"""Índice de trechos por processo: busca densa, lexical (BM25) e literal.

Os vetores ficam num .npy e a busca densa é um produto interno em numpy. Com
vetores normalizados isso equivale ao IndexFlatIP do FAISS usado antes, e
permite substituir um documento sem recriar o índice inteiro.
"""

import json
import math
import re
import threading
from collections import Counter

import numpy as np

from sicai import config
from sicai.text import contem_literal, extrair_identificadores, normalizar

_cache: dict[str, "VectorStore"] = {}
_trava = threading.Lock()


def _tokens(texto: str) -> list[str]:
    return re.findall(r"\w+", normalizar(texto))


class _BM25:
    def __init__(self, documentos: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.frequencias = [Counter(doc) for doc in documentos]
        self.tamanhos = [len(doc) for doc in documentos]
        self.media = (sum(self.tamanhos) / len(documentos)) if documentos else 0.0
        presenca = Counter(termo for freq in self.frequencias for termo in freq)
        total = len(documentos)
        self.idf = {
            termo: math.log(1 + (total - n + 0.5) / (n + 0.5))
            for termo, n in presenca.items()
        }

    def pontuar(self, consulta: list[str]) -> list[float]:
        pontos = []
        for freq, tamanho in zip(self.frequencias, self.tamanhos):
            total = 0.0
            for termo in consulta:
                f = freq.get(termo, 0)
                if not f:
                    continue
                norma = 1 - self.b + self.b * tamanho / (self.media or 1)
                total += self.idf.get(termo, 0.0) * f * (self.k1 + 1) / (f + self.k1 * norma)
            pontos.append(total)
        return pontos


class VectorStore:
    """Trechos e vetores de um processo, persistidos em DATA_DIR/<processo_id>/."""

    def __init__(self, processo_id: str):
        self.processo_id = config.validar_processo_id(processo_id)
        self.pasta = config.DATA_DIR / processo_id
        self.chunks: list[dict] = []
        self.vetores = np.zeros((0, 0), dtype="float32")
        self._bm25: _BM25 | None = None
        self._carregar()

    # ------------------------------------------------------------ persistência
    @classmethod
    def abrir(cls, processo_id: str) -> "VectorStore":
        """Instância compartilhada por processo (a API reutiliza entre requisições)."""
        with _trava:
            if processo_id not in _cache:
                _cache[processo_id] = cls(processo_id)
            return _cache[processo_id]

    @classmethod
    def invalidar(cls, processo_id: str) -> None:
        with _trava:
            _cache.pop(processo_id, None)

    def existe(self) -> bool:
        return bool(self.chunks)

    def _carregar(self) -> None:
        arq_chunks = self.pasta / "chunks.json"
        arq_vetores = self.pasta / "embeddings.npy"
        if arq_chunks.exists() and arq_vetores.exists():
            self.chunks = json.loads(arq_chunks.read_text(encoding="utf-8"))
            self.vetores = np.load(arq_vetores)

    def salvar(self) -> None:
        self.pasta.mkdir(parents=True, exist_ok=True)
        (self.pasta / "chunks.json").write_text(
            json.dumps(self.chunks, ensure_ascii=False), encoding="utf-8"
        )
        np.save(self.pasta / "embeddings.npy", self.vetores)

    # ---------------------------------------------------------------- escrita
    def substituir_documento(
        self, document_id: str, chunks: list[dict], vetores: np.ndarray
    ) -> None:
        """Troca os trechos de um documento, preservando os demais."""
        manter = [i for i, c in enumerate(self.chunks) if c["document_id"] != document_id]
        antigos = [self.chunks[i] for i in manter]
        vetores = np.asarray(vetores, dtype="float32")

        if manter and self.vetores.size:
            base = self.vetores[manter]
            self.vetores = np.vstack([base, vetores]) if len(chunks) else base
        else:
            self.vetores = vetores

        self.chunks = antigos + list(chunks)
        self._bm25 = None

    # ----------------------------------------------------------------- buscas
    def busca_literal(self, consulta: str) -> list[tuple[int, list[str]]]:
        """Trechos que contêm literalmente os identificadores da consulta."""
        identificadores = extrair_identificadores(consulta)
        if not identificadores:
            return []
        resultados = []
        for indice, chunk in enumerate(self.chunks):
            achados = [i for i in identificadores if contem_literal(i, chunk["content"])]
            if achados:
                resultados.append((indice, achados))
        return resultados

    def _ranking_denso(self, consulta: str, limite: int) -> list[int]:
        from sicai.store.embeddings import embutir

        if not len(self.chunks):
            return []
        vetor = embutir([consulta])[0]
        pontos = self.vetores @ vetor
        return [int(i) for i in np.argsort(-pontos)[:limite]]

    def _ranking_lexical(self, consulta: str, limite: int) -> list[int]:
        if self._bm25 is None:
            self._bm25 = _BM25([_tokens(c["content"]) for c in self.chunks])
        pontos = self._bm25.pontuar(_tokens(consulta))
        ordem = sorted(range(len(pontos)), key=lambda i: -pontos[i])
        return [i for i in ordem[:limite] if pontos[i] > 0]

    def busca_hibrida(self, consulta: str, limite: int | None = None) -> list[dict]:
        """Funde busca densa e BM25 por Reciprocal Rank Fusion; reranker opcional."""
        limite = limite or config.RAG_LIMIT
        if not self.chunks:
            return []
        candidatos = max(limite * 4, 20)
        fusao: dict[int, float] = {}
        for ranking in (
            self._ranking_denso(consulta, candidatos),
            self._ranking_lexical(consulta, candidatos),
        ):
            for posicao, indice in enumerate(ranking):
                fusao[indice] = fusao.get(indice, 0.0) + 1.0 / (60 + posicao)

        ordem = sorted(fusao, key=lambda i: -fusao[i])

        if config.RERANKER_MODEL and ordem:
            from sicai.store.embeddings import reordenar

            ordem = reordenar(consulta, ordem[:candidatos], self.chunks)

        return [self.chunks[i] for i in ordem[:limite]]
