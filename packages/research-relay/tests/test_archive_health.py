from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from research_relay.config import load_config
from research_relay.health import run_health
from research_relay.ledger import Ledger
from tests.test_config import MINIMAL


def _cfg(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        MINIMAL.replace('ledger = "/tmp/relay.sqlite"', f'ledger = "{tmp_path / "ledger.sqlite"}"'),
        encoding="utf-8",
    )
    cfg = load_config(path)
    return replace(
        cfg,
        archive=replace(
            cfg.archive,
            enabled=True,
            pdf_folder_id="pdfid",
            docs_folder_id="docsid",
        ),
    )


def test_health_archive_disabled_when_omitted(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    cfg = load_config(path)
    report = run_health(cfg, connect_network=False, gmail_password="x", proton_password="y", hmac_key="z")
    names = {item.name: item for item in report.checks}
    assert names["archive"].ok is True
    assert names["archive"].detail == "disabled"


def test_health_fresh_incomplete_is_ok(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    ledger.enqueue_archive("proton:<a>", message_id="<a>", kind="html", expected_names=[])
    ledger.close()
    report = run_health(cfg, connect_network=False, gmail_password="x", proton_password="y", hmac_key="z")
    names = {item.name: item for item in report.checks}
    assert names["archive.stale"].ok is True
    assert names["archive.unrecoverable"].ok is True


def test_health_stale_incomplete_fails(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    ledger.enqueue_archive("proton:<old>", message_id="<old>", kind="html", expected_names=[])
    old = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc).isoformat()
    ledger._conn.execute(
        "UPDATE archives SET enqueued_at = ?, updated_at = ? WHERE gmail_msgid = ?",
        (old, old, "proton:<old>"),
    )
    ledger._conn.commit()
    ledger.close()
    report = run_health(cfg, connect_network=False, gmail_password="x", proton_password="y", hmac_key="z")
    names = {item.name: item for item in report.checks}
    assert names["archive.stale"].ok is False


def test_health_unrecoverable_fails(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    ledger.enqueue_archive("proton:<x>", message_id="<x>", kind="html", expected_names=[])
    for _ in range(5):
        ledger.record_find_miss("proton:<x>", threshold=5)
    ledger.close()
    report = run_health(cfg, connect_network=False, gmail_password="x", proton_password="y", hmac_key="z")
    names = {item.name: item for item in report.checks}
    assert names["archive.unrecoverable"].ok is False
