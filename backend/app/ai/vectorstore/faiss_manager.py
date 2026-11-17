from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from threading import RLock

import faiss
import numpy as np


class FaissIndexManager:
    """Cosine FAISS index with normalized vectors and atomic persistence."""

    def __init__(self, index_path: Path, dimension: int) -> None:
        self.index_path = index_path.resolve()
        self.dimension = dimension
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.index = self._load_or_create()

    def _load_or_create(self):
        if self.index_path.exists():
            index = faiss.read_index(str(self.index_path))
            if index.d != self.dimension:
                raise ValueError(
                    f"FAISS dimension {index.d} != embedding dimension {self.dimension}"
                )
            return index
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dimension))

    def add_many(self, vector_ids: list[int], vectors: list[list[float]]) -> None:
        if not vector_ids:
            return
        if len(vector_ids) != len(vectors):
            raise ValueError("Vector ID and embedding counts do not match.")
        array = np.asarray(vectors, dtype="float32")
        if array.ndim != 2 or array.shape[1] != self.dimension:
            raise ValueError("Embedding dimension mismatch")
        if not np.isfinite(array).all():
            raise ValueError("Embedding array contains non-finite values")
        ids = np.asarray(vector_ids, dtype="int64")
        if len(ids) != len(set(ids.tolist())):
            raise ValueError("Duplicate FAISS vector IDs were supplied")
        faiss.normalize_L2(array)
        with self._lock:
            self.index.add_with_ids(array, ids)

    def remove(self, vector_ids: list[int]) -> int:
        if not vector_ids:
            return 0
        ids = np.asarray(vector_ids, dtype="int64")
        with self._lock:
            return int(self.index.remove_ids(ids))

    def save_atomic(self) -> None:
        with self._lock:
            fd, temp_name = tempfile.mkstemp(
                suffix=".faiss.tmp", dir=self.index_path.parent
            )
            os.close(fd)
            try:
                faiss.write_index(self.index, temp_name)
                os.replace(temp_name, self.index_path)
            finally:
                Path(temp_name).unlink(missing_ok=True)

    def create_backup(self) -> Path | None:
        if not self.index_path.exists():
            return None
        fd, backup_name = tempfile.mkstemp(
            suffix=".faiss.backup", dir=self.index_path.parent
        )
        os.close(fd)
        backup = Path(backup_name)
        shutil.copy2(self.index_path, backup)
        return backup

    def restore_backup(self, backup: Path | None) -> None:
        if backup is None:
            self.index_path.unlink(missing_ok=True)
            return
        os.replace(backup, self.index_path)

    @staticmethod
    def discard_backup(backup: Path | None) -> None:
        if backup is not None:
            backup.unlink(missing_ok=True)

    @property
    def total_vectors(self) -> int:
        return int(self.index.ntotal)
