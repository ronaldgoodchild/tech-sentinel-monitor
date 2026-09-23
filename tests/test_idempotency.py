"""Tests for idempotent provisioning — re-running should produce same IDs."""

from ts_provisioner.layout_parser import load_layout, validate_layout


class TestLayoutValidation:
    """Test layout parsing and validation."""

    def test_valid_layout(self, sample_layout):
        errors = validate_layout(sample_layout)
        assert errors == []

    def test_missing_tenant(self):
        errors = validate_layout({"monitors": []})
        assert any("tenant" in e for e in errors)

    def test_missing_monitor_fields(self):
        layout = {
            "tenant": {"name": "X", "slug": "x"},
            "monitors": [{"name": "Y"}],  # missing type and target
        }
        errors = validate_layout(layout)
        assert len(errors) >= 2

    def test_invalid_monitor_type(self):
        layout = {
            "tenant": {"name": "X", "slug": "x"},
            "monitors": [{"name": "Y", "monitor_type": "ftp", "target": "x.com"}],
        }
        errors = validate_layout(layout)
        assert any("monitor_type" in e for e in errors)


class TestTokenSubstitution:
    """Test token replacement in layout files."""

    def test_token_replacement(self, tmp_path):
        layout_file = tmp_path / "layout.json"
        layout_file.write_text('{"tenant": {"name": "{{COMPANY}}", "slug": "test"}}')
        result = load_layout(str(layout_file), {"COMPANY": "ACME"})
        assert result["tenant"]["name"] == "ACME"

    def test_unresolved_token_kept(self, tmp_path):
        layout_file = tmp_path / "layout.json"
        layout_file.write_text('{"tenant": {"name": "{{UNKNOWN}}", "slug": "test"}}')
        result = load_layout(str(layout_file))
        assert result["tenant"]["name"] == "{{UNKNOWN}}"

    def test_env_token_substitution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TS_MY_VAR", "from_env")
        layout_file = tmp_path / "layout.json"
        layout_file.write_text('{"tenant": {"name": "{{MY_VAR}}", "slug": "test"}}')
        result = load_layout(str(layout_file))
        assert result["tenant"]["name"] == "from_env"
