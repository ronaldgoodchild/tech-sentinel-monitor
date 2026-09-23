# Tech Sentinel Monitor — Runbook

## Startup

```bash
# Full stack
docker compose up -d --build

# Verify all services
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8001/health
```

## Shutdown

```bash
docker compose down          # Stop services, keep data
docker compose down -v       # Stop services AND delete volumes (destructive!)
```

## Health Checks

| Service | Endpoint | Expected |
|---------|----------|----------|
| Control Plane | `GET /health` on `:8000` | `{"status": "ok"}` |
| Status Page | `GET /health` on `:8001` | `{"status": "ok"}` |
| TimescaleDB | `pg_isready -U tsadmin` | exit code 0 |
| Redis | `redis-cli ping` | `PONG` |

## Troubleshooting

### Control Plane won't start
1. Check TimescaleDB is healthy: `docker compose logs timescaledb`
2. Verify migration ran: `docker compose exec timescaledb psql -U tsadmin -d techsentinel -c '\dt'`
3. Check connection string in `.env`

### Probe Worker not processing jobs
1. Check Redis is healthy: `docker compose logs redis`
2. Verify consumer group exists: `docker compose exec redis redis-cli XINFO GROUPS ts:probe:jobs`
3. Check pending messages: `docker compose exec redis redis-cli XLEN ts:probe:jobs`
4. Review worker logs: `docker compose logs probe-worker`

### Status page shows "unknown" for all monitors
1. Verify monitors exist: `curl -H "X-TS-API-Key: <key>" http://localhost:8000/api/v1/monitors/`
2. Check probe worker is running and producing results
3. Verify status page can reach control plane (internal Docker networking)

### Alerts not firing
1. Check consecutive failure count vs threshold (`TS_ALERT_CONSECUTIVE_FAILURES`)
2. Verify alert channels are configured: `curl -H "X-TS-API-Key: <key>" http://localhost:8000/api/v1/alert-channels/`
3. Check webhook URLs are reachable from the container

## Scaling

### Horizontal scaling (Probe Workers)
```bash
docker compose up -d --scale probe-worker=3
```
Redis Streams consumer groups distribute work automatically.

### Database maintenance
```sql
-- Check hypertable size
SELECT hypertable_size('check_results');

-- View compression stats
SELECT * FROM timescaledb_information.compressed_chunk_stats;

-- Manual compression
SELECT compress_chunk(c) FROM show_chunks('check_results', older_than => INTERVAL '7 days') c;
```

## Backup & Restore

### Backup
```bash
docker compose exec timescaledb pg_dump -U tsadmin techsentinel > backup_$(date +%Y%m%d).sql
```

### Restore
```bash
docker compose exec -T timescaledb psql -U tsadmin techsentinel < backup_20260412.sql
```

## Disaster Recovery

1. Stop all services: `docker compose down`
2. Restore database from backup
3. Start services: `docker compose up -d`
4. Verify health endpoints
5. Re-run provisioner to ensure all monitors are scheduled: `ts-provisioner provision layout.json`
