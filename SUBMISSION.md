# Submission

## Candidate
- **Name:** Galla Jayadev
- **Assignment chosen:A (13-11-2026)
- **Time spent (honest estimate): 7 hours

## How to Run

```bash
pip install -r requirements.txt
python solution/main.py
pytest -v
```

## Design

The solution follows a structured data engineering pipeline.

- Ingests lead and interaction event data.
- Validates incoming records.
- Handles duplicate and invalid records.
- Stores processed data in a database.
- Maintains interaction records for reliable reporting.
- Generates the required business reports.

The design focuses on data integrity, consistency and reliable processing.

## Decisions & Assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| Separate ingestion and processing | Easier maintenance | Single processing script |
| Validate input records | Maintain data quality | Direct processing |
| Handle duplicate events | Avoid repeated records | Allow duplicates |
| Use database constraints | Maintain data integrity | Application-only validation |
| Generate structured reports | Easy analysis | Manual reporting |

## Failure Modes Considered

- Invalid or missing input data.
- Duplicate records and events.
- Database connection failures.
- Repeated pipeline execution.
- Unexpected input formats.

These scenarios were considered during implementation. Additional crash recovery and failure testing could improve reliability.

## Testing

- Reviewed Python implementation.
- Checked data validation and processing.
- Inspected database loading.
- Reviewed duplicate-handling logic.
- Used GitHub Copilot for test-case suggestions and testing assistance.
- Used ChatGPT for understanding requirements and debugging.

Additional edge-case and failure-recovery testing remains an area for improvement.

## Results

The solution implements the data processing workflow and generates structured reporting outputs.

The generated reports and actual execution results should be verified against the final pipeline run before submission.

## If I Had Another Day

1. Improve automated test coverage.
2. Perform additional idempotency testing.
3. Strengthen database constraints.
4. Improve error handling and logging.
5. Test with larger datasets and optimize performance.
