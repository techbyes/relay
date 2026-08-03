from sqlalchemy.orm import Session

from app.models import UsageLog

# $ per token, not per 1K/1M -- keeps the multiplication in compute_cost trivial.
PRICING_PER_TOKEN = {
    ("openai", "gpt-4o-mini"): {"input": 0.15e-6, "output": 0.6e-6},
    ("openai", "gpt-4o"): {"input": 2.5e-6, "output": 10e-6},
    ("anthropic", "claude-3-5-haiku-20241022"): {"input": 0.8e-6, "output": 4e-6},
    ("anthropic", "claude-3-5-sonnet-20241022"): {"input": 3e-6, "output": 15e-6},
}
# Used for any model not in the table above, so an unrecognized model name
# never crashes the request -- it just costs a conservative flat estimate.
DEFAULT_PRICE = {"input": 1e-6, "output": 3e-6}


def compute_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price = PRICING_PER_TOKEN.get((provider, model), DEFAULT_PRICE)
    return prompt_tokens * price["input"] + completion_tokens * price["output"]


def log_usage(
    db: Session,
    api_key_id: int,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    status: str,
) -> float:
    cost = compute_cost(provider, model, prompt_tokens, completion_tokens)
    entry = UsageLog(
        api_key_id=api_key_id,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        status=status,
    )
    db.add(entry)
    db.commit()
    return cost
