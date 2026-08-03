from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class ChatChunk:
    """One unified streaming chunk, regardless of which provider produced it."""

    delta: str = ""
    finish_reason: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    is_final: bool = False


class ProviderError(Exception):
    """Raised whenever a provider call fails (HTTP error, timeout, bad response)."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


class Provider(ABC):
    name: str

    @abstractmethod
    def stream_chat(self, model: str, messages: list[dict]) -> AsyncIterator[ChatChunk]:
        """Yield ChatChunk objects for a chat completion, translated to a unified shape."""
        raise NotImplementedError
