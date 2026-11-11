"""Monta, em código, o contexto que o especialista de cada rota recebe.

Devolve o texto do contexto e a lista de fontes (documento, página) presentes
nele, que o verificador usa para conferir as citações da resposta.
"""

import re
from dataclasses import dataclass, field

from sicai import config
from sicai.analysis import inconsistencias
from sicai.store.case_db import CaseDB
from sicai.store.vector_store import VectorStore
from sicai.text import extrair_identificadores, normalizar

_PAPEIS_DE_CUSTODIA = ("exibidor", "delegado", "perito", "policial", "escriva")


@dataclass
class Contexto:
    texto: str = ""
    fontes: list[tuple[str, int]] = field(default_factory=list)

    def acrescentar(self, bloco: str, fontes: list[tuple[str, int]]) -> None:
        if not bloco:
            return
        self.texto = f"{self.texto}\n\n---\n\n{bloco}" if self.texto else bloco
        for fonte in fontes:
            if fonte not in self.fontes:
                self.fontes.append(fonte)


# --------------------------------------------------------------- formatação

def _fontes_do_registro(registro: dict) -> list[tuple[str, int]]:
    return [(f["documento"], int(f["pagina"])) for f in registro["fontes"]]


def _texto_fontes(registro: dict) -> str:
    return "; ".join(f"{doc}, p. {pag}" for doc, pag in _fontes_do_registro(registro))


def _formatar_pessoa(dados: dict) -> list[str]:
    papeis = "; ".join(
        f"{p['papel']} ({p['documento']}, p. {p['pagina']})" for p in dados.get("papeis", [])
    )
    return [
        f"Nome: {dados['nome']}",
        f"Variações de grafia: {', '.join(dados.get('variacoes', [])) or 'nenhuma'}",
        f"CPF: {dados.get('cpf') or 'não informado'}",
        f"Papéis conforme cada peça: {papeis or 'não informado'}",
        f"Contexto das menções: {' | '.join(dados.get('contextos', [])[:3]) or 'não informado'}",
    ]


def _formatar_crime(dados: dict) -> list[str]:
    return [
        f"Crime: {dados['descricao']}",
        f"Artigo/lei: {dados.get('artigo') or 'não informado'}",
        f"Autor(es) apontado(s): {', '.join(dados.get('autores', [])) or 'não informado'}",
        f"Status: {dados.get('status') or 'não informado'}",
    ]


def _formatar_equipamento(dados: dict) -> list[str]:
    campos = (
        ("Tipo", "tipo"), ("Subtipo", "subtipo"), ("Quantidade", "quantidade"),
        ("Unidade", "unidade"), ("Marca", "marca"), ("Observações", "observacoes"),
        ("Lacre", "lacre"), ("Pessoa relacionada", "pessoa_relacionada"),
    )
    linhas = [f"{rotulo}: {dados.get(campo) or 'não informado'}" for rotulo, campo in campos]
    linhas.insert(
        6, f"Identificadores: {', '.join(dados.get('identificadores', [])) or 'não informado'}"
    )
    return linhas


def _formatar_evento(dados: dict) -> list[str]:
    return [
        f"Ato: {dados['tipo_evento']}",
        f"Data: {dados.get('data') or 'não informado'}",
        f"Item: {dados.get('item') or 'não informado'}",
        f"Responsável: {dados.get('responsavel') or 'não informado'}",
        f"Descrição: {dados.get('descricao') or 'não informado'}",
    ]


_FORMATADORES = {
    "pessoa": _formatar_pessoa,
    "crime": _formatar_crime,
    "equipamento": _formatar_equipamento,
    "evento": _formatar_evento,
}


def _pesquisavel(registro: dict) -> str:
    def valores(item):
        if isinstance(item, dict):
            for valor in item.values():
                yield from valores(valor)
        elif isinstance(item, list):
            for valor in item:
                yield from valores(valor)
        else:
            yield str(item)

    return normalizar(" ".join(valores(registro["dados"])))


def _por_relevancia(registros: list[dict], pergunta: str) -> list[dict]:
    """Registros que citam termos da pergunta vêm primeiro; a ordem é estável."""
    termos = [t for t in re.findall(r"\w+", normalizar(pergunta)) if len(t) >= 4]
    if not termos:
        return registros

    def pontos(registro: dict) -> int:
        texto = _pesquisavel(registro)
        return sum(1 for termo in termos if termo in texto)

    return sorted(registros, key=lambda r: -pontos(r))


def _bloco_registros(
    titulo: str, categoria: str, registros: list[dict], limite: int
) -> tuple[str, list[tuple[str, int]]]:
    """Formata registros até o limite de caracteres e informa quantos couberam."""
    formatar = _FORMATADORES[categoria]
    partes, fontes, usados = [], [], 0
    for numero, registro in enumerate(registros, start=1):
        linhas = [f"REGISTRO {numero}", *formatar(registro["dados"])]
        linhas.append(f"Fontes: {_texto_fontes(registro)}")
        parte = "\n".join(linhas)
        if usados + len(parte) > limite and partes:
            break
        partes.append(parte)
        usados += len(parte)
        fontes.extend(_fontes_do_registro(registro))

    cabecalho = (
        f"{titulo}\n"
        "Os campos foram extraídos dos autos e conferidos contra o texto. Use-os "
        "como fatos; não complete campos ausentes.\n"
        f"Total de registros na base: {len(registros)}. Exibidos abaixo: {len(partes)}."
    )
    if len(partes) < len(registros):
        cabecalho += (
            " A lista está INCOMPLETA por limite de espaço: avise o usuário de que "
            "há mais registros do que os exibidos."
        )
    return cabecalho + "\n\n" + "\n\n".join(partes), fontes


