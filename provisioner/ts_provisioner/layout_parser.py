"""Layout JSON parser with token substitution."""

import json
import os
import re


def load_layout(path: str, token_map: dict | None = None) -> dict:
    """Load a layout JSON file and perform token substitution.

    Tokens in the format {{TOKEN_NAME}} are replaced with values from:
    1. The provided token_map dict
    2. Environment variables with TS_ prefix (e.g. TS_TOKEN_NAME)
    3. Environment variables matching the token name directly
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Perform token substitution
    token_map = token_map or {}

    def _replace(match):
        token = match.group(1).strip()
        # Check token_map first
        if token in token_map:
            return token_map[token]
        # Check env with TS_ prefix
        env_val = os.environ.get(f"TS_{token}", os.environ.get(token, ""))
        return env_val or match.group(0)  # Keep original if not found

    raw = re.sub(r"\{\{(\w+)\}\}", _replace, raw)

    return json.loads(raw)


def validate_layout(layout: dict) -> list[str]:
    """Validate a layout dict and return a list of errors (empty = valid)."""
    errors = []

    if "tenant" not in layout:
        errors.append("Missing required field: tenant")
    else:
        tenant = layout["tenant"]
        if "name" not in tenant:
            errors.append("tenant.name is required")
        if "slug" not in tenant:
            errors.append("tenant.slug is required")

    for i, m in enumerate(layout.get("monitors", [])):
        prefix = f"monitors[{i}]"
        if "name" not in m:
            errors.append(f"{prefix}.name is required")
        if "monitor_type" not in m:
            errors.append(f"{prefix}.monitor_type is required")
        if "target" not in m:
            errors.append(f"{prefix}.target is required")
        if m.get("monitor_type") not in ("http", "tcp", "ping", "heartbeat"):
            errors.append(f"{prefix}.monitor_type must be http, tcp, ping, or heartbeat")

    for i, c in enumerate(layout.get("alert_channels", [])):
        prefix = f"alert_channels[{i}]"
        if "name" not in c:
            errors.append(f"{prefix}.name is required")
        if "channel_type" not in c:
            errors.append(f"{prefix}.channel_type is required")

    return errors
