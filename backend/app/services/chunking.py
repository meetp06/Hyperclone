"""Heuristic text chunker.

No model tokenizer — we approximate `tokens ≈ chars / 4` (English text).
Good enough for Phase 2 retrieval; cheaper than loading tiktoken on the
worker hot path.

SCALE: when accurate counts matter (very long Notion pages, code blocks,
non-Latin text) swap in the embedding model's tokenizer.
"""

from __future__ import annotations

from collections.abc import Iterator

_CHARS_PER_TOKEN = 4


def _to_chars(tokens: int) -> int:
    return max(1, tokens * _CHARS_PER_TOKEN)


def chunk_text(
    text: str,
    *,
    target_tokens: int,
    overlap_tokens: int,
) -> Iterator[tuple[int, str]]:
    """Yield `(chunk_index, chunk_text)`.

    Tries to break on paragraph boundaries; falls back to char windows
    when a paragraph is larger than the target. Always emits at least
    one chunk for non-empty input.
    """
    if not text or not text.strip():
        return

    target_chars = _to_chars(target_tokens)
    overlap_chars = _to_chars(overlap_tokens)
    if overlap_chars >= target_chars:
        overlap_chars = target_chars // 4

    # First pass: group paragraphs into ~target_chars buckets.
    paragraphs = [p for p in text.split("\n") if p.strip()]
    buckets: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for p in paragraphs:
        if cur_len + len(p) + 1 > target_chars and cur:
            buckets.append("\n".join(cur))
            cur = [p]
            cur_len = len(p)
        else:
            cur.append(p)
            cur_len += len(p) + 1
    if cur:
        buckets.append("\n".join(cur))

    # Second pass: any bucket still larger than target_chars gets split
    # by sliding window so we don't ship a 50k-char chunk.
    out: list[str] = []
    for b in buckets:
        if len(b) <= target_chars:
            out.append(b)
            continue
        step = max(1, target_chars - overlap_chars)
        for start in range(0, len(b), step):
            piece = b[start : start + target_chars]
            if piece.strip():
                out.append(piece)
            if start + target_chars >= len(b):
                break

    for i, piece in enumerate(out):
        yield i, piece
