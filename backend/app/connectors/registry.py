"""Provider → Connector registry.

Adding a connector = drop a module under app/connectors/, register it here.
The worker and routers always look up through this registry.
"""

from __future__ import annotations

from app.connectors.base import Connector
from app.connectors.notion import NotionConnector

_REGISTRY: dict[str, Connector] = {
    "notion": NotionConnector(),
}


def get(provider: str) -> Connector:
    try:
        return _REGISTRY[provider]
    except KeyError as e:
        raise KeyError(f"no connector registered for provider {provider!r}") from e


def has(provider: str) -> bool:
    return provider in _REGISTRY


def providers() -> list[str]:
    return sorted(_REGISTRY)
