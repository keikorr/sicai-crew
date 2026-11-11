"""Modelos de embedding e reranking, carregados só quando usados."""

import threading

import numpy as np

from sicai import config

_trava = threading.Lock()
_embedder = None
_reranker = None


def _modelo_embedding():
    global _embedder
    with _trava:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer

            _embedder = SentenceTransformer(config.EMBEDDING_MODEL)
        return _embedder


def embutir(textos: list[str]) -> np.ndarray:
    """Vetores normalizados (produto interno = similaridade de cosseno)."""
    vetores = _modelo_embedding().encode(
        textos, normalize_embeddings=True, show_progress_bar=False
    )
    return np.asarray(vetores, dtype="float32")


def reordenar(consulta: str, indices: list[int], chunks: list[dict]) -> list[int]:
    """Reordena candidatos com um cross-encoder (RERANKER_MODEL)."""
    global _reranker
    with _trava:
        if _reranker is None:
            from sentence_transformers import CrossEncoder

            _reranker = CrossEncoder(config.RERANKER_MODEL)
    pares = [(consulta, chunks[i]["content"]) for i in indices]
    pontos = _reranker.predict(pares)
    ordem = sorted(range(len(indices)), key=lambda p: -float(pontos[p]))
    return [indices[p] for p in ordem]
