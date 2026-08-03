# Relay — a small, honest LLM gateway

Relay is a unified proxy that sits in front of multiple LLM providers (OpenAI, Anthropic)
behind a single API, with virtual API keys, per-key rate limiting and budgets, automatic
failover, and a cost dashboard. It's a scaled-down, junior-appropriate version of what
products like Portkey, LiteLLM, and Cloudflare AI Gateway do commercially.

This is a portfolio project. It is architected the way a production system would be,
but it has **not** been run at production scale — see [Known limitations](#known-limitations)
for exactly where the line is, instead of overclaiming.

## Why this exists

Any team using more than one LLM provider re-solves the same problems: different SDKs,
different auth schemes, no unified view of spend, no automatic fallback when a provider
has an outage. Relay solves this once, behind one OpenAI-compatible-ish endpoint.

## Architecture

```
client
  │  POST /v1/chat/completions   (Authorization: Bearer sk-relay-...)
  ▼
auth.py          — resolve virtual key → ApiKey row, reject if invalid/inactive
  ▼
rate_limit.py    — Redis: per-minute request cap + monthly budget check
  ▼
router.py        — try providers in configured order, fail over on error
  ▼
providers/*.py   — translate the unified request into each provider's own
                   wire format, stream the response back, translate deltas
                   into a unified ChatChunk
  ▼
telemetry.py     — compute cost from token usage, persist to Postgres,
                   update the Redis spend counter
  ▼
client (SSE stream) + /v1/usage/summary + /dashboard (cost charts)
```

Every request flows through exactly these five stages, in this order. That's the entire
system — no message queue, no separate worker fleet, because at this scale a synchronous
in-process pipeline is simpler and just as correct.

## Key design decisions (and their trade-offs)

**Streaming failover only covers the first chunk.**
`router.py` calls the first provider, and if it raises *before yielding anything*, moves
to the next one. Once a single chunk has reached the client, no more failover happens —
you can't un-send bytes that already went out over the wire. This is a genuine constraint
of streaming systems, not a shortcut: a request/response (non-streaming) gateway could
retry a failed request from scratch on any provider; a streaming one can't, once it's
started talking.

**Budget checks are approximate, not exact.**
The real cost of a request is only known after the provider finishes and reports token
usage. `rate_limit.py` checks spend *as of the start of the request*, so a single
in-flight request can push total spend slightly past budget before the next one gets
blocked. A stricter design would reserve an estimated cost up front and reconcile
afterwards — that's real added complexity for a marginal accuracy gain at this scale, so
it's documented here instead of solved.

**Virtual keys, never real ones, cross the wire to callers.**
`ApiKey.virtual_key` is what a client sees and sends; the real OpenAI/Anthropic keys live
only in server config. Revoking a caller's access is flipping `is_active` to `False`, with
no need to rotate the real provider key.

**One bug I hit while building this:** the FastAPI `TestClient` triggers the app's
lifespan/startup event (which calls `init_db()` against the real Postgres URL from
settings) *only* when used as a context manager (`with TestClient(app) as c:`). Using it
without the `with` block skips lifespan entirely. Early test runs were hanging trying to
connect to a Postgres instance that wasn't running. Fix: tests use a fixture-created
SQLite engine directly and never trigger the app's own startup event — see
`tests/conftest.py`.

## Running it

```bash
cp .env.example .env
# fill in OPENAI_API_KEY and ANTHROPIC_API_KEY in .env

docker compose up --build
```

Then seed a virtual API key (there's no signup flow — this is infrastructure, not a
product with a UI for that yet):

```bash
docker compose exec postgres psql -U relay -d relay -c \
  "INSERT INTO api_keys (virtual_key, name, monthly_budget_usd, requests_per_minute, is_active, created_at) \
   VALUES ('sk-relay-demo', 'demo', 10.0, 20, true, now());"
```

Call it:

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-relay-demo" \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-3-5-haiku-20241022", "messages": [{"role": "user", "content": "Say hi in five words."}]}'
```

Open `http://localhost:8000/dashboard` to see cost by provider/model/day.

## Running the tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

Tests don't call real providers or need Postgres/Redis running — `fakeredis` stands in
for Redis, an in-memory SQLite engine stands in for Postgres, and the router failover
tests use fake in-repo `Provider` implementations instead of real HTTP calls.

## Known limitations

- No auth/rate-limit/budget checks are enforced *between* the request being accepted and
  the provider call starting except what's described above — there's no distributed lock,
  so extremely concurrent requests from the same key could both pass the budget check
  before either one's cost is recorded. Acceptable at this scale; would need a different
  design (e.g. a reservation system) at high concurrency.
- `/v1/usage/summary` uses Postgres' `date_trunc`, so it only works against the real
  Postgres database, not the SQLite database used in tests.
- Only two providers are implemented (OpenAI, Anthropic). Adding a third means writing one
  more file in `app/providers/` that implements the `Provider` interface in `base.py` —
  no other file needs to change except the registry in `main.py`.
- No load test numbers are published yet — the honest status is "correct, production-shaped
  architecture," not "verified under production load."