def _bloco_trechos(titulo: str, chunks: list[dict]) -> tuple[str, list[tuple[str, int]]]:
    if not chunks:
        return "", []
    partes = [
        f"Documento: {c['documento']}\nPágina: {c['pagina']}\n\n{c['content']}" for c in chunks
    ]
    fontes = [(c["documento"], int(c["pagina"])) for c in chunks]
    return titulo + "\n\n" + "\n\n---\n\n".join(partes), fontes


def _trechos_literais(store: VectorStore, pergunta: str, limite: int) -> list[dict]:
    """Trechos com o identificador; cópias idênticas (autos repetidos) entram uma vez."""
    vistos, chunks = set(), []
    for indice, _ in store.busca_literal(pergunta):
        chunk = store.chunks[indice]
        chave = normalizar(chunk["content"])
        if chave in vistos:
            continue
        vistos.add(chave)
        chunks.append(chunk)
    return chunks[:limite]


def _filtrar_por_identificador(registros: list[dict], pergunta: str) -> list[dict]:
    identificadores = [normalizar(i) for i in extrair_identificadores(pergunta)]
    if not identificadores:
        return registros
    return [r for r in registros if all(i in _pesquisavel(r) for i in identificadores)]


def _ordem_cronologica(evento: dict) -> tuple:
    achado = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", evento["dados"].get("data", ""))
    if not achado:
        return (1, 0, 0, 0)
    dia, mes, ano = (int(x) for x in achado.groups())
    return (0, ano + 2000 if ano < 100 else ano, mes, dia)


# ------------------------------------------------------------------- rotas

def montar(rota: str, processo_id: str, pergunta: str, consulta: str, db: CaseDB) -> Contexto:
    """`pergunta` é a mensagem atual; `consulta` inclui a pergunta anterior."""
    store = VectorStore.abrir(processo_id)
    contexto = Contexto()
    orcamento = config.CONTEXT_CHARS

    def trechos_semanticos(titulo="TRECHOS RECUPERADOS", limite=None):
        contexto.acrescentar(*_bloco_trechos(titulo, store.busca_hibrida(consulta, limite)))

    def registros(titulo, categoria, itens, fracao=0.7):
        if itens:
            contexto.acrescentar(
                *_bloco_registros(titulo, categoria, itens, int(orcamento * fracao))
            )

    if rota in ("pessoas", "crimes"):
        categoria = "pessoa" if rota == "pessoas" else "crime"
        titulo = "REGISTROS DE PESSOAS" if rota == "pessoas" else "REGISTROS DE CRIMES"
        registros(titulo, categoria, _por_relevancia(db.listar(processo_id, categoria), pergunta))
        # Complemento narrativo curto; sem registros, a busca responde sozinha.
        trechos_semanticos(limite=3 if contexto.texto else None)

    elif rota in ("equipamentos", "identificador"):
        itens = _filtrar_por_identificador(db.listar(processo_id, "equipamento"), pergunta)
        registros("REGISTROS DE EQUIPAMENTOS", "equipamento", _por_relevancia(itens, pergunta))
        literais = _trechos_literais(store, pergunta, config.RAG_LIMIT)
        contexto.acrescentar(*_bloco_trechos("TRECHOS COM O IDENTIFICADOR", literais))
        # Com identificador localizado, a busca semântica só traria ruído.
        if not contexto.texto:
            trechos_semanticos()

    elif rota in ("custodia", "conformidade"):
        eventos = sorted(db.listar(processo_id, "evento"), key=_ordem_cronologica)
        registros("LINHA DO TEMPO (ATOS REGISTRADOS)", "evento", eventos, fracao=0.4)
        itens = _filtrar_por_identificador(db.listar(processo_id, "equipamento"), pergunta)
        registros("REGISTROS DE EQUIPAMENTOS", "equipamento",
                  _por_relevancia(itens, pergunta), fracao=0.3)
        if rota == "custodia":
            agentes = [
                p for p in db.listar(processo_id, "pessoa")
                if any(
                    termo in normalizar(papel["papel"])
                    for papel in p["dados"].get("papeis", [])
                    for termo in _PAPEIS_DE_CUSTODIA
                )
            ]
            registros("PAPÉIS DOCUMENTAIS", "pessoa", agentes, fracao=0.15)
        else:
            normas = VectorStore.abrir(config.PROCESSO_NORMAS)
            contexto.acrescentar(*_bloco_trechos(
                "TRECHOS NORMATIVOS", normas.busca_hibrida(consulta, 4) if normas.existe() else []
            ))
        if not contexto.texto:
            trechos_semanticos()

    elif rota == "inconsistencias":
        pessoas = db.listar(processo_id, "pessoa")
        equipamentos = db.listar(processo_id, "equipamento")
        achados = inconsistencias.detectar(pessoas, equipamentos)
        if achados:
            fontes = [f for r in pessoas + equipamentos for f in _fontes_do_registro(r)]
            bloco = "DIVERGÊNCIAS DETECTADAS\n\n" + "\n\n".join(
                f"{n}. {achado}" for n, achado in enumerate(achados, start=1)
            )
            contexto.acrescentar(bloco, fontes)
        else:
            contexto.acrescentar(
                "DIVERGÊNCIAS DETECTADAS\n\nA comparação automática dos registros de "
                "pessoas e equipamentos não encontrou divergências. Isso não cobre "
                "divergências em trechos narrativos.",
                [],
            )
            trechos_semanticos(limite=3)

    else:  # narrativa
        trechos_semanticos()

    if len(contexto.texto) > orcamento:
        contexto.texto = contexto.texto[:orcamento].rstrip() + "\n[... contexto truncado ...]"
    return contexto
