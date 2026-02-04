from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class EmbeddingConfig:
    model_name: str = "all-MiniLM-L6-v2"
    normalize: bool = True
    batch_size: int = 32


class EmbeddingModel:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - runtime error path
            raise RuntimeError(
                "sentence-transformers is required. Install with `pip install sentence-transformers`."
            ) from exc
        self._model = SentenceTransformer(config.model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype="float32")
        vectors = self._model.encode(
            texts,
            batch_size=self.config.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=self.config.normalize,
        )
        return vectors.astype("float32")
