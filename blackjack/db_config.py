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
    org: str
    bucket: str
    bucket_id: str
    token_read: str
    token_write: str
    query_range: str = "-1h"

    @property
    def is_configured(self) -> bool:
        # URL/Org/Bucket + mindestens ein Token müssen sinnvoll gesetzt sein.
        for v in (self.url, self.org, self.bucket, self.token_read, self.token_write):
            if not v or v.startswith(("<", "YOUR_")):
                return False
        return True


def load_influx_config() -> InfluxConfig:
    # Ein einziger Token (INFLUX_TOKEN) wird als Fallback für beide
    # Rollen benutzt, falls jemand nur einen gesetzt hat.
    generic_token = os.environ.get("INFLUX_TOKEN", "")
    return InfluxConfig(
        url=os.environ.get("INFLUX_URL", ""),
        # ORG akzeptiert Name oder ID; INFLUX_ORG_ID bleibt als Fallback.
        org=os.environ.get("INFLUX_ORG") or os.environ.get("INFLUX_ORG_ID", ""),
        bucket=os.environ.get("INFLUX_BUCKET", ""),
        bucket_id=os.environ.get("INFLUX_BUCKET_ID", ""),
        token_read=os.environ.get("INFLUX_TOKEN_READ") or generic_token,
        token_write=os.environ.get("INFLUX_TOKEN_WRITE") or generic_token,
        query_range=os.environ.get("INFLUX_QUERY_RANGE", "-1h"),
    )


INFLUX = load_influx_config()
