import json
from typing import AsyncIterator

import httpx

from app.providers.base import ChatChunk, Provider, ProviderError


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com/v1"):
        self.api_key = api_key
        self.base_url = base_url

    @staticmethod
    def _split_system(messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Anthropic takes the system prompt as a top-level field, not a message."""
        system = None
        rest = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                rest.append({"role": m["role"], "content": m["content"]})
        return system, rest

    async def stream_chat(self, model: str, messages: list[dict]) -> AsyncIterator[ChatChunk]:
        system, chat_messages = self._split_system(messages)
        payload = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": 1024,
            "stream": True,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        prompt_tokens = 0

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/messages", json=payload, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise ProviderError(
                            self.name, f"HTTP {resp.status_code}: {body.decode(errors='ignore')[:200]}"
                        )

                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue

                        event = json.loads(line[len("data:"):].strip())
                        etype = event.get("type")

                        if etype == "message_start":
                            prompt_tokens = event["message"]["usage"].get("input_tokens", 0)

                        elif etype == "content_block_delta":
                            text = event.get("delta", {}).get("text", "")
                            yield ChatChunk(delta=text)

                        elif etype == "message_delta":
                            usage = event.get("usage", {})
                            yield ChatChunk(
                                delta="",
                                finish_reason=event.get("delta", {}).get("stop_reason"),
                                prompt_tokens=prompt_tokens,
                                completion_tokens=usage.get("output_tokens", 0),
                                is_final=True,
                            )

                        elif etype == "error":
                            raise ProviderError(self.name, str(event.get("error")))
        except httpx.HTTPError as e:
            raise ProviderError(self.name, str(e)) from e
