
import csv
import json
import re
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalize_header(header):
    """Normalize CSV headers for schema matching."""
    return re.sub(r"[_\s]+", " ", header.strip().lower())


def normalize_phone(value):
    """Normalize and validate Indian mobile numbers."""
    digits = re.sub(r"\D", "", str(value))

    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("invalid_phone")

    return "+91" + digits


def normalize_date(value):
    """Accept the date formats specified in the assignment."""
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    raise ValueError("invalid_date")


def normalize_decimal(value):
    """Normalize currency values to two decimal places."""
    cleaned = re.sub(
        r"^(?:₹|rs\.?|inr)\s*",
        "",
        value.strip(),
        flags=re.IGNORECASE
    )

    if "," in cleaned:
        if not re.fullmatch(
            r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?",
            cleaned
        ):
            raise ValueError("invalid_decimal")
        cleaned = cleaned.replace(",", "")
    elif not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", cleaned):
        raise ValueError("invalid_decimal")

    try:
        number = Decimal(cleaned)

        if not number.is_finite() or number < 0:
            raise ValueError("invalid_decimal")

        return str(number.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        ))
    except InvalidOperation:
        raise ValueError("invalid_decimal")


def load_schema(schema_path):
    with open(schema_path, "r", encoding="utf-8") as file:
        return json.load(file)


def build_header_mapping(headers, fields):
    """Map CSV headers to schema field names."""
    aliases = {}

    for field in fields:
        aliases[normalize_header(field["name"])] = field["name"]

        for alias in field.get("aliases", []):
            aliases[normalize_header(alias)] = field["name"]

    mapping = {}

    for header in headers:
        normalized = normalize_header(header)

        if normalized in aliases:
            mapping[header] = aliases[normalized]

    return mapping


def validate_value(value, field):
    """Validate one value according to its schema definition."""
    field_type = field["type"]

    if field_type == "string":
        return value

    if field_type == "phone":
        return normalize_phone(value)

    if field_type == "date":
        return normalize_date(value)

    if field_type == "decimal":
        return normalize_decimal(value)

    if field_type == "enum":
        normalized = value.lower()

        allowed = [
            str(item).lower()
            for item in field.get("values", [])
        ]

        if normalized not in allowed:
            raise ValueError("invalid_enum")

        return normalized

    raise ValueError(f"unsupported_type:{field_type}")


def ingest_lead_file(csv_path, schema_path):
    """
    Read and validate a lead CSV file.

    Returns:
        valid_rows, rejections, field_warnings
    """
    schema = load_schema(schema_path)
    fields = schema["fields"]
    workflow_id = schema["workflow_id"]

    batch_id = Path(csv_path).stem

    valid_rows = []
    rejections = []
    field_warnings = 0

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            return valid_rows, rejections, field_warnings

        mapping = build_header_mapping(reader.fieldnames, fields)

        row_number = 0

        for raw_row in reader:
            values = [
                str(value or "").strip()
                for value in raw_row.values()
            ]

            # Skip completely blank rows.
            if not any(values):
                continue

            row_number += 1

            mapped = {}

            for header, field_name in mapping.items():
                mapped[field_name] = (
                    raw_row.get(header) or ""
                ).strip()

            record = {
                "workflow_id": workflow_id,
                "batch_id": batch_id,
                "_defaults": {
                    field["name"]: field["default"]
                    for field in fields
                    if "default" in field
                }
            }

            rejection_reason = None
            row_warnings = 0

            # Validate fields in schema order.
            for field in fields:
                name = field["name"]
                value = mapped.get(name, "")

                if not value:
                    if field.get("required", False):
                        rejection_reason = (
                            f"missing_required:{name}"
                        )
                        break

                    record[name] = None
                    continue

                try:
                    record[name] = validate_value(value, field)

                except ValueError as error:
                    if field.get("required", False):
                        rejection_reason = str(error)
                        break

                    record[name] = None
                    row_warnings += 1

            if rejection_reason:
                rejections.append({
                    "workflow_id": workflow_id,
                    "batch_id": batch_id,
                    "row_number": row_number,
                    "reason": rejection_reason
                })
            else:
                record["policy_number"] = (
                    record.get("policy_number")
                    or record.get("order_id")
                )

                valid_rows.append(record)
                field_warnings += row_warnings

    return valid_rows, rejections, field_warnings