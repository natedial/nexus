from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass

import numpy as np


@dataclass
class EmbeddingConfig:
    model_name: str = "all-MiniLM-L6-v2"
    normalize: bool = True
    batch_size: int = 32
    local_files_only: bool = False
    quiet: bool = False


class EmbeddingModel:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - runtime error path
            raise RuntimeError(
                "sentence-transformers is required. Install with `pip install sentence-transformers`."
            ) from exc
        if config.quiet:
            try:
                from transformers.utils import logging as transformers_logging

                transformers_logging.set_verbosity_error()
                transformers_logging.disable_progress_bar()
            except Exception:
                pass
        if config.quiet:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self._model = SentenceTransformer(config.model_name, local_files_only=config.local_files_only)
        else:
            self._model = SentenceTransformer(config.model_name, local_files_only=config.local_files_only)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype="float32")
        if self.config.quiet:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                vectors = self._model.encode(
                    texts,
                    batch_size=self.config.batch_size,
                    convert_to_numpy=True,
                    normalize_embeddings=self.config.normalize,
                )
        else:
            vectors = self._model.encode(
                texts,
                batch_size=self.config.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=self.config.normalize,
            )
        return vectors.astype("float32")
