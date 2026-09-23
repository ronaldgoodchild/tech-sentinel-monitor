# Tech Sentinel Monitor — Maintenance Windows

## Overview

Maintenance windows suppress alerting during scheduled maintenance periods. During a maintenance window:
- Probes continue to run (data is still collected)
- Alerts are suppressed (no notifications sent)
- Status page shows "Maintenance" instead of "Down"

## Per-Monitor Maintenance

Set a monitor to "paused" status during maintenance:

```bash
# Pause a monitor
curl -X PATCH http://localhost:8000/api/v1/monitors/{monitor_id}/status \
  -H "X-TS-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"status": "paused"}'

# Resume after maintenance
curl -X PATCH http://localhost:8000/api/v1/monitors/{monitor_id}/status \
  -H "X-TS-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}'
```

## Tenant-Wide Maintenance

Pause all monitors for a tenant:

```bash
# Get all monitors
MONITORS=$(curl -s http://localhost:8000/api/v1/monitors/ \
  -H "X-TS-API-Key: <key>" | jq -r '.[].id')

# Pause all
for id in $MONITORS; do
  curl -X PATCH "http://localhost:8000/api/v1/monitors/$id/status" \
    -H "X-TS-API-Key: <key>" \
    -H "Content-Type: application/json" \
    -d '{"status": "paused"}'
done

# Resume all (same loop with "active")
```

## Recurring Maintenance Schedules

For recurring windows (e.g., every Sunday 2-4 AM), use a cron job:

```bash
# /etc/cron.d/ts-maintenance
# Pause at 2:00 AM Sunday
0 2 * * 0 /usr/local/bin/ts-maintenance.sh pause
# Resume at 4:00 AM Sunday
0 4 * * 0 /usr/local/bin/ts-maintenance.sh resume
```

## Status Page Behavior During Maintenance

- Paused monitors are excluded from status calculations
- The status page shows only active monitors
- Overall status reflects only non-maintenance monitors

## Best Practices

1. **Communicate**: Notify stakeholders before maintenance
2. **Time-bound**: Always set a resume time — don't leave monitors paused indefinitely
3. **Verify**: After maintenance, check that all monitors are active and reporting
4. **Document**: Log maintenance windows for SLA calculations
