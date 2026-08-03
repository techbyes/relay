import json
import time
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_key
from app.config import settings
from app.db import get_db, init_db
from app.models import ApiKey, UsageLog
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.openai_provider import OpenAIProvider
from app.rate_limit import RateLimiter
from app.router import Router
from app.telemetry import log_usage

redis_client = redis.from_url(settings.redis_url, decode_responses=True)
rate_limiter = RateLimiter(redis_client)

PROVIDER_REGISTRY = {
    "openai": lambda: OpenAIProvider(settings.openai_api_key),
    "anthropic": lambda: AnthropicProvider(settings.anthropic_api_key),
}


def build_router() -> Router:
    providers = [PROVIDER_REGISTRY[name]() for name in settings.provider_order_list]
    return Router(providers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Relay - LLM Gateway", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    api_key: ApiKey = Depends(get_current_key),
    db: Session = Depends(get_db),
):
    body = await request.json()
    model = body.get("model")
    messages = body.get("messages")
    if not model or not messages:
        raise HTTPException(status_code=400, detail="`model` and `messages` are required")

    rate_limiter.check_request_rate(api_key.id, api_key.requests_per_minute)
    rate_limiter.check_budget(api_key.id, api_key.monthly_budget_usd)

    router = build_router()
    start = time.perf_counter()

    async def event_stream():
        provider_used = None
        prompt_tokens = completion_tokens = 0
        status = "success"
        try:
            async for provider_name, chunk in router.stream_chat(model, messages):
                provider_used = provider_name
                if chunk.prompt_tokens:
                    prompt_tokens = chunk.prompt_tokens
                if chunk.completion_tokens:
                    completion_tokens = chunk.completion_tokens
                payload = {
                    "provider": provider_name,
                    "delta": chunk.delta,
                    "finish_reason": chunk.finish_reason,
                }
                yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001 - surfaced to the client as an SSE error event
            status = "error"
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            if provider_used:
                cost = log_usage(
                    db,
                    api_key.id,
                    provider_used,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    latency_ms,
                    status,
                )
                rate_limiter.record_spend(api_key.id, cost)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/v1/usage/summary")
def usage_summary(db: Session = Depends(get_db)):
    """Daily cost/request rollup per provider+model, feeding the dashboard.

    Uses Postgres' date_trunc, so this endpoint targets the Postgres-backed
    dev/prod database rather than the SQLite database used in unit tests.
    """
    rows = (
        db.query(
            UsageLog.provider,
            UsageLog.model,
            func.date_trunc("day", UsageLog.created_at).label("day"),
            func.sum(UsageLog.cost_usd).label("total_cost"),
            func.count(UsageLog.id).label("requests"),
        )
        .group_by(UsageLog.provider, UsageLog.model, "day")
        .order_by("day")
        .all()
    )
    return [
        {
            "provider": r.provider,
            "model": r.model,
            "day": r.day.isoformat() if r.day else None,
            "total_cost": round(r.total_cost or 0, 6),
            "requests": r.requests,
        }
        for r in rows
    ]


@app.get("/dashboard")
def dashboard():
    return FileResponse("dashboard/index.html")
