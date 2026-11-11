"""Acompanhamento das ingestões em andamento (em memória, some ao reiniciar)."""

import threading
import uuid

_trava = threading.Lock()
_jobs: dict[str, dict] = {}


def criar(processo_id: str) -> str:
    job_id = uuid.uuid4().hex
    with _trava:
        _jobs[job_id] = {
            "job_id": job_id,
            "processo_id": processo_id,
            "status": "na fila",
            "etapa": "",
            "resumo": {},
            "erro": "",
        }
    return job_id


def atualizar(job_id: str, **campos) -> None:
    if not job_id:
        return
    with _trava:
        if job_id in _jobs:
            _jobs[job_id].update(campos)


def obter(job_id: str) -> dict | None:
    with _trava:
        job = _jobs.get(job_id)
        return dict(job) if job else None
