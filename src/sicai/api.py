"""API HTTP. Mantém /api/chat e /api/ingest do serviço original, agora por processo."""

import re
import secrets
import traceback
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sicai import config, jobs
from sicai.store.case_db import CATEGORIAS, obter_db
from sicai.store.vector_store import VectorStore

app = FastAPI(title="SICAI - assistente multiagente")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def autenticar(x_api_key: str = Header(default="")) -> None:
    """Com API_KEY definida, toda rota /api exige o cabeçalho X-API-Key."""
    if config.API_KEY and not secrets.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Chave de API inválida.")


def _processo(processo_id: str) -> str:
    try:
        return config.validar_processo_id(processo_id)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))


class MessageHistory(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    processo_id: str
    message: str = Field(min_length=1, max_length=4000)
    history: list[MessageHistory] = Field(default_factory=list)


class DocumentInput(BaseModel):
    document_id: str
    pdf_name: str


class IngestRequest(BaseModel):
    processo_id: str
    documents: list[DocumentInput] = Field(min_length=1)
    # False indexa e roda só os extratores por regras (rápido, sem modelo).
    extrair_com_agentes: bool = True


@app.post("/api/chat", dependencies=[Depends(autenticar)])
def chat(request: ChatRequest):
    processo_id = _processo(request.processo_id)
    if not VectorStore.abrir(processo_id).existe():
        raise HTTPException(status_code=404, detail="Processo sem documentos ingeridos.")

    from sicai.flows.chat_flow import responder

    try:
        resultado = responder(
            processo_id, request.message, [m.model_dump() for m in request.history]
        )
    except Exception:
        # O detalhe fica no log do servidor; o cliente não recebe o erro interno.
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Falha ao gerar a resposta.")

    return {"success": True, **resultado}


@app.post("/api/ingest", status_code=202, dependencies=[Depends(autenticar)])
def ingest(request: IngestRequest, tarefas: BackgroundTasks):
    processo_id = _processo(request.processo_id)
    job_id = jobs.criar(processo_id)
    tarefas.add_task(
        _ingerir,
        processo_id,
        [d.model_dump() for d in request.documents],
        request.extrair_com_agentes,
        job_id,
    )
    return {"success": True, "job_id": job_id, "message": "Ingestão iniciada."}


def _ingerir(processo_id, documentos, extrair_com_agentes, job_id) -> None:
    from sicai.flows.ingest_flow import executar_ingestao

    try:
        executar_ingestao(processo_id, documentos, extrair_com_agentes, job_id)
    except Exception:
        traceback.print_exc()


@app.post(
    "/api/processos/{processo_id}/documentos",
    status_code=202,
    dependencies=[Depends(autenticar)],
)
def enviar_documentos(
    processo_id: str,
    tarefas: BackgroundTasks,
    arquivos: list[UploadFile] = File(...),
    extrair_com_agentes: bool = Form(True),
):
    """Recebe PDFs pela interface, grava em DOCS_FOLDER/<processo> e inicia a ingestão."""
    processo_id = _processo(processo_id)
    pasta = Path(config.DOCS_FOLDER) / processo_id
    limite = config.MAX_UPLOAD_MB * 1024 * 1024
    documentos = []

    for arquivo in arquivos:
        # O nome vem do navegador: fica só o nome-base, sem caracteres de caminho.
        nome = re.sub(r"[^\w .()\-]", "_", Path(arquivo.filename or "").name).strip()
        conteudo = arquivo.file.read(limite + 1)
        if not nome.lower().endswith(".pdf") or not conteudo.startswith(b"%PDF"):
            raise HTTPException(status_code=422, detail=f"'{nome}' não é um PDF.")
        if len(conteudo) > limite:
            raise HTTPException(
                status_code=413, detail=f"'{nome}' passa de {config.MAX_UPLOAD_MB} MB."
            )
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / nome).write_bytes(conteudo)
        documentos.append({"document_id": f"{processo_id}/{nome}", "pdf_name": nome})

    job_id = jobs.criar(processo_id)
    tarefas.add_task(_ingerir, processo_id, documentos, extrair_com_agentes, job_id)
    return {"success": True, "job_id": job_id, "documentos": [d["pdf_name"] for d in documentos]}


@app.get("/api/info")
def info():
    """Dados que a interface precisa antes de autenticar."""
    return {
        "exige_chave": bool(config.API_KEY),
        "modelo": config.OLLAMA_MODEL,
        "extracao_com_agentes": config.EXTRACAO_LLM,
    }


@app.get("/api/processos", dependencies=[Depends(autenticar)])
def processos():
    return obter_db().listar_processos()


@app.get("/api/ingest/{job_id}", dependencies=[Depends(autenticar)])
def situacao_da_ingestao(job_id: str):
    job = jobs.obter(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestão não encontrada.")
    return job


@app.get("/api/processos/{processo_id}", dependencies=[Depends(autenticar)])
def resumo_do_processo(processo_id: str):
    processo_id = _processo(processo_id)
    db = obter_db()
    return {
        "processo_id": processo_id,
        "documentos": db.listar_documentos(processo_id),
        "registros": db.contagem(processo_id),
    }


@app.get("/api/processos/{processo_id}/registros/{categoria}", dependencies=[Depends(autenticar)])
def registros(processo_id: str, categoria: str):
    processo_id = _processo(processo_id)
    if categoria not in CATEGORIAS:
        raise HTTPException(status_code=422, detail=f"Categorias: {', '.join(CATEGORIAS)}.")
    return obter_db().listar(processo_id, categoria)


@app.get("/", include_in_schema=False)
def interface():
    return FileResponse(Path(__file__).parent / "web" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
