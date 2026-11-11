"""Validação literal do que os agentes extraem.

Princípio herdado da branch `reus`: nada entra na base se não estiver escrito
na página. O modelo propõe; este módulo confere contra o texto e descarta ou
esvazia o que não encontrar.
"""

import re
from difflib import SequenceMatcher

from sicai.text import contem_literal, limpar_valor, normalizar, so_digitos

STATUS_CRIME = ("acusacao", "indicio", "decisao")
# Nomes diferentes com similaridade a partir daqui são "identificação incerta".
LIMIAR_IDENTIFICACAO_INCERTA = 0.80


def _presente(valor: str, pagina_normalizada: str) -> bool:
    valor = normalizar(valor)
    return bool(valor) and valor in pagina_normalizada


def _numeros_presentes(valor: str, texto: str) -> bool:
    """Todo número citado pelo modelo precisa existir na página."""
    # Número inteiro, não pedaço: "35" não vale por estar dentro de um IMEI.
    return all(
        re.search(rf"(?<!\d){numero}(?!\d)", texto)
        for numero in re.findall(r"\d+", valor or "")
    )


def _papel_presente(papel: str, pagina_normalizada: str) -> bool:
    """O papel vale se o radical estiver na página: "denunciado" casa com
    "denuncia Fulano"; "réu" só como palavra inteira (não casa com "reunião")."""
    papel = normalizar(papel)
    if not papel:
        return False
    if len(papel) <= 4:
        return re.search(rf"\b{re.escape(papel)}s?\b", pagina_normalizada) is not None
    return re.search(rf"\b{re.escape(papel[:6])}", pagina_normalizada) is not None


def validar_pessoa(item: dict, texto: str) -> dict | None:
    pagina = normalizar(texto)
    nome = limpar_valor(item.get("nome", ""))
    # Nome pela metade, ou que não está na página, não entra.
    if len(nome.split()) < 2 or not _presente(nome, pagina):
        return None

    cpf = so_digitos(item.get("cpf", ""))
    if len(cpf) != 11 or cpf not in so_digitos(texto):
        cpf = ""

    papel = limpar_valor(item.get("papel", ""))
    if not _papel_presente(papel, pagina):
        papel = "mencionado"

    contexto = limpar_valor(item.get("contexto", ""))
    if not _numeros_presentes(contexto, texto):
        contexto = ""

    return {"nome": nome, "cpf": cpf, "papel": papel, "contexto": contexto}


def validar_crime(item: dict, texto: str) -> dict | None:
    pagina = normalizar(texto)
    descricao = limpar_valor(item.get("descricao", ""))
    if not descricao:
        return None

    artigo = limpar_valor(item.get("artigo", ""))
    # Artigo ou lei com número que não está na página é chute.
    if not _numeros_presentes(artigo, texto):
        artigo = ""
    if not _numeros_presentes(descricao, texto):
        return None

    autores = [
        limpar_valor(autor)
        for autor in item.get("autores", [])
        if _presente(autor, pagina)
    ]

    status = normalizar(item.get("status", ""))
    status = next((s for s in STATUS_CRIME if s in status), "não informado")
    rotulos = {"acusacao": "acusação", "indicio": "indício", "decisao": "decisão"}

    return {
        "descricao": descricao,
        "artigo": artigo,
        "autores": autores,
        "status": rotulos.get(status, status),
    }


def validar_equipamento(item: dict, texto: str) -> dict | None:
    pagina = normalizar(texto)
    tipo = limpar_valor(item.get("tipo", ""))
    if not tipo or not _presente(tipo, pagina):
        return None

    def literal(valor: str) -> str:
        valor = limpar_valor(valor)
        return valor if _presente(valor, pagina) else ""

    identificadores = [
        limpar_valor(i)
        for i in item.get("identificadores", [])
        if limpar_valor(i) and contem_literal(limpar_valor(i), texto)
    ]
    lacre = limpar_valor(item.get("lacre", ""))
    if not lacre or not contem_literal(lacre, texto):
        lacre = ""

    quantidade = limpar_valor(item.get("quantidade", ""))
    if not _numeros_presentes(quantidade, texto):
        quantidade = ""

    return {
        "tipo": tipo,
        "subtipo": literal(item.get("subtipo", "")),
        "quantidade": quantidade,
        "unidade": "",
        "marca": literal(item.get("marca", "")),
        "observacoes": literal(item.get("observacoes", "")),
        "lacre": lacre,
        "identificadores": identificadores,
        "pessoa_relacionada": literal(item.get("pessoa_relacionada", "")),
    }


def validar_evento(item: dict, texto: str) -> dict | None:
    pagina = normalizar(texto)
    tipo = limpar_valor(item.get("tipo_evento", ""))
    if not tipo:
        return None

    data = limpar_valor(item.get("data", ""))
    if not data or not _numeros_presentes(data, texto):
        data = ""

    def literal(valor: str) -> str:
        valor = limpar_valor(valor)
        return valor if _presente(valor, pagina) else ""

    descricao = limpar_valor(item.get("descricao", ""))
    if not _numeros_presentes(descricao, texto):
        descricao = ""

    item_ref = limpar_valor(item.get("item", ""))
    if not _numeros_presentes(item_ref, texto):
        item_ref = ""

    # Evento sem data, item nem responsável não ajuda a montar a linha do tempo.
    responsavel = literal(item.get("responsavel", ""))
    if not (data or item_ref or responsavel):
        return None

    return {
        "tipo_evento": tipo,
        "data": data,
        "item": item_ref,
        "responsavel": responsavel,
        "descricao": descricao,
    }


def similaridade_nomes(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def mesma_pessoa(a: dict, b: dict) -> bool:
    """CPF decide quando os dois têm; senão, só nome idêntico (sem acento e caixa).

    A branch `reus` unia nomes com similaridade acima de 0,92, mas esse limiar
    também une sobrenomes diferentes ("Ferreira" e "Pereira" dão 0,96). Grafias
    parecidas ficam separadas e são apontadas como "identificação incerta".
    """
    if a.get("cpf") and b.get("cpf"):
        return a["cpf"] == b["cpf"]
    return normalizar(a["nome"]) == normalizar(b["nome"])
