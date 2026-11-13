
import csv
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from database.db import get_connection


IST = timezone(timedelta(hours=5, minutes=30))


def parse_ist(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)

        return dt.astimezone(IST)
    except ValueError:
        return None


def load_dispositions(path):
    catalogue = {}

    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            workflow = row.get("workflow_id")
            code = (row.get("code") or row.get("disposition_code") or "").strip()

            if not workflow or not code:
                continue

            catalogue[(workflow, code.lower())] = {
                "terminal": str(row.get("is_terminal", "")).lower() == "true",
                "success": str(row.get("is_success", "")).lower() == "true"
            }

    return catalogue


def write_csv(path, headers, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def generate_reports(output_dir, dispositions_path,
                     rejections=None, quality=None):

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    catalogue = load_dispositions(dispositions_path)

    with get_connection() as conn:
        leads = [
            dict(row) for row in conn.execute(
                "SELECT * FROM leads"
            ).fetchall()
        ]

        events = [
            dict(row) for row in conn.execute(
                "SELECT * FROM events WHERE linked = 1 AND ignored = 0"
            ).fetchall()
        ]

    events_by_lead = {}
    for event in events:
        events_by_lead.setdefault(event["lead_id"], []).append(event)

    # Build call-level information.
    calls_by_lead = {}
    calls_by_date = {}

    for lead in leads:
        lead_id = lead["id"]
        lead_events = events_by_lead.get(lead_id, [])

        calls = {}

        for event in lead_events:
            if not event["call_id"]:
                continue

            calls.setdefault(event["call_id"], []).append(event)

        lead_calls = []

        for call_id, call_events in calls.items():
            initiated = [
                e for e in call_events
                if e["event_type"] == "call.initiated"
            ]

            if not initiated:
                continue

            initiated.sort(
                key=lambda e: parse_ist(e["occurred_at"]) or datetime.min.replace(tzinfo=IST)
            )

            start_event = initiated[0]
            start_time = parse_ist(start_event["occurred_at"])

            if not start_time:
                continue

            connected = any(
                e["event_type"] == "call.connected"
                for e in call_events
            )

            overrides = [
                e for e in call_events
                if e["event_type"] == "disposition.override"
            ]

            sets = [
                e for e in call_events
                if e["event_type"] == "disposition.set"
            ]

            candidates = overrides if overrides else sets

            candidates.sort(
                key=lambda e: parse_ist(e["occurred_at"]) or datetime.min.replace(tzinfo=IST)
            )

            disposition = None

            if candidates:
                payload = json.loads(candidates[-1]["payload"] or "{}")
                disposition = payload.get("disposition_code")

            call = {
                "call_id": call_id,
                "time": start_time,
                "date": start_time.date().isoformat(),
                "connected": connected,
                "disposition": disposition
            }

            lead_calls.append(call)

            date_key = (
                lead["workflow_id"],
                call["date"]
            )

            calls_by_date.setdefault(date_key, []).append(
                (lead_id, call)
            )

        calls_by_lead[lead_id] = lead_calls

    # 1. Batch summary.
    batch_groups = {}

    for lead in leads:
        key = (lead["workflow_id"], lead["batch_id"])
        batch_groups.setdefault(key, []).append(lead)

    batch_rows = []

    for (workflow, batch), group in sorted(batch_groups.items()):
        buckets = {
            "yet_to_reach_out": 0,
            "in_progress_telephony_failed": 0,
            "in_progress_dialed": 0,
            "completed": 0
        }

        for lead in group:
            calls = calls_by_lead.get(lead["id"], [])

            if not calls:
                bucket = "yet_to_reach_out"
            elif any(
                catalogue.get(
                    (workflow, (c["disposition"] or "").lower()),
                    {}
                ).get("terminal", False)
                for c in calls
            ):
                bucket = "completed"
            elif all(
                any(
                    e["event_type"] == "call.telephony_failed"
                    for e in events_by_lead.get(lead["id"], [])
                    if e["call_id"] == c["call_id"]
                )
                for c in calls
            ):
                bucket = "in_progress_telephony_failed"
            else:
                bucket = "in_progress_dialed"

            buckets[bucket] += 1

        batch_rows.append({
            "workflow_id": workflow,
            "batch_id": batch,
            "total_leads": len(group),
            **buckets
        })

    write_csv(
        output_dir / "batch_summary.csv",
        ["workflow_id", "batch_id", "total_leads",
         "yet_to_reach_out", "in_progress_telephony_failed",
         "in_progress_dialed", "completed"],
        batch_rows
    )

    # 2. Daily overview.
    daily_rows = []

    for (workflow, date), calls in sorted(calls_by_date.items()):
        connected = sum(1 for _, c in calls if c["connected"])

        successful_leads = set()

        for lead_id, call in calls:
            if catalogue.get(
                (workflow, (call["disposition"] or "").lower()),
                {}
            ).get("success", False):
                successful_leads.add(lead_id)

        daily_rows.append({
            "workflow_id": workflow,
            "date": date,
            "total_calls": len(calls),
            "connected_calls": connected,
            "connectivity_rate": f"{connected / len(calls):.4f}",
            "success_leads": len(successful_leads)
        })

    write_csv(
        output_dir / "daily_overview.csv",
        ["workflow_id", "date", "total_calls", "connected_calls",
         "connectivity_rate", "success_leads"],
        daily_rows
    )

    # 3. Lead report.
    lead_rows = []

    for lead in leads:
        workflow = lead["workflow_id"]
        calls = calls_by_lead.get(lead["id"], [])

        calls.sort(key=lambda c: c["time"])

        successful = any(
            catalogue.get(
                (workflow, (c["disposition"] or "").lower()),
                {}
            ).get("success", False)
            for c in calls
        )

        current_disposition = ""

        for call in reversed(calls):
            if call["disposition"]:
                current_disposition = call["disposition"]
                break

        last_call = calls[-1]["time"].isoformat() if calls else ""

        lead_rows.append({
            "workflow_id": workflow,
            "external_ref": lead["policy_number"],
            "batch_id": lead["batch_id"],
            "phone_masked": "+91******" + lead["phone_last4"],
            "bucket": (
                "yet_to_reach_out" if not calls else
                "completed" if any(
                    catalogue.get(
                        (workflow, (c["disposition"] or "").lower()),
                        {}
                    ).get("terminal", False)
                    for c in calls
                ) else
                "in_progress_telephony_failed" if all(
                    any(
                        e["event_type"] == "call.telephony_failed"
                        for e in events_by_lead.get(lead["id"], [])
                        if e["call_id"] == c["call_id"]
                    )
                    for c in calls
                ) else "in_progress_dialed"
            ),
            "total_calls": len(calls),
            "connected_calls": sum(1 for c in calls if c["connected"]),
            "last_call_at": last_call,
            "current_disposition": current_disposition,
            "ever_success": str(successful).lower()
        })

    lead_rows.sort(key=lambda r: (r["workflow_id"], r["external_ref"]))

    write_csv(
        output_dir / "lead_report.csv",
        ["workflow_id", "external_ref", "batch_id", "phone_masked",
         "bucket", "total_calls", "connected_calls", "last_call_at",
         "current_disposition", "ever_success"],
        lead_rows
    )

    # 4. Rejections.
    rejection_rows = sorted(
        rejections or [],
        key=lambda r: (
            r["workflow_id"], r["batch_id"], r["row_number"]
        )
    )

    write_csv(
        output_dir / "rejections.csv",
        ["workflow_id", "batch_id", "row_number", "reason"],
        rejection_rows
    )

    # 5. Data quality.
    default_quality = {
        "lead_rows_total": 0,
        "lead_rows_rejected": 0,
        "rejections_by_reason": {},
        "duplicate_lead_rows_merged": 0,
        "field_warnings": 0,
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "orphan_events": 0,
        "unknown_disposition_events": 0
    }

    if quality:
        default_quality.update(quality)

    with open(
        output_dir / "data_quality.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(default_quality, f, indent=2)

    print("All five reports generated successfully.")
