"""Base estruturada, resolução de entidades, contexto, inconsistências e verificador."""

import numpy as np
import pytest

from sicai import config, context, verifier
from sicai.analysis import inconsistencias
from sicai.extraction import resolver
from sicai.store.case_db import CaseDB
from sicai.store.vector_store import VectorStore

P = "proc-teste"
F1 = {"documento": "Denúncia", "pagina": 2}
F2 = {"documento": "Relatório Final", "pagina": 40}


@pytest.fixture
def db():
    return CaseDB(":memory:")


@pytest.fixture(autouse=True)
def pasta_de_dados(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    VectorStore.invalidar(P)
    VectorStore.invalidar(config.PROCESSO_NORMAS)


def _pessoa(nome, papel, cpf=""):
    return {"nome": nome, "cpf": cpf, "papel": papel, "contexto": ""}


def _equipamento(tipo, lacre, fonte, quantidade="1", identificadores=()):
    return {
        "tipo": tipo, "subtipo": "", "quantidade": quantidade, "unidade": "", "marca": "",
        "observacoes": "", "lacre": lacre, "identificadores": list(identificadores),
        "pessoa_relacionada": "", "fontes": [fonte],
    }


# ---------------------------------------------------------- base e resolver

def test_mesma_pessoa_em_duas_pecas_vira_um_registro(db):
    resolver.integrar_pessoa(
        db, P, _pessoa("Willian de Souza Prado", "investigado", "11111111111"), F2
    )
    resolver.integrar_pessoa(db, P, _pessoa("Willians de Sousa Prado", "réu", "11111111111"), F1)

    pessoas = db.listar(P, "pessoa")
    assert len(pessoas) == 1
    dados = pessoas[0]["dados"]
    assert dados["variacoes"] == ["Willians de Sousa Prado"]
    assert dados["cpf"] == "11111111111"
    assert [p["papel"] for p in dados["papeis"]] == ["investigado", "réu"]
    assert pessoas[0]["fontes"] == [F2, F1]


def test_nomes_apenas_parecidos_ficam_separados(db):
    resolver.integrar_pessoa(db, P, _pessoa("Marcos Antônio Ferreira", "réu"), F1)
    resolver.integrar_pessoa(db, P, _pessoa("Marcos Antônio Pereira", "testemunha"), F2)
    assert len(db.listar(P, "pessoa")) == 2


def test_processos_nao_se_misturam(db):
    resolver.integrar_pessoa(db, P, _pessoa("Ana Clara Mendes", "vítima"), F1)
    assert db.listar("outro-processo", "pessoa") == []


def test_reingestao_remove_o_que_so_o_documento_sustentava(db):
    resolver.integrar_pessoa(db, P, _pessoa("Ana Clara Mendes", "vítima"), F1)
    resolver.integrar_pessoa(db, P, _pessoa("Ana Clara Mendes", "testemunha"), F2)
    resolver.integrar_evento(
        db, P,
        {"tipo_evento": "apreensão", "data": "05/03/2021", "item": "", "responsavel": "",
         "descricao": ""},
        F1,
    )

    db.remover_fontes_do_documento(P, "Denúncia")

    assert db.listar(P, "evento") == []
    pessoa = db.listar(P, "pessoa")[0]
    assert pessoa["fontes"] == [F2]
    assert [p["papel"] for p in pessoa["dados"]["papeis"]] == ["testemunha"]


def test_equipamento_repetido_une_fontes(db):
    resolver.integrar_equipamento(db, P, _equipamento("Celular", "ABC12345", F1))
    resolver.integrar_equipamento(db, P, _equipamento("Celular", "ABC12345", F2))
    itens = db.listar(P, "equipamento")
    assert len(itens) == 1
    assert itens[0]["fontes"] == [F1, F2]
    assert db.contagem(P) == {"equipamento": 1}


# ----------------------------------------------------------- inconsistências

def test_divergencias_detectadas(db):
    resolver.integrar_equipamento(db, P, _equipamento("Celular", "ABC12345", F1, "1"))
    resolver.integrar_equipamento(db, P, _equipamento("Tablet", "ABC12345", F2, "2"))
    resolver.integrar_pessoa(db, P, _pessoa("Marcos Antônio Ferreira", "réu"), F1)
    resolver.integrar_pessoa(db, P, _pessoa("Marcos Antônio Pereira", "testemunha"), F2)
    resolver.integrar_pessoa(db, P, _pessoa("Ana Clara Mendes", "vítima"), F1)
    resolver.integrar_pessoa(db, P, _pessoa("Ana Clara Mendes", "testemunha"), F2)

    achados = inconsistencias.detectar(db.listar(P, "pessoa"), db.listar(P, "equipamento"))

    assert len(achados) == 3
    assert "ABC12345" in achados[0] and "Tablet" in achados[0]
    assert any("Identificação incerta" in a for a in achados)
    assert any("papéis diferentes" in a and "Ana Clara Mendes" in a for a in achados)


def test_sem_divergencias(db):
    resolver.integrar_equipamento(db, P, _equipamento("Celular", "ABC12345", F1))
    assert inconsistencias.detectar([], db.listar(P, "equipamento")) == []


# ------------------------------------------------------------------ contexto

def test_contexto_de_equipamentos_filtra_por_identificador(db):
    resolver.integrar_equipamento(db, P, _equipamento("Celular", "ABC12345", F1))
    resolver.integrar_equipamento(db, P, _equipamento("Notebook", "XYZ98765", F2))

    todos = context.montar("equipamentos", P, "Quais itens foram apreendidos?", "", db)
    assert "Total de registros na base: 2. Exibidos abaixo: 2." in todos.texto
    assert set(todos.fontes) == {("Denúncia", 2), ("Relatório Final", 40)}

    um = context.montar("identificador", P, "O que é o lacre XYZ98765?", "", db)
    assert "Notebook" in um.texto and "Celular" not in um.texto
    assert um.fontes == [("Relatório Final", 40)]


def test_contexto_avisa_quando_a_lista_nao_cabe(db, monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_CHARS", 900)
    for n in range(12):
        resolver.integrar_equipamento(db, P, _equipamento(f"Celular {n}", f"LAC{n:05d}", F1))
    montado = context.montar("equipamentos", P, "Liste os itens apreendidos", "", db)
    assert "Total de registros na base: 12." in montado.texto
    assert "INCOMPLETA" in montado.texto


def test_contexto_de_inconsistencias_sem_achados(db):
    montado = context.montar("inconsistencias", P, "Há divergências?", "Há divergências?", db)
    assert "não encontrou divergências" in montado.texto


# -------------------------------------------------------------- índice vetorial

def test_substituir_documento_preserva_os_demais():
    store = VectorStore(P)
    a = [{"document_id": "a", "documento": "A", "pagina": 1, "chunk_id": 0, "content": "lacre ABC12345"}]
    b = [{"document_id": "b", "documento": "B", "pagina": 1, "chunk_id": 0, "content": "outro texto"}]
    store.substituir_documento("a", a, np.ones((1, 4), dtype="float32"))
    store.substituir_documento("b", b, np.zeros((1, 4), dtype="float32"))
    novo_a = [{**a[0], "content": "lacre ZZZ99999"}, {**a[0], "chunk_id": 1, "content": "mais"}]
    store.substituir_documento("a", novo_a, np.ones((2, 4), dtype="float32"))
    store.salvar()

    reaberto = VectorStore(P)
    assert [c["document_id"] for c in reaberto.chunks] == ["b", "a", "a"]
    assert reaberto.vetores.shape == (3, 4)
    assert reaberto.vetores[0].sum() == 0
    assert reaberto.busca_literal("lacre ABC12345") == []
    assert reaberto.busca_literal("e o ZZZ99999?") == [(1, ["ZZZ99999"])]


# ---------------------------------------------------------------- verificador

CONTEXTO = (
    "Documento: Boletins 31-2021 e 32-2021 - AUTOS DE APREENSÃO\nPágina: 2\n\n"
    "Celular lacre ABC12345."
)
FONTES = [("Boletins 31-2021 e 32-2021 - AUTOS DE APREENSÃO", 2), ("Laudo (6)", 4)]


def test_resposta_correta_passa():
    resposta = (
        "Foi apreendido um celular com lacre ABC12345 "
        "(Boletins 31-2021 e 32-2021 - AUTOS DE APREENSÃO, p. 2)."
    )
    assert verifier.verificar(resposta, CONTEXTO, FONTES) == []


def test_nome_abreviado_e_nome_com_parenteses_passam():
    assert verifier.verificar("Consta um celular (Boletins 31-2021 e 32-2021, p. 2).", CONTEXTO, FONTES) == []
    assert verifier.verificar("Consta no laudo (Laudo (6), p. 4).", CONTEXTO, FONTES) == []
    assert verifier.verificar("| Celular | Laudo (6), pág. 4 |", CONTEXTO, FONTES) == []


def test_pagina_ou_documento_inexistente_reprova():
    problemas = verifier.verificar(
        "Há um celular (Boletins 31-2021 e 32-2021, p. 7) e um tablet (Denúncia, p. 2).",
        CONTEXTO, FONTES,
    )
    assert len(problemas) == 2
    assert "p. 7" in problemas[0] and "Denúncia" in problemas[1]


def test_codigo_inventado_reprova():
    problemas = verifier.verificar(
        "O celular tem lacre ABC12399 (Boletins 31-2021 e 32-2021, p. 2).", CONTEXTO, FONTES
    )
    assert problemas == ["O código 'ABC12399' aparece na resposta, mas não no contexto."]


def test_resposta_longa_sem_citacao_reprova_mas_nao_encontrado_passa():
    longa = "O réu foi preso em flagrante na residência e levado à delegacia. " * 5
    assert verifier.verificar(longa, CONTEXTO, FONTES) == [
        "A resposta traz afirmações factuais sem citar documento e página."
    ]
    assert verifier.verificar("Não encontrado nos documentos disponíveis.", CONTEXTO, FONTES) == []
