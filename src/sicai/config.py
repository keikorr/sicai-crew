"""Configuração lida do ambiente. Nenhum outro módulo chama os.getenv."""

import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv é opcional (testes rodam sem ele)
    pass


def _bool(nome: str, padrao: str) -> bool:
    return os.getenv(nome, padrao).strip().lower() in ("1", "true", "yes", "sim")


# --- Armazenamento -----------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
# Pasta local com PDFs. Se o document_id existir aqui, o Garage não é consultado.
DOCS_FOLDER = os.getenv("DOCS_FOLDER", "processo_RAG")

# --- Garage (S3 compatível) --------------------------------------------------
GARAGE_ENDPOINT = os.getenv("GARAGE_ENDPOINT", "")
GARAGE_REGION = os.getenv("GARAGE_REGION", "garage")
GARAGE_ACCESS_KEY = os.getenv("GARAGE_ACCESS_KEY", "")
GARAGE_SECRET_KEY = os.getenv("GARAGE_SECRET_KEY", "")
GARAGE_BUCKET = os.getenv("GARAGE_BUCKET", "")

# --- Modelo de linguagem -----------------------------------------------------
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "1600"))
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))
# qwen3 aceita "/no_think" no prompt para pular o raciocínio separado.
OLLAMA_NO_THINK = _bool("OLLAMA_NO_THINK", "true")
CREW_VERBOSE = _bool("CREW_VERBOSE", "false")

# --- Recuperação -------------------------------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "")  # ex.: BAAI/bge-reranker-v2-m3
RAG_LIMIT = int(os.getenv("RAG_LIMIT", "5"))
# Orçamento de caracteres do contexto enviado ao modelo (~4 caracteres por token).
CONTEXT_CHARS = int(os.getenv("CONTEXT_CHARS", "14000"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# --- Ingestão ----------------------------------------------------------------
OCR_ENABLED = _bool("OCR_ENABLED", "false")
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "por")
# Liga os agentes extratores (pessoas, crimes, equipamentos, eventos).
EXTRACAO_LLM = _bool("EXTRACAO_LLM", "true")
EXTRACAO_MAX_CHARS = int(os.getenv("EXTRACAO_MAX_CHARS", "6000"))

# --- API ---------------------------------------------------------------------
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
API_KEY = os.getenv("API_KEY", "")  # vazio = sem autenticação (só para desenvolvimento)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))

# Índice separado com legislação e protocolos, usado pela rota de conformidade.
PROCESSO_NORMAS = "_normas"

_RE_PROCESSO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")


def validar_processo_id(processo_id: str) -> str:
    """O identificador vira nome de pasta, então não pode sair de DATA_DIR."""
    if not _RE_PROCESSO.match(processo_id or "") or ".." in processo_id:
        raise ValueError(
            "processo_id inválido: use até 64 letras, números, '.', '_' ou '-'."
        )
    return processo_id
