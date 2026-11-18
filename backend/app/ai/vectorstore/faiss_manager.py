from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import faiss
import numpy as np


class FaissIndexManager:
    """Small atomic cosine-index manager using explicit int64 vector IDs."""

    def __init__(self, index_path: Path, dimension: int) -> None:
        self.index_path = Path(index_path)
        self.dimension = int(dimension)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index = self._load_or_create()

    @property
    def total_vectors(self) -> int:
        return int(self.index.ntotal)

    def _load_or_create(self):
        if self.index_path.exists():
            index = faiss.read_index(str(self.index_path))
            if index.d != self.dimension:
                raise ValueError(
                    f"Existing FAISS dimension {index.d} != embedding dimension {self.dimension}"
                )
            if not hasattr(index, "add_with_ids"):
                raise ValueError("Existing FAISS index must support explicit vector IDs")
            return index
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dimension))

    def add_many(self, vector_ids: list[int], embeddings: list[list[float]]) -> None:
        if not vector_ids:
            return
        matrix = np.asarray(embeddings, dtype="float32")
        ids = np.asarray(vector_ids, dtype="int64")
        if matrix.ndim != 2 or matrix.shape[1] != self.dimension:
            raise ValueError(
                f"Embedding matrix shape {matrix.shape} is incompatible with dimension {self.dimension}"
            )
        if len(ids) != len(matrix):
            raise ValueError("Vector ID count does not match embedding count")
        if not np.isfinite(matrix).all():
            raise ValueError("Embedding matrix contains non-finite values")
        faiss.normalize_L2(matrix)
        self.index.add_with_ids(matrix, ids)

    def remove(self, vector_ids: list[int]) -> int:
        if not vector_ids or self.index.ntotal == 0:
            return 0
        ids = np.asarray(vector_ids, dtype="int64")
        return int(self.index.remove_ids(ids))

    def save_atomic(self) -> None:
        temporary = self.index_path.with_name(
            f".{self.index_path.name}.{uuid4().hex}.tmp"
        )
        try:
            faiss.write_index(self.index, str(temporary))
            os.replace(temporary, self.index_path)
        finally:
            temporary.unlink(missing_ok=True)

    def create_backup(self) -> Path | None:
        if not self.index_path.exists():
            return None
        backup = self.index_path.with_name(
            f".{self.index_path.name}.{uuid4().hex}.backup"
        )
        shutil.copy2(self.index_path, backup)
        return backup

    def restore_backup(self, backup: Path | None) -> None:
        if backup and backup.exists():
            os.replace(backup, self.index_path)
            self.index = faiss.read_index(str(self.index_path))
        elif not backup:
            self.index_path.unlink(missing_ok=True)
            self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dimension))

    @staticmethod
    def discard_backup(backup: Path | None) -> None:
        if backup:
            backup.unlink(missing_ok=True)
