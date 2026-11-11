"""Crews e flows rodando no CrewAI de verdade, com um modelo falso no lugar do Ollama.

Pulado quando o CrewAI não está instalado (requirements-dev.txt não o inclui).
"""

import json

import pytest

pytest.importorskip("crewai")

from crewai import BaseLLM  # noqa: E402

from sicai import config  # noqa: E402
from sicai.crews import llm as base  # noqa: E402
from sicai.extraction import resolver  # noqa: E402
from sicai.store.case_db import CaseDB  # noqa: E402
from sicai.store.vector_store import VectorStore  # noqa: E402

P = "proc-crew"
FONTE = {"documento": "Auto 31-2021", "pagina": 2}


class LLMFalso(BaseLLM):
    """Devolve respostas prontas, na ordem, e guarda os prompts recebidos."""

    def __init__(self, respostas):
        super().__init__(model="falso")
        self.respostas = list(respostas)
        self.prompts = []

    def call(self, messages, *args, **kwargs):
        if isinstance(messages, str):
            self.prompts.append(messages)
        else:
            self.prompts.append("\n".join(str(m.get("content", "")) for m in messages))
        return "Thought: tenho a resposta.\nFinal Answer: " + self.respostas.pop(0)

    def supports_function_calling(self) -> bool:
        return False


@pytest.fixture
def llm(monkeypatch):
    def instalar(*respostas):
        falso = LLMFalso(respostas)
        monkeypatch.setattr(base, "criar_llm", lambda temperatura=0.2: falso)
        return falso

    return instalar


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    VectorStore.invalidar(P)
    banco = CaseDB(":memory:")
    resolver.integrar_equipamento(banco, P, {
        "tipo": "Telefone", "subtipo": "Celular", "quantidade": "1", "unidade": "UN",
        "marca": "Acme", "observacoes": "", "lacre": "ABC12345", "identificadores": [],
        "pessoa_relacionada": "Beltrano Souza", "fontes": [FONTE],
    })
    from sicai.flows import chat_flow

    monkeypatch.setattr(chat_flow, "obter_db", lambda: banco)
    return banco


def test_llm_do_ollama_e_construido_sem_rede():
    base.criar_llm.cache_clear()
    modelo = base.criar_llm()
    assert modelo.model.endswith(config.OLLAMA_MODEL)


def test_crew_de_extracao_roda_um_agente_por_categoria(llm):
    from sicai.crews.extraction_crew.extraction_crew import extrair_da_pagina

    falso = llm(
        json.dumps({"pessoas": [{"nome": "Beltrano Souza", "papel": "investigado"}]}),
        "Segue o resultado: " + json.dumps({"crimes": []}) + " fim.",
    )
    extraido = extrair_da_pagina(
        ["pessoas", "crimes"], "Beltrano Souza, investigado, compareceu.", "Auto 31-2021", 2, "outro"
    )

    assert extraido["pessoas"][0]["nome"] == "Beltrano Souza"
    assert extraido["crimes"] == []
    assert len(falso.prompts) == 2
    # Os campos do kickoff chegam ao prompt de cada agente...
    assert all("Beltrano Souza, investigado, compareceu." in p for p in falso.prompts)
    assert "página 2 do documento 'Auto 31-2021'" in falso.prompts[0]
    # ...e a saída do extrator anterior não vira contexto do seguinte.
    assert '"papel"' not in falso.prompts[1]


def test_chat_responde_com_o_especialista_e_passa_na_verificacao(llm, db):
    from sicai.flows.chat_flow import responder

    falso = llm("Foi apreendido um celular Acme, lacre ABC12345 (Auto 31-2021, p. 2).")
    resultado = responder(P, "Quais equipamentos foram apreendidos?")

    assert resultado["rota"] == "equipamentos"
    assert resultado["response"].startswith("Foi apreendido um celular Acme")
    assert resultado["pendencias"] == [] and resultado["revisada"] is False
    assert resultado["fontes"] == [{"documento": "Auto 31-2021", "pagina": 2}]
    assert len(falso.prompts) == 1
    assert "REGISTROS DE EQUIPAMENTOS" in falso.prompts[0]
    assert "Especialista em equipamentos apreendidos" in falso.prompts[0]


