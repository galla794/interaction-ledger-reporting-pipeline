# Assignment A solution

Run commands from the `solution` directory (install the repository's
`requirements.txt` first):

```powershell
python main.py ingest ..\data\drop_1
python main.py ingest ..\data\drop_2
python main.py report --out ..\reports
python -m pytest -q
```

`python main.py run` ingests the configured `data\drop_1` and `data\drop_2`
directories before writing reports to `..\reports`. Input files are recorded by
resolved path and SHA-256, so an identical drop can be submitted again without
changing data-quality totals. A changed file at an already-ingested path is
rejected; use a fresh database for a revised input set.

SQLite stores lead PII using Fernet encryption for names and a keyed HMAC token
for phone identity. Event records keep the HMAC token rather than the phone.
`events` is the event ledger; linkage state may be updated when a previously
orphaned event's lead arrives, while event content is not overwritten.
Unknown dispositions are retained with an ignored flag for deduplication and
excluded from reports. `ingestion_files`, `quality_metrics`, and `rejections`
preserve idempotency and report-quality state between commands.
