
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database.db as db
from ingestion.event_ingestion import ingest_event_file, resolve_pending_events
from ingestion.lead_ingestion import (
    normalize_phone,
    normalize_date,
    normalize_decimal,
)
from reporting.reports import generate_reports


def test_valid_phone():
    assert normalize_phone("9876543210") == "+919876543210"


def test_phone_with_country_code():
    assert normalize_phone("919876543210") == "+919876543210"


def test_invalid_phone():
    with pytest.raises(ValueError):
        normalize_phone("12345")


def test_valid_date():
    assert normalize_date("2026-11-13") == "2026-11-13"


def test_invalid_date():
    with pytest.raises(ValueError):
        normalize_date("invalid-date")


def test_valid_decimal():
    assert normalize_decimal("1,500") == "1500.00"


def test_invalid_decimal():
    with pytest.raises(ValueError):
        normalize_decimal("abc")


def test_invalid_thousands_grouping():
    with pytest.raises(ValueError, match="invalid_decimal"):
        normalize_decimal("12,34")


def test_day_first_date_with_case_insensitive_month():
    assert normalize_date("01-dEc-2026") == "2026-12-01"


def _use_temporary_database(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "pipeline.db")
    monkeypatch.setattr(db, "KEY_PATH", tmp_path / ".secret.key")
    db.initialize_database()


def test_event_ingestion_accepts_code_header_and_deduplicates_unknown(
    monkeypatch, tmp_path
):
    _use_temporary_database(monkeypatch, tmp_path)
    db.upsert_lead({
        "workflow_id": "motor_renewal",
        "phone": "+919876543210",
        "customer_name": "Test Customer",
        "policy_number": "P-1",
        "batch_id": "batch_001",
    })

    dispositions = tmp_path / "dispositions.csv"
    dispositions.write_text(
        "workflow_id,code,label,is_terminal,is_success\n"
        "motor_renewal,renewed,Renewed,true,true\n",
        encoding="utf-8",
    )
    event = {
        "event_id": "evt-unknown",
        "event_type": "disposition.set",
        "workflow_id": "motor_renewal",
        "call_id": "call-1",
        "occurred_at": "2026-11-13T10:00:00Z",
        "phone": "9876543210",
        "payload": {"disposition_code": "not_in_catalogue"},
    }
    event_file = tmp_path / "events.jsonl"
    event_file.write_text(
        json.dumps(event) + "\n" + json.dumps(event) + "\n",
        encoding="utf-8",
    )

    stats = ingest_event_file(event_file, dispositions)

    assert stats["events_total"] == 2
    assert stats["duplicate_events_dropped"] == 1
    assert stats["unknown_disposition_events"] == 1
    with db.get_connection() as conn:
        stored = conn.execute(
            "SELECT linked, ignored FROM events WHERE event_id = ?",
            ("evt-unknown",),
        ).fetchone()
    assert tuple(stored) == (1, 1)


def test_override_is_effective_and_makes_terminal_bucket(monkeypatch, tmp_path):
    _use_temporary_database(monkeypatch, tmp_path)
    db.upsert_lead({
        "workflow_id": "motor_renewal",
        "phone": "+919876543210",
        "customer_name": "Test Customer",
        "policy_number": "P-1",
        "batch_id": "batch_001",
    })
    phone_token = db.phone_hash("+919876543210")

    with db.get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO events(
                event_id, workflow_id, call_id, event_type, occurred_at,
                phone_hash, payload, lead_id, linked, ignored
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, 0)
            """,
            [
                (
                    "evt-init",
                    "motor_renewal",
                    "call-1",
                    "call.initiated",
                    "2026-11-13T10:00:00Z",
                    phone_token,
                    "{}",
                ),
                (
                    "evt-set",
                    "motor_renewal",
                    "call-1",
                    "disposition.set",
                    "2026-11-13T10:05:00Z",
                    phone_token,
                    '{"disposition_code":"callback_requested"}',
                ),
                (
                    "evt-override",
                    "motor_renewal",
                    "call-1",
                    "disposition.override",
                    "2026-11-13T10:06:00Z",
                    None,
                    '{"disposition_code":"renewed"}',
                ),
            ],
        )
        resolve_pending_events(conn)

    dispositions = tmp_path / "dispositions.csv"
    dispositions.write_text(
        "workflow_id,code,label,is_terminal,is_success\n"
        "motor_renewal,callback_requested,Callback,false,false\n"
        "motor_renewal,renewed,Renewed,true,true\n",
        encoding="utf-8",
    )
    generate_reports(tmp_path / "reports", dispositions)

    with open(tmp_path / "reports" / "lead_report.csv", newline="", encoding="utf-8") as file:
        lead = next(csv.DictReader(file))
    assert lead["bucket"] == "completed"
    assert lead["current_disposition"] == "renewed"
    assert lead["ever_success"] == "true"
