"""Tests für das Laden der InfluxDB-Konfiguration."""

import os

from blackjack.db_config import InfluxConfig, load_influx_config


def _make(**overrides) -> InfluxConfig:
    defaults = dict(
        url="https://x", org="a", bucket="b",
        bucket_id="c", token_read="t1", token_write="t2",
    )
    defaults.update(overrides)
    return InfluxConfig(**defaults)


def test_is_configured_true_for_real_values():
    assert _make().is_configured


def test_is_configured_false_for_placeholders():
    assert not _make(token_read="<HIER LESE-TOKEN EINTRAGEN>").is_configured
    assert not _make(token_write="YOUR_TOKEN").is_configured


def test_is_configured_false_for_empty_values():
    assert not _make(url="").is_configured
    assert not _make(token_read="", token_write="").is_configured


def test_load_influx_config_reads_env():
    saved = {}
    keys = (
        "INFLUX_URL", "INFLUX_ORG", "INFLUX_ORG_ID", "INFLUX_BUCKET",
        "INFLUX_BUCKET_ID", "INFLUX_TOKEN", "INFLUX_TOKEN_READ",
        "INFLUX_TOKEN_WRITE", "INFLUX_QUERY_RANGE",
    )
    for k in keys:
        saved[k] = os.environ.get(k)
        os.environ.pop(k, None)
    try:
        os.environ["INFLUX_URL"] = "http://10.0.244.254:8086"
        os.environ["INFLUX_ORG"] = "FIT244"
        os.environ["INFLUX_BUCKET"] = "PPMaster"
        os.environ["INFLUX_BUCKET_ID"] = "0a38c021dbad8b0c"
        os.environ["INFLUX_TOKEN_READ"] = "readtoken"
        os.environ["INFLUX_TOKEN_WRITE"] = "writetoken"
        os.environ["INFLUX_QUERY_RANGE"] = "-2h"
        cfg = load_influx_config()
        assert cfg.url == "http://10.0.244.254:8086"
        assert cfg.org == "FIT244"
        assert cfg.bucket == "PPMaster"
        assert cfg.bucket_id == "0a38c021dbad8b0c"
        assert cfg.token_read == "readtoken"
        assert cfg.token_write == "writetoken"
        assert cfg.query_range == "-2h"
        assert cfg.is_configured
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_generic_token_falls_back_to_both_roles():
    saved = {k: os.environ.get(k) for k in (
        "INFLUX_TOKEN", "INFLUX_TOKEN_READ", "INFLUX_TOKEN_WRITE",
    )}
    try:
        for k in saved:
            os.environ.pop(k, None)
        os.environ["INFLUX_URL"] = "u"
        os.environ["INFLUX_ORG"] = "o"
        os.environ["INFLUX_BUCKET"] = "b"
        os.environ["INFLUX_TOKEN"] = "generic"
        cfg = load_influx_config()
        assert cfg.token_read == "generic"
        assert cfg.token_write == "generic"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
