import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from app.core.config import PROJECT_ROOT, settings  # noqa: E402

print(f"Project root: {PROJECT_ROOT}")
print(f"Application: {settings.app_name}")
print(f"Environment: {settings.app_env}")

print(f"Upload directory: " f"{settings.resolve_path(settings.upload_dir)}")

print(f"Extracted directory: " f"{settings.resolve_path(settings.extracted_dir)}")

print(f"FAISS directory: " f"{settings.resolve_path(settings.faiss_dir)}")

print(f"Generated directory: " f"{settings.resolve_path(settings.generated_dir)}")

print(f"Temporary directory: " f"{settings.resolve_path(settings.temp_dir)}")

print(f"FAISS index: {settings.faiss_index_name}")
print(f"Allowed types: {settings.get_allowed_file_types()}")
