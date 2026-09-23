# Contributing to Tech Sentinel Monitor

Thanks for helping! This is a small, friendly project.

## Ways to help
- **Report a bug** - open an issue with your Windows version, what you did, and what happened. Remove server names, IPs, usernames and passwords from anything you paste.
- **Suggest a feature** - open an issue or start a Discussion.
- **Send a pull request** - fork, create a branch, keep the change focused, and describe how you tested it.
- **Improve the docs** - clearer wording, screenshots and examples are always welcome.
- Look for issues labelled `good first issue` and `help wanted`, and see ROADMAP.md for ideas.

## Dev setup
```
pip install -r control-plane/requirements.txt -r probe-worker/requirements.txt
pip install -e provisioner/ pytest pytest-asyncio ruff
# tests
PYTHONPATH=control-plane:probe-worker:provisioner pytest tests/ -v   # (PowerShell: set PYTHONPATH first)
ruff check control-plane/ probe-worker/ provisioner/ tests/
```

## Ground rules
- Never include real credentials, IP addresses, share names, logs or personal data in issues or PRs.
- Be kind - we follow the [Code of Conduct](CODE_OF_CONDUCT.md).
