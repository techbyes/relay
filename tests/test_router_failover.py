from typing import AsyncIterator

import pytest

from app.providers.base import ChatChunk, Provider, ProviderError
from app.router import Router


class FailingProvider(Provider):
    name = "failing"

    async def stream_chat(self, model: str, messages: list[dict]) -> AsyncIterator[ChatChunk]:
        raise ProviderError(self.name, "simulated outage")
        yield  # pragma: no cover - unreachable, but makes this a generator function


class WorkingProvider(Provider):
    name = "working"

    async def stream_chat(self, model: str, messages: list[dict]) -> AsyncIterator[ChatChunk]:
        yield ChatChunk(delta="hello ")
        yield ChatChunk(delta="world", finish_reason="stop", prompt_tokens=5, completion_tokens=2, is_final=True)


async def test_failover_to_second_provider_when_first_fails():
    router = Router([FailingProvider(), WorkingProvider()])
    chunks = [c async for c in router.stream_chat("test-model", [{"role": "user", "content": "hi"}])]

    providers_seen = {name for name, _ in chunks}
    assert providers_seen == {"working"}
    assert "".join(c.delta for _, c in chunks) == "hello world"


async def test_all_providers_failing_raises_provider_error():
    router = Router([FailingProvider(), FailingProvider()])
    with pytest.raises(ProviderError):
        async for _ in router.stream_chat("test-model", []):
            pass


async def test_first_working_provider_is_used_without_trying_the_rest():
    router = Router([WorkingProvider(), FailingProvider()])
    chunks = [c async for c in router.stream_chat("test-model", [])]
    assert {name for name, _ in chunks} == {"working"}
