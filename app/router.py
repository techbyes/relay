from typing import AsyncIterator

from app.providers.base import ChatChunk, Provider, ProviderError


class Router:
    """Tries providers in order and fails over on error.

    Failover only works up to the first chunk successfully streamed to the
    caller: once bytes have been sent over the wire, they can't be un-sent,
    so a mid-stream failure on the second+ chunk cannot be silently retried
    on another provider. This "peek the first chunk" strategy is the
    deliberate boundary of what failover can safely do in a streaming system
    -- it's a real constraint of this class of problem, not an oversight.
    """

    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError("Router needs at least one provider")
        self.providers = providers

    async def stream_chat(self, model: str, messages: list[dict]) -> AsyncIterator[tuple[str, ChatChunk]]:
        last_error: Exception | None = None

        for provider in self.providers:
            gen = provider.stream_chat(model, messages)
            try:
                first_chunk = await gen.__anext__()
            except StopAsyncIteration:
                continue
            except ProviderError as e:
                last_error = e
                continue

            # Committed to this provider now -- no more failover past this point.
            yield provider.name, first_chunk
            async for chunk in gen:
                yield provider.name, chunk
            return

        raise last_error or ProviderError("router", "All providers failed")
