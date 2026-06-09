"""LLMProvider interface + Anthropic / OpenAI / stub implementations.

Used by grounded chat and the automations draft generator. The stub
exists so the whole app boots cleanly without any API key — local dev
keeps working when ANTHROPIC_API_KEY / OPENAI_API_KEY are unset.

SCALE: single provider, single model per request today. At enterprise
scale this becomes a small routing layer: short prompts → Haiku, RAG
synth → Sonnet, long context → an explicit long-context model; per-
workspace overrides for residency / vendor; circuit-breaker on the
provider call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any

from app.config import get_settings


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResult:
    text: str
    usage: LLMUsage


@dataclass
class LLMStreamEvent:
    """One streamed event. `delta` is the new text chunk; `done` true on
    the terminal event which also carries the final usage tallies."""

    delta: str = ""
    done: bool = False
    usage: LLMUsage | None = None


class LLMProvider(ABC):
    name: str = ""
    model: str = ""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult: ...

    @abstractmethod
    def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMStreamEvent]: ...


# ---------- Stub ----------


class StubLLMProvider(LLMProvider):
    """Deterministic templated answer. Token counts ≈ chars/4."""

    name = "stub"

    def __init__(self) -> None:
        self.model = "pioneer-stub-llm-v1"

    @staticmethod
    def _last_user(messages: list[LLMMessage]) -> str:
        for m in reversed(messages):
            if m.role == "user":
                return m.content
        return ""

    @staticmethod
    def _build_text(messages: list[LLMMessage]) -> tuple[str, LLMUsage]:
        user_q = StubLLMProvider._last_user(messages)
        joined = "\n".join(m.content for m in messages)
        in_tokens = max(1, len(joined) // 4)

        # Pull the question; if there's context, summarize what we'd cite.
        text = (
            "(stub LLM) I read the provided workspace context for: "
            f"{user_q.strip().splitlines()[0][:140] if user_q else 'your query'}. "
            "Plug in a real Anthropic or OpenAI key to get a synthesized answer."
        )
        out_tokens = max(1, len(text) // 4)
        return text, LLMUsage(input_tokens=in_tokens, output_tokens=out_tokens)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        text, usage = self._build_text(messages)
        return LLMResult(text=text, usage=usage)

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        text, usage = self._build_text(messages)
        # Yield in word-chunks so the client sees streaming UX.
        for i, chunk in enumerate(_word_chunks(text, n=4)):
            yield LLMStreamEvent(delta=chunk + (" " if i >= 0 else ""))
        yield LLMStreamEvent(done=True, usage=usage)


def _word_chunks(text: str, *, n: int) -> Iterable[str]:
    words = text.split(" ")
    for i in range(0, len(words), n):
        yield " ".join(words[i : i + n])


# ---------- Anthropic ----------


class AnthropicLLMProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        s = get_settings()
        if not s.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = AsyncAnthropic(api_key=s.anthropic_api_key)
        self.model = s.llm_model
        self._defaults = dict(max_tokens=s.llm_max_tokens, temperature=s.llm_temperature)

    @staticmethod
    def _split(messages: list[LLMMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        system_chunks: list[str] = []
        turns: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_chunks.append(m.content)
            else:
                turns.append({"role": m.role, "content": m.content})
        return ("\n\n".join(system_chunks) if system_chunks else None, turns)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        system, turns = self._split(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self._defaults["max_tokens"],
            "temperature": temperature if temperature is not None else self._defaults["temperature"],
            "messages": turns,
        }
        if system:
            kwargs["system"] = system
        msg = await self._client.messages.create(**kwargs)
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        usage = LLMUsage(
            input_tokens=getattr(msg.usage, "input_tokens", 0),
            output_tokens=getattr(msg.usage, "output_tokens", 0),
        )
        return LLMResult(text=text, usage=usage)

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        system, turns = self._split(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self._defaults["max_tokens"],
            "temperature": temperature if temperature is not None else self._defaults["temperature"],
            "messages": turns,
        }
        if system:
            kwargs["system"] = system
        in_tokens = 0
        out_tokens = 0
        async with self._client.messages.stream(**kwargs) as stream:
            async for delta in stream.text_stream:
                if delta:
                    yield LLMStreamEvent(delta=delta)
            final = await stream.get_final_message()
            in_tokens = getattr(final.usage, "input_tokens", 0)
            out_tokens = getattr(final.usage, "output_tokens", 0)
        yield LLMStreamEvent(done=True, usage=LLMUsage(in_tokens, out_tokens))


# ---------- OpenAI ----------


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        from openai import AsyncOpenAI

        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = AsyncOpenAI(api_key=s.openai_api_key)
        self.model = s.llm_model
        self._defaults = dict(max_tokens=s.llm_max_tokens, temperature=s.llm_temperature)

    @staticmethod
    def _as_chat(messages: list[LLMMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=self._as_chat(messages),
            max_tokens=max_tokens or self._defaults["max_tokens"],
            temperature=temperature if temperature is not None else self._defaults["temperature"],
        )
        text = resp.choices[0].message.content or ""
        u = resp.usage
        usage = LLMUsage(
            input_tokens=getattr(u, "prompt_tokens", 0) or 0,
            output_tokens=getattr(u, "completion_tokens", 0) or 0,
        )
        return LLMResult(text=text, usage=usage)

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=self._as_chat(messages),
            max_tokens=max_tokens or self._defaults["max_tokens"],
            temperature=temperature if temperature is not None else self._defaults["temperature"],
            stream=True,
            stream_options={"include_usage": True},
        )
        usage = LLMUsage()
        async for event in stream:
            if event.choices:
                delta = event.choices[0].delta.content or ""
                if delta:
                    yield LLMStreamEvent(delta=delta)
            if event.usage is not None:
                usage = LLMUsage(
                    input_tokens=event.usage.prompt_tokens or 0,
                    output_tokens=event.usage.completion_tokens or 0,
                )
        yield LLMStreamEvent(done=True, usage=usage)


# ---------- Factory ----------


_default: LLMProvider | None = None


def get_llm() -> LLMProvider:
    """Resolve LLM by settings. Never raises — falls back to stub when a
    real provider can't be initialized (missing key) so the API stays up.
    """
    global _default
    if _default is not None:
        return _default
    s = get_settings()
    choice = (s.llm_provider or "stub").lower()
    try:
        if choice == "anthropic":
            _default = AnthropicLLMProvider()
        elif choice == "openai":
            _default = OpenAILLMProvider()
        else:
            _default = StubLLMProvider()
    except Exception:  # noqa: BLE001
        # SCALE: log the fallback at WARN and emit a metric; today we
        # silently degrade to keep dev frictionless.
        _default = StubLLMProvider()
    return _default


def reset_llm() -> None:
    """Tests clear the cached provider."""
    global _default
    _default = None
