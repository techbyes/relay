from app.telemetry import compute_cost


def test_known_model_uses_its_own_pricing():
    cost = compute_cost("openai", "gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost == 0.15 + 0.6


def test_unknown_model_falls_back_to_default_price_without_raising():
    cost = compute_cost("openai", "some-future-model", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost == 1 + 3


def test_zero_tokens_costs_nothing():
    assert compute_cost("anthropic", "claude-3-5-haiku-20241022", 0, 0) == 0
