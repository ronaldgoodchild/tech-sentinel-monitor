"""HTTP probe — checks URL availability, status code, optional body match."""

import json
import time

import httpx


async def http_probe(target: str, timeout: int, config_str: str = "{}") -> dict:
    """Execute an HTTP probe against the target URL.

    Returns dict with: status, response_time_ms, status_code, error
    """
    config = json.loads(config_str) if isinstance(config_str, str) else config_str
    method = config.get("method", "GET").upper()
    expected_status = config.get("expected_status", 200)
    body_contains = config.get("body_contains", None)
    headers = config.get("headers", {})

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.request(method, target, headers=headers)
            elapsed_ms = (time.monotonic() - start) * 1000

            # Check status code
            if resp.status_code != expected_status:
                return {
                    "status": "down",
                    "response_time_ms": elapsed_ms,
                    "status_code": resp.status_code,
                    "error": f"Expected {expected_status}, got {resp.status_code}",
                }

            # Check body content
            if body_contains and body_contains not in resp.text:
                return {
                    "status": "down",
                    "response_time_ms": elapsed_ms,
                    "status_code": resp.status_code,
                    "error": f"Body does not contain '{body_contains}'",
                }

            return {
                "status": "up",
                "response_time_ms": elapsed_ms,
                "status_code": resp.status_code,
                "error": None,
            }
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": "timeout",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": "Connection timed out",
        }
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": "down",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": str(e),
        }
