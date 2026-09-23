"""Tests for the provisioner CLI and layout parser."""

import json

from click.testing import CliRunner
from ts_provisioner.cli import cli
from ts_provisioner.layout_parser import load_layout, validate_layout


class TestLayoutParser:
    """Test layout file parsing."""

    def test_load_valid_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"tenant": {"name": "Test", "slug": "test"}}')
        result = load_layout(str(f))
        assert result["tenant"]["name"] == "Test"

    def test_multiple_token_substitutions(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"tenant": {"name": "{{A}}", "slug": "{{B}}"}}')
        result = load_layout(str(f), {"A": "Alpha", "B": "beta"})
        assert result["tenant"]["name"] == "Alpha"
        assert result["tenant"]["slug"] == "beta"

    def test_validate_complete_layout(self, sample_layout):
        errors = validate_layout(sample_layout)
        assert errors == []

    def test_validate_empty_layout(self):
        errors = validate_layout({})
        assert len(errors) > 0

    def test_validate_missing_monitor_target(self):
        layout = {
            "tenant": {"name": "X", "slug": "x"},
            "monitors": [{"name": "Y", "monitor_type": "http"}],
        }
        errors = validate_layout(layout)
        assert any("target" in e for e in errors)

    def test_validate_missing_channel_type(self):
        layout = {
            "tenant": {"name": "X", "slug": "x"},
            "alert_channels": [{"name": "Y"}],
        }
        errors = validate_layout(layout)
        assert any("channel_type" in e for e in errors)


class TestCLI:
    """Test provisioner CLI commands."""

    def test_validate_command_valid(self, tmp_path, sample_layout):
        f = tmp_path / "layout.json"
        f.write_text(json.dumps(sample_layout))

        runner = CliRunner()
        result = runner.invoke(cli, ["validate", str(f)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower() or "\u2705" in result.output

    def test_validate_command_invalid(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text('{"monitors": [{"name": "X"}]}')

        runner = CliRunner()
        result = runner.invoke(cli, ["validate", str(f)])
        assert result.exit_code != 0

    def test_provision_dry_run(self, tmp_path, sample_layout):
        f = tmp_path / "layout.json"
        f.write_text(json.dumps(sample_layout))

        runner = CliRunner()
        result = runner.invoke(cli, ["provision", str(f), "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "Dry run" in result.output

    def test_status_command_unreachable(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--api-url", "http://localhost:99999", "status"])
        assert result.exit_code != 0

    def test_provision_with_tokens(self, tmp_path):
        f = tmp_path / "layout.json"
        f.write_text(json.dumps({
            "tenant": {"name": "{{COMPANY}}", "slug": "test"},
            "monitors": [],
        }))

        runner = CliRunner()
        result = runner.invoke(cli, ["provision", str(f), "-t", "COMPANY=TestCo", "--dry-run"])
        assert result.exit_code == 0
