"""Ping (ICMP) probe — checks host reachability via subprocess ping."""

import asyncio
import platform
import time


async def ping_probe(target: str, timeout: int, config_str: str = "{}") -> dict:
    """Execute a ping probe against the target host."""
    system = platform.system().lower()

    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), target]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout), target]

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
        elapsed_ms = (time.monotonic() - start) * 1000

        if proc.returncode == 0:
            # Parse response time from output
            rtt = _parse_rtt(stdout.decode())
            return {
                "status": "up",
                "response_time_ms": rtt or elapsed_ms,
                "status_code": None,
                "error": None,
            }
        else:
            return {
                "status": "down",
                "response_time_ms": elapsed_ms,
                "status_code": None,
                "error": "Host unreachable",
            }
    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": "timeout",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": "Ping timed out",
        }
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": "down",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": str(e),
        }


def _parse_rtt(output: str) -> float | None:
    """Extract round-trip time from ping output."""
    import re
    # Linux: rtt min/avg/max/mdev = 0.123/0.456/0.789/0.012 ms
    match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", output)
    if match:
        return float(match.group(1))
    # Windows: Average = 1ms
    match = re.search(r"Average\s*=\s*(\d+)ms", output)
    if match:
        return float(match.group(1))
    # macOS: round-trip min/avg/max/stddev = 0.123/0.456/0.789/0.012 ms
    match = re.search(r"round-trip min/avg/max/stddev = [\d.]+/([\d.]+)/", output)
    if match:
        return float(match.group(1))
    return None
