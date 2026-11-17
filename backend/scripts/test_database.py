import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.db.session import engine  # noqa: E402


def test_database_connection() -> None:
    try:
        with engine.connect() as connection:
            database_name = connection.execute(
                text("SELECT current_database();")
            ).scalar_one()

            schema_exists = connection.execute(text("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.schemata
                        WHERE schema_name = 'credit_ai'
                    );
                    """)).scalar_one()

            table_count = connection.execute(text("""
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'credit_ai';
                    """)).scalar_one()

        print("[SUCCESS] PostgreSQL connection established")
        print(f"Database: {database_name}")
        print(f"credit_ai schema exists: {schema_exists}")
        print(f"credit_ai table count: {table_count}")

    except Exception as exc:
        print("[FAILED] PostgreSQL connection failed")
        print(f"Error type: {type(exc).__name__}")
        print(f"Details: {exc}")
        raise


if __name__ == "__main__":
    test_database_connection()
