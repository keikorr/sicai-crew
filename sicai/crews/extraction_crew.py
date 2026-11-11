"""Crew de extração: lê uma página e devolve registros estruturados.

Cada categoria tem um agente próprio. A crew é montada por página só com os
agentes cujos gatilhos apareceram, e roda em sequência (uma GPU, um modelo).
"""

from crewai import Crew, Process, Task

from sicai import config
from sicai.crews import prompts
from sicai.crews.base import criar_agente, descricao, ler_saida
from sicai.extraction import schemas
from sicai.extraction.rules import TIPOS_PECA

_MODELOS = {
    "pessoas": (schemas.ListaPessoas, "pessoas"),
    "crimes": (schemas.ListaCrimes, "crimes"),
    "equipamentos": (schemas.ListaEquipamentos, "equipamentos"),
    "eventos": (schemas.ListaEventos, "eventos"),
}


def extrair_da_pagina(
    categorias: list[str],
    texto: str,
    documento: str,
    pagina: int,
    tipo_peca: str,
) -> dict[str, list[dict]]:
    """Roda os extratores pedidos sobre uma página. Saída ainda NÃO validada."""
    categorias = [c for c in categorias if c in _MODELOS]
    if not categorias:
        return {}

    agentes, tarefas = [], []
    for categoria in categorias:
        perfil = prompts.EXTRATORES[categoria]
        agente = criar_agente(perfil, temperatura=0.0)
        agentes.append(agente)
        tarefas.append(Task(
            description=descricao(perfil["descricao"]),
            expected_output=perfil["saida"],
            agent=agente,
            output_pydantic=_MODELOS[categoria][0],
            # Cada extrator lê só a página; a saída do anterior não é contexto.
            context=[],
        ))

    crew = Crew(
        agents=agentes,
        tasks=tarefas,
        process=Process.sequential,
        verbose=config.CREW_VERBOSE,
    )
    resultado = crew.kickoff(inputs={
        "texto": texto,
        "documento": documento,
        "pagina": pagina,
        "tipo_peca": tipo_peca,
    })

    extraido = {}
    for categoria, saida in zip(categorias, resultado.tasks_output):
        modelo, campo = _MODELOS[categoria]
        lido = ler_saida(saida, modelo)
        if lido is None:
            print(f"  {documento} p.{pagina}: saída de '{categoria}' fora do formato")
            continue
        extraido[categoria] = [item.model_dump() for item in getattr(lido, campo)]
    return extraido


def classificar_peca(documento: str, texto: str) -> str:
    """Usado só quando as regras não reconhecem o tipo da peça."""
    perfil = prompts.CLASSIFICADOR
    agente = criar_agente(perfil, temperatura=0.0)
    tarefa = Task(
        description=descricao(perfil["descricao"]),
        expected_output=perfil["saida"],
        agent=agente,
        output_pydantic=schemas.ClassificacaoPeca,
    )
    crew = Crew(agents=[agente], tasks=[tarefa], verbose=config.CREW_VERBOSE)
    resultado = crew.kickoff(inputs={
        "documento": documento,
        "tipos": ", ".join(TIPOS_PECA),
        "texto": texto[:2500],
    })
    lido = ler_saida(resultado.tasks_output[0], schemas.ClassificacaoPeca)
    tipo = (lido.tipo_peca if lido else "").strip().lower()
    return tipo if tipo in TIPOS_PECA else "outro"
