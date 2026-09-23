"""Probe Worker — Redis Streams consumer that executes monitoring probes."""

import asyncio
import logging

import redis.asyncio as aioredis

from worker.config import worker_settings
from worker.persistence import close_pool, write_check_result
from worker.probes import PROBE_REGISTRY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ts.probe_worker")

STREAM_KEY = "ts:probe:jobs"
GROUP_NAME = "probe-workers"
CONSUMER_NAME = "worker-1"


async def ensure_consumer_group(redis_client: aioredis.Redis):
    """Create the consumer group if it doesn't exist."""
    try:
        await redis_client.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
        logger.info(f"Created consumer group '{GROUP_NAME}'")
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def _reschedule_job(job_data: dict, redis_client: aioredis.Redis, interval: int):
    """Sleep for interval_seconds then re-queue the job so it runs again."""
    await asyncio.sleep(interval)
    try:
        await redis_client.xadd(STREAM_KEY, job_data)
        logger.debug(f"Re-queued monitor {job_data.get('monitor_id')} after {interval}s")
    except Exception as e:
        logger.error(f"Failed to re-queue monitor {job_data.get('monitor_id')}: {e}")


async def process_job(job_data: dict, redis_client: aioredis.Redis):
    """Execute a single probe job, write results, and schedule the next run."""
    monitor_id = job_data.get("monitor_id", "")
    monitor_type = job_data.get("monitor_type", "")
    target = job_data.get("target", "")
    timeout = int(job_data.get("timeout_seconds", "10"))
    interval = int(job_data.get("interval_seconds", "60"))
    config = job_data.get("config", "{}")

    probe_fn = PROBE_REGISTRY.get(monitor_type)
    if not probe_fn:
        logger.error(f"Unknown monitor type: {monitor_type}")
        return

    logger.info(f"Probing {monitor_type}://{target} (monitor={monitor_id})")

    result = await probe_fn(target, timeout, config)

    await write_check_result(
        monitor_id=monitor_id,
        status=result["status"],
        response_time_ms=result.get("response_time_ms"),
        status_code=result.get("status_code"),
        error=result.get("error"),
    )

    logger.info(f"Result: {monitor_id} -> {result['status']} ({result.get('response_time_ms', 0):.1f}ms)")

    # Re-queue this monitor to run again after its interval
    asyncio.create_task(_reschedule_job(job_data, redis_client, interval))


async def run_worker():
    """Main worker loop — consume jobs from Redis Streams."""
    redis_client = aioredis.from_url(worker_settings.redis_url, decode_responses=True)
    await ensure_consumer_group(redis_client)

    logger.info(f"Probe worker started (concurrency={worker_settings.ts_probe_concurrency})")
    semaphore = asyncio.Semaphore(worker_settings.ts_probe_concurrency)

    while True:
        try:
            messages = await redis_client.xreadgroup(
                GROUP_NAME, CONSUMER_NAME,
                {STREAM_KEY: ">"},
                count=worker_settings.ts_probe_concurrency,
                block=5000,
            )

            if not messages:
                continue

            tasks = []
            ack_ids = []

            for stream, entries in messages:
                for msg_id, data in entries:
                    ack_ids.append(msg_id)

                    async def _run(d=data, rc=redis_client):
                        async with semaphore:
                            await process_job(d, rc)

                    tasks.append(asyncio.create_task(_run()))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Acknowledge processed messages
            if ack_ids:
                await redis_client.xack(STREAM_KEY, GROUP_NAME, *ack_ids)

        except aioredis.ConnectionError:
            logger.warning("Redis connection lost, retrying in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(1)


async def main():
    try:
        await run_worker()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
