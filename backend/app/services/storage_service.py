from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import settings

PDF_EXTENSION = ".pdf"
PDF_MIME_TYPE = "application/pdf"
PDF_SIGNATURE = b"%PDF-"
HASH_CHUNK_SIZE = 1024 * 1024  # 1 MB


class StorageError(Exception):
    """Base exception for storage operations."""


class InvalidFileError(StorageError):
    """Raised when an uploaded file fails validation."""


class FileTooLargeError(StorageError):
    """Raised when a file exceeds the configured upload-size limit."""


class DuplicateFileError(StorageError):
    """Raised when the same file already exists in the target application."""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Metadata returned after a file is validated and stored."""

    original_filename: str
    stored_filename: str
    storage_path: str
    mime_type: str
    file_size_bytes: int
    file_hash: str


class StorageService:
    """Validate and store uploaded PDF documents safely."""

    def __init__(self, upload_root: Path | None = None) -> None:
        configured_root = upload_root or settings.resolve_path(settings.upload_dir)
        self.upload_root = configured_root.resolve()
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.max_file_size_bytes = settings.max_upload_size_mb * 1024 * 1024
        self.allowed_mime_types = settings.get_allowed_file_types()

    def store_pdf(
        self,
        source_path: Path,
        application_reference: str,
        declared_mime_type: str = PDF_MIME_TYPE,
    ) -> StoredFile:
        """Validate a local PDF and copy it into application-specific storage.

        This method is reusable by scripts now and by a FastAPI upload endpoint later.
        It does not create the PostgreSQL Document row. The caller receives metadata
        required to create that row inside a database transaction.
        """

        source_path = source_path.resolve()
        self._validate_source_path(source_path)
        self._validate_extension(source_path.name)
        self._validate_mime_type(declared_mime_type)
        self._validate_pdf_signature(source_path)

        file_size = source_path.stat().st_size
        self._validate_file_size(file_size)

        file_hash = self.calculate_sha256(source_path)
        safe_application_reference = self._sanitize_component(application_reference)
        target_directory = self.upload_root / safe_application_reference / "documents"
        target_directory.mkdir(parents=True, exist_ok=True)

        self._ensure_not_duplicate(target_directory, file_hash)

        safe_stem = self._sanitize_component(source_path.stem)
        stored_filename = f"{safe_stem}_{uuid4().hex}{PDF_EXTENSION}"
        destination = target_directory / stored_filename
        temporary_destination = destination.with_suffix(".uploading")

        try:
            shutil.copyfile(source_path, temporary_destination)

            copied_hash = self.calculate_sha256(temporary_destination)
            if copied_hash != file_hash:
                raise StorageError("Stored file failed integrity verification.")

            temporary_destination.replace(destination)
            self._write_hash_marker(destination, file_hash)

        except Exception:
            temporary_destination.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

        return StoredFile(
            original_filename=source_path.name,
            stored_filename=stored_filename,
            storage_path=str(destination),
            mime_type=declared_mime_type,
            file_size_bytes=file_size,
            file_hash=file_hash,
        )

    @staticmethod
    def calculate_sha256(file_path: Path) -> str:
        """Calculate a SHA-256 fingerprint without loading the full file into RAM."""

        digest = hashlib.sha256()
        with file_path.open("rb") as file_handle:
            while chunk := file_handle.read(HASH_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_source_path(self, source_path: Path) -> None:
        if not source_path.exists():
            raise InvalidFileError(f"File does not exist: {source_path}")
        if not source_path.is_file():
            raise InvalidFileError(f"Path is not a file: {source_path}")

    @staticmethod
    def _validate_extension(filename: str) -> None:
        if Path(filename).suffix.lower() != PDF_EXTENSION:
            raise InvalidFileError("Only .pdf files are allowed.")

    def _validate_mime_type(self, mime_type: str) -> None:
        normalized_mime_type = mime_type.split(";", maxsplit=1)[0].strip().lower()
        if normalized_mime_type not in self.allowed_mime_types:
            raise InvalidFileError(
                f"MIME type '{mime_type}' is not allowed. "
                f"Allowed types: {sorted(self.allowed_mime_types)}"
            )

    @staticmethod
    def _validate_pdf_signature(file_path: Path) -> None:
        with file_path.open("rb") as file_handle:
            signature = file_handle.read(len(PDF_SIGNATURE))

        if signature != PDF_SIGNATURE:
            raise InvalidFileError(
                "The file does not contain a valid PDF signature (%PDF-)."
            )

    def _validate_file_size(self, file_size: int) -> None:
        if file_size == 0:
            raise InvalidFileError("The uploaded file is empty.")
        if file_size > self.max_file_size_bytes:
            raise FileTooLargeError(
                f"File size exceeds the {settings.max_upload_size_mb} MB limit."
            )

    @staticmethod
    def _sanitize_component(value: str) -> str:
        """Create a Windows-safe filename or directory component."""

        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
        sanitized = sanitized.strip("._")
        if not sanitized:
            raise InvalidFileError("Filename or application reference is invalid.")
        return sanitized[:100]

    def _ensure_not_duplicate(self, target_directory: Path, file_hash: str) -> None:
        for marker_path in target_directory.glob("*.sha256"):
            try:
                existing_hash = marker_path.read_text(encoding="ascii").strip()
            except OSError:
                continue

            if existing_hash == file_hash:
                stored_pdf = marker_path.with_suffix("")
                raise DuplicateFileError(
                    "This exact PDF is already stored for the application: "
                    f"{stored_pdf.name}"
                )

    @staticmethod
    def _write_hash_marker(stored_path: Path, file_hash: str) -> None:
        marker_path = stored_path.with_name(f"{stored_path.name}.sha256")
        marker_path.write_text(file_hash, encoding="ascii")
