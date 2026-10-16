"""Which network address the standalone API and status page listen on."""

LOCAL_ONLY = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"


def resolve_bind_host(value: str | None) -> str:
    """Return the address to bind to. Blank means this PC only (127.0.0.1)."""
    value = (value or "").strip()
    return value or LOCAL_ONLY


def is_local_only(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")
