import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.storage_service import StorageService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and store one PDF using StorageService."
    )
    parser.add_argument("pdf_path", type=Path, help="Path to the sample PDF")
    parser.add_argument(
        "--application",
        default="APP-TEST-001",
        help="Application reference used for the storage folder",
    )
    args = parser.parse_args()

    service = StorageService()
    stored_file = service.store_pdf(
        source_path=args.pdf_path,
        application_reference=args.application,
        declared_mime_type="application/pdf",
    )

    print("[SUCCESS] PDF validated and stored")
    print(json.dumps(asdict(stored_file), indent=2))


if __name__ == "__main__":
    main()
