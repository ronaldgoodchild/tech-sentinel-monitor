"""
Tech Sentinel Monitor — Branding / White-Label Configuration
=============================================================
Allows private-labeling of the status pages while keeping
the original creator credits hardcoded.

Created by Ronald Goodchild / REGTeches — this line is permanent.
"""

import json
import os
import logging

logger = logging.getLogger("ts.branding")

# ── Hardcoded Creator Credit (never changes) ────────────────────────────────
CREATOR_CREDIT = "Created by Ronald Goodchild / REGTeches"
CREATOR_URL = "https://regteches.com"


class BrandingConfig:
    """White-label branding settings."""

    def __init__(self):
        self.app_name: str = "Tech Sentinel Monitor"
        self.company_name: str = ""
        self.accent_color: str = "#3b82f6"
        self.logo_url: str = ""       # URL to a logo image (optional)
        self.favicon_url: str = ""    # URL to a favicon (optional)
        self.custom_footer: str = ""  # Extra footer text (credit line always appended)

    def to_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "company_name": self.company_name,
            "accent_color": self.accent_color,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "custom_footer": self.custom_footer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BrandingConfig":
        cfg = cls()
        for key in cfg.to_dict():
            if key in data:
                setattr(cfg, key, data[key])
        return cfg

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "BrandingConfig":
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except Exception as e:
            logger.warning("Failed to load branding config: %s", e)
            return cls()

    def get_footer_html(self) -> str:
        """Build footer HTML — custom text + hardcoded creator credit."""
        parts = []
        if self.custom_footer:
            parts.append(self.custom_footer)
        parts.append(f'Powered by {self.app_name}')
        parts.append(f'<span style="opacity:0.7">{CREATOR_CREDIT}</span>')
        return " &mdash; ".join(parts)

    def get_header_html(self) -> str:
        """Build header with optional logo."""
        if self.logo_url:
            return (
                f'<img src="{self.logo_url}" alt="{self.app_name}" '
                f'style="height:40px;vertical-align:middle;margin-right:8px" '
                f'onerror="this.style.display=\'none\'"> '
                f'{self.app_name}'
            )
        return f'🛡️ {self.app_name}'


# ── Module-level singleton ──────────────────────────────────────────────────

_config: BrandingConfig | None = None
_config_path: str = ""


def init_branding_config(config_dir: str = "") -> BrandingConfig:
    """Initialize branding config from disk."""
    global _config, _config_path
    if not config_dir:
        config_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor"
        )
    os.makedirs(config_dir, exist_ok=True)
    _config_path = os.path.join(config_dir, "branding_config.json")
    _config = BrandingConfig.load(_config_path)
    logger.info("Branding config loaded: %s", _config.app_name)
    return _config


def get_branding_config() -> BrandingConfig:
    global _config
    if _config is None:
        _config = init_branding_config()
    return _config


def save_branding_config():
    global _config, _config_path
    if _config and _config_path:
        _config.save(_config_path)
        logger.info("Branding config saved")
