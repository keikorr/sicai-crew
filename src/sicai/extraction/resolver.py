"""Grava registros validados na base, unindo menções do mesmo ente.

Pessoas com grafia parecida mas não idêntica NÃO são unidas: ficam como
registros separados e a análise de inconsistências as aponta como
"identificação incerta".
"""

from sicai.extraction.inventory_regex import chave_equipamento
from sicai.extraction.validation import mesma_pessoa
from sicai.store.case_db import CaseDB
from sicai.text import normalizar


def _chave_pessoa(dados: dict) -> str:
    return dados["cpf"] or normalizar(dados["nome"])


def integrar_pessoa(db: CaseDB, processo_id: str, pessoa: dict, fonte: dict) -> None:
    papel = {
        "papel": pessoa["papel"],
        "documento": fonte["documento"],
        "pagina": fonte["pagina"],
    }

    for existente in db.listar(processo_id, "pessoa"):
        dados = existente["dados"]
        if not mesma_pessoa(dados, pessoa):
            continue
        if pessoa["nome"] != dados["nome"] and pessoa["nome"] not in dados["variacoes"]:
            dados["variacoes"].append(pessoa["nome"])
        dados["cpf"] = dados["cpf"] or pessoa["cpf"]
        if papel not in dados["papeis"]:
            dados["papeis"].append(papel)
        if pessoa["contexto"] and pessoa["contexto"] not in dados["contextos"]:
            dados["contextos"].append(pessoa["contexto"])
        db.atualizar(
            existente["id"], _chave_pessoa(dados), dados, existente["fontes"] + [fonte]
        )
        return

    dados = {
        "nome": pessoa["nome"],
        "variacoes": [],
        "cpf": pessoa["cpf"],
        "papeis": [papel],
        "contextos": [pessoa["contexto"]] if pessoa["contexto"] else [],
    }
    db.gravar(processo_id, "pessoa", _chave_pessoa(dados), dados, [fonte])


def integrar_crime(db: CaseDB, processo_id: str, crime: dict, fonte: dict) -> None:
    autores = sorted(normalizar(autor) for autor in crime["autores"])
    chave = "|".join(
        [normalizar(crime["descricao"]), normalizar(crime["artigo"]), crime["status"], *autores]
    )
    db.gravar(processo_id, "crime", chave, crime, [fonte])


def integrar_equipamento(db: CaseDB, processo_id: str, equipamento: dict) -> None:
    """`equipamento` já traz a lista "fontes" (o regex pode citar duas páginas)."""
    dados = {k: v for k, v in equipamento.items() if k != "fontes"}
    chave = chave_equipamento(dados) + "|" + "|".join(
        sorted(normalizar(i) for i in dados.get("identificadores", []))
    )
    db.gravar(processo_id, "equipamento", chave, dados, equipamento["fontes"])


def integrar_evento(db: CaseDB, processo_id: str, evento: dict, fonte: dict) -> None:
    campos = ("tipo_evento", "data", "item", "responsavel")
    chave = "|".join(normalizar(evento[campo]) for campo in campos)
    db.gravar(processo_id, "evento", chave, evento, [fonte])
