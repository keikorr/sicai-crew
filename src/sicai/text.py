"""Funções de texto sem dependências, usadas por todos os módulos."""

import re
import unicodedata

# Lacres, IMEIs, placas e códigos: algo com letra+dígito, ou 5+ dígitos seguidos.
_RE_IDENTIFICADOR = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9-]*\d[A-Za-z0-9-]*|\d{5,})(?![A-Za-z0-9])"
)


def normalizar(texto: str) -> str:
    """Sem acentos, minúsculo e com espaços colapsados."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acentos.casefold().split())


def nome_curto(documento: str) -> str:
    """Nome do arquivo sem pasta e sem extensão .pdf."""
    nome = (documento or "").replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return re.sub(r"\.pdf$", "", nome, flags=re.IGNORECASE)


def extrair_identificadores(texto: str) -> list[str]:
    """Códigos que não podem depender só de busca semântica (mín. 6 caracteres)."""
    encontrados = _RE_IDENTIFICADOR.findall(texto or "")
    return list(dict.fromkeys(item for item in encontrados if len(item) >= 6))


def contem_literal(identificador: str, texto: str) -> bool:
    """Verifica o identificador como palavra inteira, sem diferenciar caixa."""
    padrao = rf"(?<![A-Za-z0-9]){re.escape(identificador)}(?![A-Za-z0-9])"
    return re.search(padrao, texto or "", flags=re.IGNORECASE) is not None


def dividir(texto: str, tamanho: int = 1800, sobreposicao: int = 200) -> list[str]:
    """Corta o texto em blocos com sobreposição."""
    if tamanho <= sobreposicao:
        raise ValueError("tamanho deve ser maior que a sobreposição")
    blocos = []
    inicio = 0
    while inicio < len(texto):
        blocos.append(texto[inicio:inicio + tamanho])
        inicio += tamanho - sobreposicao
    return blocos


def limpar_valor(valor: str) -> str:
    """Remove quebras e separadores usados só na diagramação do documento."""
    return re.sub(r"\s+", " ", valor or "").strip(" -:\n\t")


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def truncar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite].rstrip() + "\n[... contexto truncado ...]"
