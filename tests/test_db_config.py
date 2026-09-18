"""Tests für das Laden der InfluxDB-Konfiguration."""

import os

from blackjack.db_config import InfluxConfig, load_influx_config


def test_is_configured_true_for_real_values():
    cfg = InfluxConfig(
        url="https://x", org_id="a", bucket="b",
        bucket_id="c", token="t",
    )
    assert cfg.is_configured


def test_is_configured_false_for_placeholders():
    cfg = InfluxConfig(
        url="https://x", org_id="YOUR_ORG_ID", bucket="b",
        bucket_id="YOUR_BUCKET_ID", token="YOUR_TOKEN",
    )
    assert not cfg.is_configured


def test_is_configured_false_for_empty_values():
    cfg = InfluxConfig(url="", org_id="", bucket="", bucket_id="", token="")
    assert not cfg.is_configured


def test_load_influx_config_reads_env(monkeypatch=None):
    old = {k: os.environ.get(k) for k in (
        "INFLUX_URL", "INFLUX_ORG_ID", "INFLUX_BUCKET",
        "INFLUX_BUCKET_ID", "INFLUX_TOKEN",
    )}
    try:
        os.environ["INFLUX_URL"] = "https://example"
        os.environ["INFLUX_ORG_ID"] = "orgX"
        os.environ["INFLUX_BUCKET"] = "bk"
        os.environ["INFLUX_BUCKET_ID"] = "bkid"
        os.environ["INFLUX_TOKEN"] = "tok"
        cfg = load_influx_config()
        assert cfg.url == "https://example"
        assert cfg.org_id == "orgX"
        assert cfg.bucket == "bk"
        assert cfg.bucket_id == "bkid"
        assert cfg.token == "tok"
        assert cfg.is_configured
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
