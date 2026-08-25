# Relay

Relay is a small proxy that sits in front of OpenAI and Anthropic and exposes them
through a single API. It handles virtual API keys, per-key rate limits and budgets,
automatic failover if a provider goes down, and a dashboard for tracking cost.

I built this as a portfolio project after noticing that any team using more than one
LLM provider ends up solving the same problems over and over: different SDKs, different
auth, no single place to see spend, no fallback when a provider has an outage. Relay
solves that once, behind one endpoint. It's not running at real production scale — see
Known limitations below for what that actually means.

## How a request moves through it

```
client
  │  POST /v1/chat/completions   (Authorization: Bearer sk-relay-...)
  ▼
auth.py          - looks up the virtual key, rejects if invalid/inactive
  ▼
rate_limit.py    - checks Redis for per-minute request cap + monthly budget
  ▼
router.py        - tries providers in order, fails over to the next on error
  ▼
providers/*.py   - translates the request into each provider's own format,
                   streams the response back, converts it into one shared
                   ChatChunk shape
  ▼
telemetry.py     - works out the cost from token usage, saves it to Postgres,
                   updates the Redis spend counter
  ▼
client (SSE stream) + /v1/usage/summary + /dashboard
```

That's the whole pipeline, five steps, always in this order. No message queue or
worker fleet - at this size a plain synchronous flow is simpler and works fine.

## A few things worth explaining

**Failover only works before the first chunk is sent.** `router.py` tries the first
provider, and if it fails before sending anything back, it moves to the next one. But
once one chunk has reached the client, that's it - you can't take back bytes that
already went out over the wire. A non-streaming gateway could just retry the whole
request on a different provider; a streaming one can't once it's started talking.

**Budget checks aren't exact.** The real cost of a request is only known once the
provider finishes and reports token usage, but `rate_limit.py` checks spend at the
*start* of the request. So a request that's already in flight can push spend slightly
over budget before the next one gets blocked. Reserving an estimated cost upfront and
reconciling afterward would fix this, but felt like overkill for a project this size.

**Real provider keys never leave the server.** Clients only ever see `virtual_key`
(e.g. `sk-relay-demo`) - the actual OpenAI/Anthropic keys stay in server config.
Revoking someone's access is just flipping `is_active` to `False`.

**A bug I ran into:** FastAPI's `TestClient` only runs the app's startup code (which
calls `init_db()` against the real Postgres URL) when you use it as a context manager
(`with TestClient(app) as c:`). Without the `with`, startup gets skipped silently. My
first test runs kept hanging because they were trying to reach a Postgres instance
that wasn't running, and it took a while to figure out why. Fixed it by having tests
build their own SQLite engine directly instead of relying on the app's startup - see
`tests/conftest.py`.

## Running it

```bash
cp .env.example .env
# fill in OPENAI_API_KEY and ANTHROPIC_API_KEY in .env

docker compose up --build
```

There's no signup flow yet, so add a virtual key by hand:

```bash
docker compose exec postgres psql -U relay -d relay -c \
  "INSERT INTO api_keys (virtual_key, name, monthly_budget_usd, requests_per_minute, is_active, created_at) \
   VALUES ('sk-relay-demo', 'demo', 10.0, 20, true, now());"
```

Then call it:

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-relay-demo" \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-3-5-haiku-20241022", "messages": [{"role": "user", "content": "Say hi in five words."}]}'
```

`http://localhost:8000/dashboard` shows cost broken down by provider/model/day.

## Running the tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

Tests don't touch real providers or need Postgres/Redis running: `fakeredis` stands in
for Redis, SQLite in memory stands in for Postgres, and the failover tests use fake
`Provider` implementations instead of hitting real APIs.

## Known limitations

- There's no lock between "budget check passed" and "cost gets recorded," so two
  requests from the same key firing at almost the same instant could both pass the
  budget check before either one's cost lands. Fine at this scale; would need a
  reservation system to handle it properly under real concurrency.
- `/v1/usage/summary` uses Postgres' `date_trunc`, so it only works against the real
  database - not the SQLite one used in tests.
- Only OpenAI and Anthropic are wired up. Adding another provider means writing one
  file in `app/providers/` implementing the `Provider` interface in `base.py`, plus
  registering it in `main.py`.
- I haven't load-tested this. It's built the way a production service would be, but
  "built correctly" and "verified under load" are different claims, and I'm only
  making the first one.
