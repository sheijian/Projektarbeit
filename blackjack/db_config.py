"""Zugangsdaten für die InfluxDB-Guthaben-Datenbank.

Die Werte werden aus Umgebungsvariablen gelesen. Wenn eine `.env`-Datei
im Projekt-Root existiert, wird sie beim Import automatisch geladen -
so kann man die Zugangsdaten lokal in `.env` pflegen, ohne dass sie im
Git landen (.env steht in .gitignore).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# .env laden - falls python-dotenv verfügbar ist, sonst simpler Fallback.
# ---------------------------------------------------------------------------
def _load_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        return
    except Exception:
        pass
    # Fallback ohne python-dotenv: KEY=VALUE zeilenweise einlesen.
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_ROOT = Path(__file__).resolve().parent.parent
_load_env(_ROOT / ".env")


# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InfluxConfig:
    url: str
    org_id: str
    bucket: str
    bucket_id: str
    token: str

    @property
    def is_configured(self) -> bool:
        # Alle Werte müssen gesetzt und nicht Platzhalter sein.
        for v in (self.url, self.org_id, self.bucket, self.bucket_id, self.token):
            if not v or v.startswith("YOUR_"):
                return False
        return True


def load_influx_config() -> InfluxConfig:
    return InfluxConfig(
        url=os.environ.get("INFLUX_URL", ""),
        org_id=os.environ.get("INFLUX_ORG_ID", ""),
        bucket=os.environ.get("INFLUX_BUCKET", ""),
        bucket_id=os.environ.get("INFLUX_BUCKET_ID", ""),
        token=os.environ.get("INFLUX_TOKEN", ""),
    )


INFLUX = load_influx_config()
