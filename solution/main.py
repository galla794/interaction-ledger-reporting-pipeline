import argparse
import hashlib
import sys
from pathlib import Path

# Make the solution folder available when invoked as a script.
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
sys.path.insert(0, str(BASE_DIR))

from database.db import get_connection, initialize_database, upsert_lead  # noqa: E402
from ingestion.event_ingestion import (  # noqa: E402
    ingest_event_file,
    resolve_pending_events,
)
from ingestion.lead_ingestion import ingest_lead_file  # noqa: E402
from reporting.reports import generate_reports  # noqa: E402


DATA_DIR = PROJECT_DIR / "data"
SCHEMA_DIR = PROJECT_DIR / "assignment-a-data" / "schemas"
OUTPUT_DIR = PROJECT_DIR / "reports"
WORKFLOWS = ("motor_renewal", "policy_feedback")

METRIC_DEFAULTS = {
    "lead_rows_total": 0,
    "lead_rows_rejected": 0,
    "duplicate_lead_rows_merged": 0,
    "field_warnings": 0,
    "events_total": 0,
    "malformed_events": 0,
    "duplicate_events_dropped": 0,
}


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_file_digest(path):
    resolved_path = str(Path(path).resolve())
    digest = _file_sha256(path)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT sha256 FROM ingestion_files WHERE file_path = ?",
            (resolved_path,),
        ).fetchone()

        if row is not None:
        if row["sha256"] != digest:
            print(
                f"WARNING: {path} changed since it was ingested; skipping. "
                "Delete solution/pipeline.db to re-ingest from scratch."
            )
        return None
    return resolved_path, digest


def _mark_file_ingested(resolved_path, digest):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ingestion_files(file_path, sha256) VALUES (?, ?)",
            (resolved_path, digest),
        )


def _add_metrics(increments):
    with get_connection() as conn:
        for metric, increment in increments.items():
            conn.execute(
                """
                INSERT INTO quality_metrics(metric, value) VALUES (?, ?)
                ON CONFLICT(metric) DO UPDATE SET value = value + excluded.value
                """,
                (metric, increment),
            )


def _load_quality():
    with get_connection() as conn:
        quality = dict(METRIC_DEFAULTS)
        quality.update({
            row["metric"]: row["value"]
            for row in conn.execute(
                "SELECT metric, value FROM quality_metrics"
            )
        })
        quality["rejections_by_reason"] = {
            row["reason"]: row["count"]
            for row in conn.execute(
                """
                SELECT reason, COUNT(*) AS count
                FROM rejections
                GROUP BY reason
                ORDER BY reason
                """
            )
        }
        quality["orphan_events"] = conn.execute(
            "SELECT COUNT(*) FROM events WHERE linked = 0"
        ).fetchone()[0]
        quality["unknown_disposition_events"] = conn.execute(
            "SELECT COUNT(*) FROM events WHERE linked = 1 AND ignored = 1"
        ).fetchone()[0]
    return quality


def _load_rejections():
    with get_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT workflow_id, batch_id, row_number, reason
                FROM rejections
                """
            )
        ]


def _store_rejections(rejections):
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO rejections(
                workflow_id, batch_id, row_number, reason
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (
                    row["workflow_id"],
                    row["batch_id"],
                    row["row_number"],
                    row["reason"],
                )
                for row in rejections
            ],
        )


def ingest_drop(drop_dir):
    """Ingest a drop once; subsequent identical runs are no-ops."""
    initialize_database()
    drop_dir = Path(drop_dir)

    for workflow in WORKFLOWS:
        schema_path = SCHEMA_DIR / f"{workflow}.json"
        lead_dir = drop_dir / "leads" / workflow
        if not lead_dir.exists():
            continue

        for csv_file in sorted(lead_dir.glob("*.csv")):
            source = _existing_file_digest(csv_file)
            if source is None:
                continue
            resolved_path, digest = source

            valid, rejected, warnings = ingest_lead_file(csv_file, schema_path)
            merged = 0
            for record in valid:
                if upsert_lead(record, initialize=False) == "merged":
                    merged += 1

            _store_rejections(rejected)
            _add_metrics({
                "lead_rows_total": len(valid) + len(rejected),
                "lead_rows_rejected": len(rejected),
                "duplicate_lead_rows_merged": merged,
                "field_warnings": warnings,
            })
            _mark_file_ingested(resolved_path, digest)

    with get_connection() as conn:
        resolve_pending_events(conn)

    event_dir = drop_dir / "events"
    if event_dir.exists():
        dispositions_path = SCHEMA_DIR / "dispositions.csv"
        for event_file in sorted(event_dir.glob("*.jsonl")):
            source = _existing_file_digest(event_file)
            if source is None:
                continue
            resolved_path, digest = source
            stats = ingest_event_file(event_file, dispositions_path)
            _add_metrics({
                "events_total": stats["events_total"],
                "malformed_events": stats["malformed_events"],
                "duplicate_events_dropped": stats["duplicate_events_dropped"],
            })
            _mark_file_ingested(resolved_path, digest)


def generate_current_reports(output_dir=OUTPUT_DIR):
    initialize_database()
    generate_reports(
        output_dir,
        SCHEMA_DIR / "dispositions.csv",
        _load_rejections(),
        _load_quality(),
    )


def run_all(data_dir=DATA_DIR, output_dir=OUTPUT_DIR):
    data_dir = Path(data_dir)
    for drop_name in ("drop_1", "drop_2"):
        drop_dir = data_dir / drop_name
        if drop_dir.exists():
            ingest_drop(drop_dir)
    generate_current_reports(output_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lead and call-event pipeline")
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser("ingest", help="ingest one data drop")
    ingest_parser.add_argument("drop", type=Path)

    report_parser = subparsers.add_parser("report", help="generate report files")
    report_parser.add_argument("--out", type=Path, default=OUTPUT_DIR)

    run_parser = subparsers.add_parser(
        "run", help="ingest the configured drops and generate reports"
    )
    run_parser.add_argument("--data", type=Path, default=DATA_DIR)
    run_parser.add_argument("--out", type=Path, default=OUTPUT_DIR)

    args = parser.parse_args(argv)
    if args.command == "ingest":
        ingest_drop(args.drop)
    elif args.command == "report":
        generate_current_reports(args.out)
    else:
        run_all(
            getattr(args, "data", DATA_DIR),
            getattr(args, "out", OUTPUT_DIR),
        )


if __name__ == "__main__":
    main()
