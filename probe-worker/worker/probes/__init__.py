"""Probe registry — maps monitor_type to probe function."""

from worker.probes.heartbeat_probe import heartbeat_probe
from worker.probes.http_probe import http_probe
from worker.probes.ping_probe import ping_probe
from worker.probes.tcp_probe import tcp_probe

PROBE_REGISTRY = {
    "http": http_probe,
    "tcp": tcp_probe,
    "ping": ping_probe,
    "heartbeat": heartbeat_probe,
}
