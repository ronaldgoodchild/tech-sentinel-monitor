"""
Tech Sentinel Monitor — Version Control / Config Backup
========================================================
Keeps timestamped copies of configuration and database snapshots
so you can roll back to any previous version.

Created by Ronald Goodchild / REGTeches
"""

import json
import logging
import os
import shutil
from datetime import datetime, timezone

logger = logging.getLogger("ts.version_control")

APP_VERSION = "2.0.0"
VERSION_HISTORY_FILE = "version_history.json"


class VersionManager:
    """Manages versioned backups of configs and database."""

    def __init__(self, app_data_dir: str = ""):
        if not app_data_dir:
            app_data_dir = os.path.join(
                os.environ.get("LOCALAPPDATA", "."), "TechSentinelMonitor"
            )
        self.app_data_dir = app_data_dir
        self.backup_dir = os.path.join(app_data_dir, "backups")
        self.history_path = os.path.join(app_data_dir, VERSION_HISTORY_FILE)
        os.makedirs(self.backup_dir, exist_ok=True)

    def get_current_version(self) -> str:
        return APP_VERSION

    def create_backup(self, label: str = "", auto: bool = False) -> dict:
        """
        Create a timestamped backup of all configs and the database.

        Returns a backup record dict.
        """
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d_%H%M%S")
        tag = label.replace(" ", "_")[:30] if label else ("auto" if auto else "manual")
        backup_name = f"backup_{ts}_{tag}"
        backup_path = os.path.join(self.backup_dir, backup_name)
        os.makedirs(backup_path, exist_ok=True)

        files_backed_up = []

        # Files to back up
        targets = [
            "techsentinel.db",
            "alert_config.json",
            "branding_config.json",
        ]

        for fname in targets:
            src = os.path.join(self.app_data_dir, fname)
            if os.path.exists(src):
                dst = os.path.join(backup_path, fname)
                try:
                    shutil.copy2(src, dst)
                    size = os.path.getsize(src)
                    files_backed_up.append({
                        "file": fname,
                        "size_bytes": size,
                    })
                except Exception as e:
                    logger.warning("Failed to backup %s: %s", fname, e)

        # Calculate total size
        total_size = sum(f["size_bytes"] for f in files_backed_up)

        record = {
            "id": backup_name,
            "timestamp": now.isoformat(),
            "label": label or tag,
            "auto": auto,
            "app_version": APP_VERSION,
            "path": backup_path,
            "files": files_backed_up,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

        # Append to history
        self._append_history(record)
        logger.info(
            "Backup created: %s (%d files, %.2f MB)",
            backup_name, len(files_backed_up), record["total_size_mb"],
        )
        return record

    def restore_backup(self, backup_id: str) -> bool:
        """
        Restore configs and database from a backup.

        WARNING: This overwrites current files.
        """
        backup_path = os.path.join(self.backup_dir, backup_id)
        if not os.path.isdir(backup_path):
            logger.error("Backup not found: %s", backup_id)
            return False

        # First, create a safety backup of current state
        self.create_backup(label="pre-restore-safety", auto=True)

        restored = []
        for fname in os.listdir(backup_path):
            src = os.path.join(backup_path, fname)
            dst = os.path.join(self.app_data_dir, fname)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, dst)
                    restored.append(fname)
                except Exception as e:
                    logger.error("Failed to restore %s: %s", fname, e)

        logger.info("Restored %d files from backup %s", len(restored), backup_id)
        return True

    def list_backups(self) -> list[dict]:
        """Get all backup records, newest first."""
        history = self._load_history()
        # Verify backup dirs still exist
        valid = []
        for rec in history:
            if os.path.isdir(rec.get("path", "")):
                valid.append(rec)
        return list(reversed(valid))

    def delete_backup(self, backup_id: str) -> bool:
        """Delete a specific backup."""
        backup_path = os.path.join(self.backup_dir, backup_id)
        if os.path.isdir(backup_path):
            try:
                shutil.rmtree(backup_path)
                # Remove from history
                history = self._load_history()
                history = [r for r in history if r.get("id") != backup_id]
                self._save_history(history)
                logger.info("Deleted backup: %s", backup_id)
                return True
            except Exception as e:
                logger.error("Failed to delete backup %s: %s", backup_id, e)
        return False

    def cleanup_old_backups(self, keep: int = 20):
        """Keep only the N most recent backups, delete the rest."""
        backups = self.list_backups()
        if len(backups) <= keep:
            return
        to_delete = backups[keep:]
        for rec in to_delete:
            self.delete_backup(rec["id"])
        logger.info("Cleaned up %d old backups (kept %d)", len(to_delete), keep)

    def export_backup(self, backup_id: str, dest_path: str) -> str | None:
        """Export a backup as a zip file to a destination path."""
        backup_path = os.path.join(self.backup_dir, backup_id)
        if not os.path.isdir(backup_path):
            return None
        try:
            zip_path = shutil.make_archive(
                os.path.join(dest_path, backup_id), "zip", backup_path
            )
            logger.info("Exported backup to: %s", zip_path)
            return zip_path
        except Exception as e:
            logger.error("Failed to export backup: %s", e)
            return None

    def _load_history(self) -> list[dict]:
        if not os.path.exists(self.history_path):
            return []
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_history(self, history: list[dict]):
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    def _append_history(self, record: dict):
        history = self._load_history()
        history.append(record)
        self._save_history(history)
