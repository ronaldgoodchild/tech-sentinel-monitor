# Changelog

Reconstructed from the original development history (April 2026).

## [Unreleased]
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
