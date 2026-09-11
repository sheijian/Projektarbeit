"""Kleiner Flask-Mock-Server für die Blackjack-Guthaben-API.

Persistiert Spielerdaten in einer SQLite-Datei und stellt die zwei Endpunkte
bereit, die der `BalanceAPI`-Client erwartet:

    GET  /players/<uid>
    POST /players/<uid>/balance   {"delta": int}

Beim ersten Start werden ein paar Test-Spieler angelegt, deren UIDs zu den
Mock-Chips in `blackjack.config.MOCK_RFID_KEYS` passen.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from flask import Flask, abort, jsonify, request

from blackjack.config import MOCK_RFID_KEYS


DB_PATH = Path(os.environ.get("BLACKJACK_DB", "blackjack.db"))


# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    con = get_db()
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            rfid    TEXT PRIMARY KEY,
            name    TEXT NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            rfid      TEXT NOT NULL REFERENCES players(rfid),
            delta     INTEGER NOT NULL,
            balance   INTEGER NOT NULL,
            ts        DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.commit()

    # Demo-Spieler
    demo = [
        (MOCK_RFID_KEYS["1"], "Alice",   500),
        (MOCK_RFID_KEYS["2"], "Bob",     250),
        (MOCK_RFID_KEYS["3"], "Charlie", 1000),
    ]
    for rfid, name, balance in demo:
        con.execute(
            "INSERT OR IGNORE INTO players (rfid, name, balance) "
            "VALUES (?, ?, ?)",
            (rfid, name, balance),
        )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
def create_app() -> Flask:
    app = Flask(__name__)
    init_db()

    @app.get("/players/<uid>")
    def get_player(uid: str):
        con = get_db()
        row = con.execute(
            "SELECT rfid, name, balance FROM players WHERE rfid = ?", (uid,),
        ).fetchone()
        con.close()
        if row is None:
            abort(404)
        return jsonify(dict(row))

    @app.post("/players/<uid>/balance")
    def apply_delta(uid: str):
        payload = request.get_json(silent=True) or {}
        try:
            delta = int(payload["delta"])
        except (KeyError, TypeError, ValueError):
            return jsonify(error="delta erforderlich (int)"), 400

        con = get_db()
        row = con.execute(
            "SELECT balance FROM players WHERE rfid = ?", (uid,),
        ).fetchone()
        if row is None:
            con.close()
            abort(404)

        new_balance = row["balance"] + delta
        if new_balance < 0:
            con.close()
            return jsonify(error="Guthaben würde negativ"), 409

        con.execute(
            "UPDATE players SET balance = ? WHERE rfid = ?",
            (new_balance, uid),
        )
        con.execute(
            "INSERT INTO transactions (rfid, delta, balance) VALUES (?, ?, ?)",
            (uid, delta, new_balance),
        )
        con.commit()
        con.close()
        return jsonify(balance=new_balance)

    @app.get("/players")
    def list_players():
        con = get_db()
        rows = con.execute(
            "SELECT rfid, name, balance FROM players ORDER BY name",
        ).fetchall()
        con.close()
        return jsonify([dict(r) for r in rows])

    return app


# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    args = p.parse_args()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
