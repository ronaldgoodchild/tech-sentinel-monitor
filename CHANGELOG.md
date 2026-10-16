# Changelog

Reconstructed from the original development history (April 2026).

## [Unreleased]
- Windows standalone EXE is now published on the Releases page (with SHA-256). Fixed `windows/build_exe.py` on Windows (`--add-data` used `:` instead of the OS path separator). Removed generated PyInstaller `.spec` files that contained local paths.
- Dependencies: redis-py 8.1 (control plane and probe worker). Verified against a real Redis 7 server: job publish, consumer-group create (incl. already-exists), read, ack and connection-error handling. Control plane now closes its Redis client with `aclose()` (`close()` is deprecated).
- Security: Windows standalone API and status page now listen on 127.0.0.1 (this PC only) by default instead of every interface. The launcher's "Server IP" setting is honoured (it was ignored before); set it to 0.0.0.0 to accept other PCs and agents on a trusted network
- Security: Windows standalone status/manage pages now HTML-escape monitor, tenant, group, incident, audit and agent-reported data (server-rendered and client-side), fixing stored XSS; non-http(s) monitor targets are no longer rendered as links; regression tests added
- Security: tenant endpoints are no longer open. Creating, listing and deleting tenants needs the admin key (`X-TS-Admin-Key` = `TS_API_KEY`, no default; endpoints are disabled until it is set); `GET /api/v1/tenants/{id}` no longer returns API keys; new `GET /api/v1/tenants/me` for a tenant to read its own record. The provisioner takes `--admin-key` / `TS_API_KEY`; agents use `/tenants/me`. **Breaking for server deployments: set TS_API_KEY.**
- CI: integration test now waits for the API and status page to be healthy (up to 3 minutes) instead of a fixed 15-second sleep, which made it flaky on busy runners
- Fix: demo layout's Backup Agent monitor used `timeout_seconds: 600` (API maximum is 120), which made the CI integration test fail
- Security: Windows standalone edition no longer ships a hard-coded JWT signing secret; it uses TS_JWT_SECRET or a random per-install secret generated on first run
- Fix: `ts-provisioner validate` crashed (`missing 1 required positional argument: 'ctx'`) - added `@click.pass_context`
- Fix: recovery-notification test patched the wrong module; all 44 tests pass
- Lint: unused imports removed, ruff configured (`ruff.toml`)
- Demo network layout sanitised to example values; licensed under MIT

## [1.2.0] - 2026-04-14 (Windows standalone edition)
- Desktop launcher with local SQLite database, probe worker, alert engine, status page and NOC layout importer
- Incident history log, version control for monitor configs
- Newer Windows system agent (`agents/windows_system_agent.py`)

## [1.0.0] - 2026-04-12 (server edition)
- Control plane API, probe worker (HTTP / TCP / ping / heartbeat), status pages, provisioner CLI
- Docker Compose, Helm chart, GitHub Actions CI, runbook and secrets docs
