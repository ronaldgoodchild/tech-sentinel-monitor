# Roadmap / ideas

Comment on (or open) an issue first so we don't duplicate work.

## Good first issues
- [x] Add screenshots of the dashboard and a status page to the README
- [x] Tighten the `pytest.raises(Exception)` assertions in `tests/test_monitors_crud.py` to specific exception types
- [ ] Split `windows/launcher.py` (80 KB) and `windows/local_status_page.py` (98 KB) into smaller modules
- [ ] Add type hints and a `py.typed` marker to the provisioner
- [ ] Publish the provisioner to PyPI

## Features
- [ ] SSL certificate expiry monitor
- [ ] Keyword / JSON-path assertions for HTTP monitors
- [ ] Email and Microsoft Teams / Discord alert channels
- [ ] Public status-page custom domains and incident posts
- [ ] Prometheus `/metrics` endpoint and Grafana dashboard
- [ ] Multi-region probe workers
- [ ] Agent auto-update

## Quality & security
- [ ] Rate-limit the auth endpoint; rotate API keys from the UI
- [ ] Container image publishing (GHCR) from CI
- [ ] Windows EXE built and attached to releases by GitHub Actions
