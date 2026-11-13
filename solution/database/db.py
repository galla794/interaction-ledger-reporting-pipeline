
import sqlite3
import hashlib
import hmac
from pathlib import Path

from cryptography.fernet import Fernet


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "pipeline.db"
KEY_PATH = BASE_DIR / ".secret.key"


def get_cipher():
    """Load or create the encryption key."""
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(Fernet.generate_key())

    key = KEY_PATH.read_bytes()
    return Fernet(key)


def phone_hash(phone):
    """Create a deterministic, keyed phone token."""

    get_cipher()  # Create encryption key if it doesn't exist

    key = hashlib.sha256(
        KEY_PATH.read_bytes() + b"phone"
    ).digest()

    return hmac.new(
        key,
        phone.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def encrypt_name(name):
    if not name:
        return None

    return get_cipher().encrypt(
        name.encode("utf-8")
    ).decode("utf-8")


def decrypt_name(encrypted_name):
    if not encrypted_name:
        return None

    return get_cipher().decrypt(
        encrypted_name.encode("utf-8")
    ).decode("utf-8")


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    """Create the database tables."""

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                phone_hash TEXT NOT NULL,
                phone_last4 TEXT NOT NULL,
                customer_name_enc TEXT,
                policy_number TEXT NOT NULL,
                policy_expiry TEXT,
                premium_amount TEXT,
                product TEXT,
                order_date TEXT,
                preferred_language TEXT,
                batch_id TEXT NOT NULL,
                UNIQUE(workflow_id, phone_hash)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                call_id TEXT,
                event_type TEXT NOT NULL,
                occurred_at TEXT,
                phone_hash TEXT,
                payload TEXT,
                lead_id INTEGER,
                linked INTEGER DEFAULT 0,
                ignored INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(lead_id) REFERENCES leads(id)
            )
        """)

        lead_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(leads)")
        }
        for column in ("product", "order_date"):
            if column not in lead_columns:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {column} TEXT")

        event_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(events)")
        }
        if "ignored" not in event_columns:
            conn.execute(
                "ALTER TABLE events ADD COLUMN ignored INTEGER NOT NULL DEFAULT 0"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_files (
                file_path TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS rejections (
                workflow_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY(workflow_id, batch_id, row_number)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_metrics (
                metric TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_call
            ON events(workflow_id, call_id)
        """)


def upsert_lead(record, initialize=True):
    """
    Insert a new lead or merge a duplicate.

    First batch_id is preserved.
    Non-null incoming values overwrite existing values.
    """

    if initialize:
        initialize_database()

    phone = record["phone"]
    hashed_phone = phone_hash(phone)

    encrypted_name = encrypt_name(
        record.get("customer_name")
    )
    defaults = record.get("_defaults", {})

    with get_connection() as conn:

        existing = conn.execute("""
            SELECT id FROM leads
            WHERE workflow_id = ? AND phone_hash = ?
        """, (
            record["workflow_id"],
            hashed_phone
        )).fetchone()

        if existing is None:

            conn.execute("""
                INSERT INTO leads (
                    workflow_id,
                    phone_hash,
                    phone_last4,
                    customer_name_enc,
                    policy_number,
                    policy_expiry,
                    premium_amount,
                    product,
                    order_date,
                    preferred_language,
                    batch_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record["workflow_id"],
                hashed_phone,
                phone[-4:],
                encrypted_name,
                record["policy_number"],
                record.get("policy_expiry"),
                record.get("premium_amount"),
                record.get("product"),
                record.get("order_date"),
                record.get("preferred_language")
                or defaults.get("preferred_language"),
                record["batch_id"]
            ))

            return "inserted"

        else:

            conn.execute("""
                UPDATE leads
                SET
                    customer_name_enc =
                        COALESCE(?, customer_name_enc),
                    policy_number =
                        COALESCE(?, policy_number),
                    policy_expiry =
                        COALESCE(?, policy_expiry),
                    premium_amount =
                        COALESCE(?, premium_amount),
                    product =
                        COALESCE(?, product),
                    order_date =
                        COALESCE(?, order_date),
                    preferred_language =
                        COALESCE(?, preferred_language)
                WHERE id = ?
            """, (
                encrypted_name,
                record.get("policy_number"),
                record.get("policy_expiry"),
                record.get("premium_amount"),
                record.get("product"),
                record.get("order_date"),
                record.get("preferred_language"),
                existing["id"]
            ))

            return "merged"
if __name__ == "__main__":
    initialize_database()
    print("Database created successfully")