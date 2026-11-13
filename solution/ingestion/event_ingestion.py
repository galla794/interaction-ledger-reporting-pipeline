
import json
import csv

from database.db import (
    get_connection,
    initialize_database,
    phone_hash
)
from ingestion.lead_ingestion import normalize_phone


def load_dispositions(path):
    """Load valid disposition codes for each workflow."""

    allowed = {}

    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            workflow = row.get("workflow_id")
            code = (row.get("code") or row.get("disposition_code") or "").strip()

            if workflow and code:
                allowed.setdefault(workflow, set()).add(code.lower())

    return allowed


def relink_events():
    """Link previously orphaned events when their leads arrive."""

    initialize_database()

    with get_connection() as conn:

        # Link events using workflow and phone hash.
        conn.execute("""
            UPDATE events
            SET lead_id = (
                SELECT leads.id
                FROM leads
                WHERE leads.workflow_id = events.workflow_id
                  AND leads.phone_hash = events.phone_hash
            ),
            linked = 1
            WHERE phone_hash IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM leads
                WHERE leads.workflow_id = events.workflow_id
                  AND leads.phone_hash = events.phone_hash
              )
        """)

        # Overrides have no phone; link through the call's other events.
        conn.execute("""
            UPDATE events
            SET lead_id = (
                SELECT e2.lead_id
                FROM events e2
                WHERE e2.workflow_id = events.workflow_id
                  AND e2.call_id = events.call_id
                  AND e2.event_type != 'disposition.override'
                  AND e2.lead_id IS NOT NULL
                LIMIT 1
            ),
            linked = 1
            WHERE event_type = 'disposition.override'
              AND EXISTS (
                SELECT 1 FROM events e2
                WHERE e2.workflow_id = events.workflow_id
                  AND e2.call_id = events.call_id
                  AND e2.event_type != 'disposition.override'
                  AND e2.lead_id IS NOT NULL
              )
        """)


def ingest_event_file(event_path, dispositions_path):

    initialize_database()

    allowed = load_dispositions(dispositions_path)

    stats = {
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "unknown_disposition_events": 0
    }
    unknown_event_ids = []

    with get_connection() as conn, open(event_path, "r", encoding="utf-8") as file:
        for line in file:

            if not line.strip():
                continue

            stats["events_total"] += 1

            try:
                event = json.loads(line)

                if not isinstance(event, dict) or not event.get("event_id"):
                    raise ValueError("Missing event_id")

            except (json.JSONDecodeError, ValueError):
                stats["malformed_events"] += 1
                continue

            event_id = str(event["event_id"])

            # Duplicate detection across all previously ingested drops.
            existing = conn.execute("""
                SELECT event_id FROM events
                WHERE event_id = ?
            """, (event_id,)).fetchone()

            if existing:
                stats["duplicate_events_dropped"] += 1
                continue

            event_type = str(event.get("event_type") or "")
            workflow_id = str(event.get("workflow_id") or "")
            call_id = event.get("call_id")
            occurred_at = event.get("occurred_at")
            call_id = str(call_id) if call_id is not None else None
            occurred_at = str(occurred_at) if occurred_at is not None else None

            phone_token = None

            phone = event.get("phone")

            if phone is not None and str(phone):
                try:
                    normalized_phone = normalize_phone(str(phone))
                    phone_token = phone_hash(normalized_phone)
                except ValueError:
                    phone_token = None

            payload_value = event.get("payload", {})
            if not isinstance(payload_value, dict):
                payload_value = {}

            ignored = False
            if event_type.startswith("disposition."):
                code = str(
                    payload_value.get("disposition_code", "")
                ).strip().lower()
                ignored = code not in allowed.get(workflow_id, set())

            payload = json.dumps(
                payload_value,
                ensure_ascii=False
            )

            conn.execute("""
                INSERT INTO events (
                    event_id,
                    workflow_id,
                    call_id,
                    event_type,
                    occurred_at,
                    phone_hash,
                    payload,
                    lead_id,
                    linked,
                    ignored
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)
            """, (
                event_id,
                workflow_id,
                call_id,
                event_type,
                occurred_at,
                phone_token,
                payload,
                int(ignored)
            ))

            if ignored:
                unknown_event_ids.append(event_id)

    # Link events that have corresponding leads.
    relink_events()

    if unknown_event_ids:
        with get_connection() as conn:
            for start in range(0, len(unknown_event_ids), 900):
                event_ids = unknown_event_ids[start:start + 900]
                placeholders = ",".join("?" for _ in event_ids)
                stats["unknown_disposition_events"] += conn.execute(
                    f"""
                    SELECT COUNT(*) FROM events
                    WHERE event_id IN ({placeholders}) AND linked = 1
                    """,
                    event_ids
                ).fetchone()[0]

    return stats

def resolve_pending_events(conn):
    """Link previously orphaned events when their leads arrive."""

    conn.execute("""
        UPDATE events
        SET lead_id = (
            SELECT l.id
            FROM leads l
            WHERE l.workflow_id = events.workflow_id
              AND l.phone_hash = events.phone_hash
        ),
        linked = 1
        WHERE linked = 0
          AND phone_hash IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM leads l
              WHERE l.workflow_id = events.workflow_id
                AND l.phone_hash = events.phone_hash
          )
    """)

    conn.execute("""
        UPDATE events
        SET lead_id = (
            SELECT e.lead_id
            FROM events e
            WHERE e.workflow_id = events.workflow_id
              AND e.call_id = events.call_id
              AND e.event_id != events.event_id
              AND e.lead_id IS NOT NULL
            LIMIT 1
        ),
        linked = 1
        WHERE linked = 0
          AND event_type = 'disposition.override'
          AND EXISTS (
              SELECT 1
              FROM events e
              WHERE e.workflow_id = events.workflow_id
                AND e.call_id = events.call_id
                AND e.event_id != events.event_id
                AND e.lead_id IS NOT NULL
          )
    """)