def test_chat_aciona_o_revisor_quando_a_citacao_e_invalida(llm, db):
    from sicai.flows.chat_flow import responder

    falso = llm(
        "Foi apreendido um celular, lacre ABC99999 (Laudo, p. 7).",
        "Foi apreendido um celular, lacre ABC12345 (Auto 31-2021, p. 2).",
    )
    resultado = responder(P, "Quais equipamentos foram apreendidos?")

    assert resultado["revisada"] is True and resultado["pendencias"] == []
    assert "ABC12345" in resultado["response"]
    assert len(falso.prompts) == 2
    assert "PROBLEMAS ENCONTRADOS" in falso.prompts[1] and "ABC99999" in falso.prompts[1]


def test_chat_mantem_o_aviso_se_a_revisao_tambem_falha(llm, db):
    from sicai.flows.chat_flow import responder

    llm("Lacre ABC99999 (Laudo, p. 7).", "Lacre ABC99999 (Laudo, p. 7).")
    resultado = responder(P, "Quais equipamentos foram apreendidos?")

    assert len(resultado["pendencias"]) == 2
    assert "verificação automática não conseguiu confirmar" in resultado["response"]


def test_chat_casual_nao_monta_contexto(llm, db):
    from sicai.flows.chat_flow import responder

    falso = llm("Olá! Posso ajudar com perguntas sobre o processo.")
    resultado = responder(P, "Bom dia!")

    assert resultado["rota"] == "casual"
    assert resultado["fontes"] == []
    assert "REGISTROS" not in falso.prompts[0]


# ------------------------------------------------------------ ingestão e API

AUTO = """AUTO DE EXIBIÇÃO E APREENSÃO
EXIBIDOR(A): Fulano de Tal Silva, RG 1234567
Objetos apreendidos:
- Tipo: Telefone - Subtipo: Celular - Qtde: 1 - Unidade: UN
- Marca: Acme - Observações: IMEI 351234567890123 LACRADO SOB N. ABC12345
Pessoa relacionada: Beltrano Souza Origem: Residência
"""


@pytest.fixture
def ingestao(tmp_path, monkeypatch):
    import numpy as np

    from sicai.flows import ingest_flow
    from sicai.store import embeddings

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    VectorStore.invalidar(P)
    banco = CaseDB(":memory:")
    monkeypatch.setattr(ingest_flow, "obter_db", lambda: banco)
    monkeypatch.setattr(ingest_flow, "baixar_pdf", lambda document_id: b"")
    monkeypatch.setattr(
        ingest_flow, "extrair_paginas", lambda pdf: [{"pagina": 1, "texto": AUTO, "ocr": False}]
    )
    monkeypatch.setattr(
        embeddings, "embutir", lambda textos: np.ones((len(textos), 4), dtype="float32")
    )
    return banco


DOCUMENTOS = [{"document_id": "doc-1", "pdf_name": "Auto 31-2021.pdf"}]


def test_ingestao_por_regras_nao_chama_o_modelo(llm, ingestao):
    from sicai.flows.ingest_flow import executar_ingestao

    falso = llm()
    resumo = executar_ingestao(P, DOCUMENTOS, extrair_com_agentes=False)

    assert falso.prompts == []
    assert resumo["erros"] == []
    assert resumo["documentos"][0]["tipo_peca"] == "auto de apreensão"
    assert resumo["registros"] == {"equipamento": 1, "pessoa": 1}
    assert ingestao.listar(P, "equipamento")[0]["dados"]["lacre"] == "ABC12345"
    assert VectorStore.abrir(P).busca_literal("lacre ABC12345")[0][1] == ["ABC12345"]

    # Reingerir o mesmo documento não duplica nada.
    executar_ingestao(P, DOCUMENTOS, extrair_com_agentes=False)
    assert ingestao.contagem(P) == {"equipamento": 1, "pessoa": 1}
    assert len(VectorStore.abrir(P).chunks) == 1


