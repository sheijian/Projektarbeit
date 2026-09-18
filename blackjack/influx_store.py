"""PlayerStore-Implementierung für InfluxDB 2.x / InfluxDB Cloud.

Datenmodell:

    measurement: "wallet"
      tags:   rfid, name
      fields: balance (int)

Der aktuelle Kontostand eines Spielers ist der Wert des letzten Datenpunkts
mit passendem `rfid`-Tag. Bei jeder Guthaben-Änderung wird ein neuer
Datenpunkt mit dem neuen Kontostand geschrieben - so entsteht nebenbei ein
komplettes Buchungsjournal, das über die InfluxDB-UI abfragbar ist.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .db_config import INFLUX, InfluxConfig, load_influx_config
from .game import Player
from .store import PlayerNotFound, StoreError

log = logging.getLogger(__name__)


try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision  # type: ignore
    from influxdb_client.client.write_api import SYNCHRONOUS            # type: ignore
    HAS_INFLUX = True
except Exception:
    InfluxDBClient = None    # type: ignore
    Point = None             # type: ignore
    WritePrecision = None    # type: ignore
    SYNCHRONOUS = None       # type: ignore
    HAS_INFLUX = False


# ---------------------------------------------------------------------------
class InfluxPlayerStore:
    """Guthaben-Store gegen InfluxDB."""

    MEASUREMENT = "wallet"

    def __init__(self, config: Optional[InfluxConfig] = None) -> None:
        if not HAS_INFLUX:
            raise StoreError(
                "influxdb-client ist nicht installiert. "
                "pip install influxdb-client"
            )
        self.config = config or load_influx_config()
        if not self.config.is_configured:
            raise StoreError(
                "InfluxDB nicht konfiguriert - INFLUX_URL/ORG_ID/BUCKET/"
                "BUCKET_ID/TOKEN in .env eintragen (siehe .env.example)."
            )
        self._client = InfluxDBClient(
            url=self.config.url,
            token=self.config.token,
            org=self.config.org_id,
            timeout=5000,
        )
        self._write = self._client.write_api(write_options=SYNCHRONOUS)
        self._query = self._client.query_api()
        log.info(
            "InfluxPlayerStore verbunden mit %s (Bucket %s)",
            self.config.url, self.config.bucket,
        )

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------
    def get_player(self, rfid_uid: str) -> Player:
        # Sanitize gegen Flux-Injection: nur Alphanumerik/Unterstrich zulassen.
        if not _safe_id(rfid_uid):
            raise PlayerNotFound(rfid_uid)
        flux = f'''
from(bucket: "{self.config.bucket}")
  |> range(start: -365d)
  |> filter(fn: (r) => r._measurement == "{self.MEASUREMENT}")
  |> filter(fn: (r) => r.rfid == "{rfid_uid}")
  |> filter(fn: (r) => r._field == "balance")
  |> last()
'''
        try:
            tables = self._query.query(flux, org=self.config.org_id)
        except Exception as e:
            raise StoreError(f"InfluxDB-Query fehlgeschlagen: {e}") from e

        for table in tables:
            for record in table.records:
                return Player(
                    rfid=str(record.values.get("rfid", rfid_uid)),
                    name=str(record.values.get("name", "?")),
                    balance=int(record.get_value()),
                )
        raise PlayerNotFound(rfid_uid)

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------
    def apply_delta(self, rfid_uid: str, delta: int) -> Optional[int]:
        try:
            player = self.get_player(rfid_uid)
        except PlayerNotFound:
            log.warning("apply_delta: Spieler %s nicht gefunden", rfid_uid)
            return None
        except StoreError as e:
            log.warning("apply_delta: %s", e)
            return None

        new_balance = player.balance + delta
        if new_balance < 0:
            log.warning("apply_delta: Guthaben würde negativ (%d)", new_balance)
            return None

        self._write_balance(rfid_uid, player.name, new_balance)
        return new_balance

    # ------------------------------------------------------------------
    # Spieler anlegen / initial seeden
    # ------------------------------------------------------------------
    def seed_player(self, rfid_uid: str, name: str, balance: int) -> None:
        """Legt einen Spieler an bzw. setzt sein Guthaben auf `balance`."""
        self._write_balance(rfid_uid, name, balance)
        log.info("Seed: %s (%s) = %d", name, rfid_uid, balance)

    # ------------------------------------------------------------------
    def _write_balance(self, rfid_uid: str, name: str, balance: int) -> None:
        point = (
            Point(self.MEASUREMENT)
            .tag("rfid", rfid_uid)
            .tag("name", name)
            .field("balance", int(balance))
            .time(datetime.now(timezone.utc), WritePrecision.NS)
        )
        try:
            self._write.write(
                bucket=self.config.bucket,
                org=self.config.org_id,
                record=point,
            )
        except Exception as e:
            raise StoreError(f"InfluxDB-Write fehlgeschlagen: {e}") from e

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._write.close()
        finally:
            self._client.close()


# ---------------------------------------------------------------------------
def _safe_id(value: str) -> bool:
    """Nur alphanumerische UIDs erlauben (RFID-Hex-Werte)."""
    return bool(value) and all(c.isalnum() or c in "-_." for c in value)
