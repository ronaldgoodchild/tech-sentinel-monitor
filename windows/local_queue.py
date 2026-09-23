"""
Tech Sentinel Monitor — In-Memory Job Queue
Replaces Redis Streams for standalone Windows operation.
Uses threading + queue.Queue for probe job distribution.
"""

import queue
import threading
import logging

logger = logging.getLogger("ts.local_queue")

# Global job queue
_job_queue: queue.Queue = queue.Queue(maxsize=10000)

# Stats
_stats_lock = threading.Lock()
_stats = {
    "jobs_enqueued": 0,
    "jobs_processed": 0,
    "jobs_failed": 0,
}


def enqueue_job(job: dict):
    """Add a probe job to the queue."""
    global _stats
    try:
        _job_queue.put_nowait(job)
        with _stats_lock:
            _stats["jobs_enqueued"] += 1
    except queue.Full:
        logger.warning("Job queue full, dropping job for monitor %s", job.get("monitor_id"))


def dequeue_job(timeout: float = 5.0) -> dict | None:
    """Get a probe job from the queue. Returns None on timeout."""
    try:
        return _job_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def mark_done():
    """Mark a job as done."""
    _job_queue.task_done()


def mark_processed():
    with _stats_lock:
        _stats["jobs_processed"] += 1


def mark_failed():
    with _stats_lock:
        _stats["jobs_failed"] += 1


def get_queue_size() -> int:
    return _job_queue.qsize()


def get_stats() -> dict:
    with _stats_lock:
        return dict(_stats)


def clear_queue():
    """Drain the queue."""
    while not _job_queue.empty():
        try:
            _job_queue.get_nowait()
        except queue.Empty:
            break
