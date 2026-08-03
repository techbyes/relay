import json
from typing import AsyncIterator

import httpx

from app.providers.base import ChatChunk, Provider, ProviderError


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url

    async def stream_chat(self, model: str, messages: list[dict]) -> AsyncIterator[ChatChunk]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            # Without this flag OpenAI never sends a usage block, and we'd have
            # no way to compute cost for the request.
            "stream_options": {"include_usage": True},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise ProviderError(
                            self.name, f"HTTP {resp.status_code}: {body.decode(errors='ignore')[:200]}"
                        )

                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            return

                        event = json.loads(data)
                        usage = event.get("usage") or {}
                        choices = event.get("choices") or [{}]
                        choice = choices[0]
                        delta = (choice.get("delta") or {}).get("content") or ""

                        yield ChatChunk(
                            delta=delta,
                            finish_reason=choice.get("finish_reason"),
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            is_final=bool(usage),
                        )
        except httpx.HTTPError as e:
            raise ProviderError(self.name, str(e)) from e
