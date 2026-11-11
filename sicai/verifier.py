"""Verificador de citações em código.

Confere a resposta do especialista contra o contexto que ele recebeu:
  1. toda citação (Documento, p. N) precisa existir entre as fontes do contexto;
  2. todo código (lacre, IMEI, série) precisa aparecer literalmente no contexto;
  3. resposta factual longa sem nenhuma citação é reprovada.
Não julga se a afirmação decorre da fonte, só se a fonte e os códigos existem.
"""

import re

from sicai.text import contem_literal, extrair_identificadores, normalizar

_RE_CITACAO = re.compile(
    r"([^|;\n]{3,200}?),\s*(?:p[áa]gs?\.?|p[áa]ginas?|pp?\.)\s*(\d+)",
    flags=re.IGNORECASE,
)
_SEM_RESPOSTA = ("nao encontrado", "nao foi encontrad", "nao consta", "nao informado")


def extrair_citacoes(resposta: str) -> list[tuple[str, int]]:
    """Pares (trecho antes de ", p. N", N).

    O trecho pode trazer palavras da frase antes do nome do documento; a
    comparação em `_mesmo_documento` tolera isso.
    """
    citacoes = []
    for documento, pagina in _RE_CITACAO.findall(resposta or ""):
        item = (documento.strip(" *_`()"), int(pagina))
        if item not in citacoes:
            citacoes.append(item)
    return citacoes


def _nome_citado(trecho: str) -> str:
    """Parte após o último parêntese aberto: em '... (Laudo X' é 'Laudo X'."""
    cauda = trecho.rsplit("(", 1)[-1].strip()
    return cauda if len(cauda) >= 3 and ")" not in cauda else trecho


def _mesmo_documento(citado: str, permitido: str) -> bool:
    """O modelo costuma abreviar o nome ou colar palavras antes dele."""
    permitido = normalizar(permitido)
    if permitido and permitido in normalizar(citado):
        return True
    citado = normalizar(_nome_citado(citado))
    if not citado or not permitido:
        return False
    if permitido in citado or citado in permitido:
        return True
    tokens_permitido = set(re.findall(r"\w+", permitido))
    tokens_citado = set(re.findall(r"\w+", citado))
    if not tokens_permitido:
        return False
    return len(tokens_permitido & tokens_citado) / len(tokens_permitido) >= 0.6


def verificar(
    resposta: str,
    contexto: str,
    fontes: list[tuple[str, int]],
    pergunta: str = "",
) -> list[str]:
    """Lista de problemas; vazia quando a resposta passa."""
    problemas = []
    citacoes = extrair_citacoes(resposta)

    for documento, pagina in citacoes:
        valida = any(
            pagina == pagina_permitida and _mesmo_documento(documento, doc_permitido)
            for doc_permitido, pagina_permitida in fontes
        )
        if not valida:
            problemas.append(
                f"A citação '{_nome_citado(documento)}, p. {pagina}' não corresponde a nenhuma "
                "fonte do contexto."
            )

    base = contexto + "\n" + pergunta
    for codigo in extrair_identificadores(resposta):
        if not contem_literal(codigo, base):
            problemas.append(
                f"O código '{codigo}' aparece na resposta, mas não no contexto."
            )

    texto = normalizar(resposta)
    sem_resposta = any(marca in texto for marca in _SEM_RESPOSTA)
    if not citacoes and len(resposta) > 200 and not sem_resposta:
        problemas.append("A resposta traz afirmações factuais sem citar documento e página.")

    return problemas
