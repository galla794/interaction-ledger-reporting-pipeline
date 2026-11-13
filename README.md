# Interaction Ledger & Reporting Pipeline

## Project Overview

This project implements a data engineering pipeline designed to ingest, validate, process, and manage lead and interaction event data.

The pipeline focuses on building a reliable interaction ledger, maintaining data consistency, handling duplicate records, validating incoming data, and generating accurate business reports.

The solution is developed as part of the Agentic Universe Junior SDE Take-Home Assignment.

## Objectives

- Ingest lead and interaction event data from input files.
- Validate incoming records and handle invalid data.
- Prevent duplicate event processing.
- Maintain a reliable interaction ledger.
- Implement database schema and data relationships.
- Ensure idempotent pipeline execution.
- Generate business reports and data quality metrics.
- Handle sensitive information responsibly.

## Technology Stack

- **Programming Language:** Python 3.11+
- **Data Processing:** Pandas
- **Database:** SQLite / PostgreSQL (as implemented)
- **Data Format:** CSV, JSONL
- **Testing:** Pytest
- **Version Control:** Git and GitHub

## Project Structure

```text
interaction-ledger-reporting-pipeline/
│
├── solution/
│   └── Source code and pipeline implementation
│
├── tests/
│   └── Test cases
│
├── README.md
├── SUBMISSION.md
├── AI_USAGE.md
├── requirements.txt
└── .gitignore
```

*The structure above describes the intended organization; adjust it to match the actual files in the repository.*

## Key Features

### 1. Data Ingestion
Reads lead records and interaction events from the provided input files.

### 2. Data Validation
Checks incoming records for missing values, invalid formats, and data inconsistencies.

### 3. Duplicate Handling
Identifies duplicate records and prevents repeated processing.

### 4. Interaction Ledger
Maintains a structured record of interaction events for reliable reporting and tracking.

### 5. Idempotency
Ensures that running the pipeline multiple times does not incorrectly duplicate previously processed records.

### 6. Reporting
Generates reports containing business metrics and data quality information.

## Installation and Setup

Clone the repository:

```bash
git clone https://github.com/galla794/interaction-ledger-reporting-pipeline.git

cd interaction-ledger-reporting-pipeline
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate the environment:

Windows:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the Project

Run the pipeline using the actual entry-point script provided in the `solution/` directory.

Example:

```bash
python solution/main.py
```

## Running Tests

```bash
pytest -v
```

## Generated Reports

The pipeline is designed to produce reporting outputs such as:

- Batch Summary
- Daily Overview
- Lead Report
- Rejected Records
- Data Quality Report

Refer to the implementation for the exact output filenames and formats.

## Design Considerations

- Data consistency and integrity
- Duplicate prevention
- Idempotent processing
- Input validation
- Database constraints
- Responsible handling of sensitive information
- Maintainable and testable code

## Documentation

- **SUBMISSION.md:** Implementation approach, design decisions, assumptions, trade-offs, and future improvements.
- **AI_USAGE.md:** Disclosure of AI tools used during development.

## Author

**Galla Jayadev**

GitHub: https://github.com/galla794

---

**Project:** Interaction Ledger & Reporting Pipeline  
**Assignment:** Agentic Universe – Junior SDE Take-Home Assignment
