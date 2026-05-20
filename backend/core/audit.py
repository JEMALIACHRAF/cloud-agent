"""Append-only JSONL audit logger with automatic rotation."""
from __future__ import annotations
import json
import os
import threading
import datetime
from pathlib import Path

from core.config import settings

MAX_BYTES    = 50 * 1024 * 1024
BACKUP_COUNT = 5


class AuditLogger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._path       = Path(settings.audit_log_path)
            cls._instance._write_lock = threading.Lock()
            cls._instance._file       = open(settings.audit_log_path, "a", encoding="utf-8")
        return cls._instance

    def _rotate(self):
        try:
            if self._path.exists() and os.path.getsize(self._path) > MAX_BYTES:
                self._file.close()
                for i in range(BACKUP_COUNT - 1, 0, -1):
                    src = Path(f"{self._path}.{i}")
                    dst = Path(f"{self._path}.{i + 1}")
                    if src.exists():
                        src.rename(dst)
                if self._path.exists():
                    self._path.rename(Path(f"{self._path}.1"))
                self._file = open(self._path, "a", encoding="utf-8")
        except Exception:
            pass

    def log(self, event: str, **kwargs):
        entry = {"ts": datetime.datetime.utcnow().isoformat() + "Z", "event": event, **kwargs}
        line = json.dumps(entry, default=str)
        with self._write_lock:
            self._file.write(line + "\n")
            self._file.flush()
            self._rotate()

    def read(self, limit: int = 300, run_id: str | None = None) -> list[dict]:
        if not self._path.exists():
            return []
        entries = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        if run_id and e.get("run_id") != run_id:
                            continue
                        entries.append(e)
                    except Exception:
                        continue
        except Exception:
            pass
        return entries[-limit:]