def test_ingestao_com_agentes_valida_a_saida_contra_a_pagina(llm, ingestao):
    from sicai.flows.ingest_flow import executar_ingestao

    falso = llm(
        json.dumps({"pessoas": [
            {"nome": "Beltrano Souza", "papel": "réu"},
            {"nome": "Pessoa Inventada Lima", "papel": "testemunha"},
        ]}),
        json.dumps({"eventos": []}),
    )
    resumo = executar_ingestao(P, DOCUMENTOS, extrair_com_agentes=True)

    # O regex já cobriu os equipamentos: só pessoas e eventos vão aos agentes.
    assert len(falso.prompts) == 2
    assert resumo["paginas_lidas_por_agentes"] == 1
    nomes = {p["dados"]["nome"]: p["dados"]["papeis"][0]["papel"] for p in ingestao.listar(P, "pessoa")}
    assert nomes == {"Fulano de Tal Silva": "Exibidor(a)", "Beltrano Souza": "mencionado"}


def test_api(llm, db, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from sicai import api

    monkeypatch.setattr(api, "obter_db", lambda: db)
    cliente = TestClient(api.app)

    assert cliente.get("/health").json() == {"status": "ok"}
    assert cliente.post("/api/chat", json={"processo_id": "../x", "message": "oi"}).status_code == 422
    assert cliente.post("/api/chat", json={"processo_id": P, "message": "oi"}).status_code == 404
    assert cliente.get(f"/api/processos/{P}").json()["registros"] == {"equipamento": 1}
    assert len(cliente.get(f"/api/processos/{P}/registros/equipamento").json()) == 1

    monkeypatch.setattr(config, "API_KEY", "segredo")
    assert cliente.get(f"/api/processos/{P}").status_code == 401
    assert cliente.get(f"/api/processos/{P}", headers={"X-API-Key": "segredo"}).status_code == 200


def test_interface_e_envio_de_pdf(llm, ingestao, tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    from sicai import api
    from sicai.flows import ingest_flow

    llm()
    monkeypatch.setattr(api, "obter_db", lambda: ingestao)
    monkeypatch.setattr(config, "DOCS_FOLDER", str(tmp_path / "docs"))
    recebidos = []
    monkeypatch.setattr(ingest_flow, "baixar_pdf", lambda document_id: recebidos.append(document_id) or b"")
    cliente = TestClient(api.app)

    pagina = cliente.get("/")
    assert pagina.status_code == 200 and "<title>SICAI</title>" in pagina.text
    assert cliente.get("/api/info").json()["exige_chave"] is False

    rota = f"/api/processos/{P}/documentos"
    pdf = ("../../Auto 31-2021.pdf", b"%PDF-1.4 falso", "application/pdf")
    envio = cliente.post(rota, files={"arquivos": pdf}, data={"extrair_com_agentes": "false"})

    assert envio.status_code == 202 and envio.json()["documentos"] == ["Auto 31-2021.pdf"]
    # O nome malicioso não sai da pasta do processo.
    assert [a.name for a in (tmp_path / "docs").rglob("*.pdf")] == ["Auto 31-2021.pdf"]
    assert (tmp_path / "docs" / P / "Auto 31-2021.pdf").is_file()
    assert recebidos == [f"{P}/Auto 31-2021.pdf"]
    # O TestClient roda a tarefa em segundo plano antes de devolver a resposta.
    assert cliente.get(f"/api/ingest/{envio.json()['job_id']}").json()["status"] == "concluída"
    assert cliente.get("/api/processos").json() == [
        {"processo_id": P, "documentos": 1, "paginas": 1}
    ]

    nao_pdf = ("x.pdf", b"texto", "application/pdf")
    assert cliente.post(rota, files={"arquivos": nao_pdf}).status_code == 422
