"""TCP probe — checks if a TCP port is open and accepting connections."""

import asyncio
import time


async def tcp_probe(target: str, timeout: int, config_str: str = "{}") -> dict:
    """Execute a TCP connection probe.

    Target format: host:port (e.g. '192.168.1.248:5432')
    """
    try:
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            port = int(port_str)
        else:
            return {
                "status": "down",
                "response_time_ms": 0,
                "status_code": None,
                "error": "Target must be in host:port format",
            }
    except ValueError:
        return {
            "status": "down",
            "response_time_ms": 0,
            "status_code": None,
            "error": f"Invalid port in target: {target}",
        }

    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        writer.close()
        await writer.wait_closed()
        return {
            "status": "up",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": None,
        }
    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": "timeout",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": f"TCP connection to {host}:{port} timed out",
        }
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": "down",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": str(e),
        }
