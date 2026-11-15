# Submission

## Candidate
- **Name:** Galla Jayadev
- **Assignment chosen:** A (13-11-2026)
- **Time spent (honest estimate):** 7h

## How to run
```bash
pip install -r requirements.txt
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
cd solution
python main.py ingest ../data/drop_1
python main.py ingest ../data/drop_2
python main.py report --out ../reports
python -m pytest -q
```
To start from scratch, delete `solution/pipeline.db` and `solution/.secret.key`.

## Design
- **Database:** SQLite (`solution/pipeline.db`), Python standard library plus `cryptography`.
- **Tables:**
  - `leads`: one row per (workflow_id, phone_hash), UNIQUE. Holds the batch_id of the first valid row, `phone_last4`, and the encrypted customer name.
  - `events`: the append-only ledger, with `event_id` as PRIMARY KEY. Event content is never edited; only the link columns (`lead_id`, `linked`) are filled in when a lead arrives later.
  - `rejections`: the rejected lead rows, with no PII.
  - `ingestion_files`: path plus SHA-256 of each ingested file, which makes re-ingest a no-op.
  - `quality_metrics`: running counters for data_quality.json.
- **PII:** phone is stored only as an HMAC-SHA256 token (keyed), which is enough to match events to leads. The customer name is encrypted with Fernet. Only the last 4 digits of the phone are stored, to build `phone_masked`.
- **Late-arriving data:** events are stored even if no lead exists yet. When a later drop brings the lead, the events are linked. Reports use only linked events, so drop_1 then drop_2 gives the same result as everything at once.
- **Reports:** calls, effective disposition and buckets are derived at report time from the ledger. An override never edits the original event.

## Decisions & assumptions
| Decision | Why | Alternative considered |
|---|---|---|
| Phone matching by HMAC token | Avoids plaintext phones but still allows matching | Plain SHA-256 (can be brute-forced; only about 4 billion Indian mobile numbers) |
| Store `phone_last4` | Needed for the masked phone in lead_report | Decrypt a stored phone at report time |
| Unknown dispositions stored with an `ignored` flag | Keeps them for event_id dedupe, excluded from reports | Drop them at ingest (a duplicate later would be miscounted) |
| Idempotency by file path + SHA-256 | Re-ingest does nothing | Hash only the file name |
| Orphan count computed at report time | Reflects the final state, as the spec requires | Count at ingest time |
| First valid row sets batch_id; later rows merge non-null fields | Follows the spec | None |

## Failure modes considered
- Bad rows (invalid phone, missing required field): rejected with a reason.
- Malformed JSON lines and duplicate event_ids: counted and skipped.
- Re-running a drop: skipped by file hash.
- Changed file at the same path: warned and skipped.
- **Not handled:** a crash in the middle of a file can leave it partly ingested (rows are committed one by one, not in one transaction per file); the encryption key is stored in a local file, not a secrets manager.

## Testing
- Unit tests for phone, date and decimal parsing, event dedupe, unknown dispositions and the override/bucket logic.
- I also compared my reports against an independent reference script on several seeds. _(Only keep this line if you do it yourself; see the note in AI_USAGE.)_
- Not tested: very large inputs.

## Results
- Small dataset: _fill in your own timing from `time python main.py ...`_.
- Large dataset: _fill in your own timing, or write that it is slow and needs batching._

## If I had another day
1. One transaction per file and `executemany` to speed up ingestion; the large dataset is currently slow.
2. Read the encryption key from an environment variable.
3. More tests: orphan relinking across drops, drop order, crash recovery.
4. Make the lead table schema-driven instead of hard-coded columns.
