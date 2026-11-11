"""Crews de resposta: especialista da rota, revisor de citações e atendente."""

from crewai import Crew, Task

from sicai import config
from sicai.crews import prompts
from sicai.crews.base import criar_agente, descricao, limpar_resposta


def _executar(perfil: dict, texto_tarefa: str, saida: str, entradas: dict) -> str:
    agente = criar_agente(perfil)
    tarefa = Task(description=descricao(texto_tarefa), expected_output=saida, agent=agente)
    crew = Crew(agents=[agente], tasks=[tarefa], verbose=config.CREW_VERBOSE)
    return limpar_resposta(crew.kickoff(inputs=entradas).raw)


def responder(rota: str, pergunta: str, contexto: str, historico: str) -> str:
    """O especialista da rota redige a resposta a partir do contexto já montado."""
    perfil = prompts.ESPECIALISTAS.get(rota, prompts.ESPECIALISTAS["narrativa"])
    return _executar(
        perfil,
        prompts.TAREFA_RESPOSTA,
        prompts.SAIDA_RESPOSTA,
        {
            "orientacao": perfil["orientacao"],
            "historico": historico or "(sem histórico)",
            "contexto": contexto or "Nenhum trecho encontrado.",
            "pergunta": pergunta,
        },
    )


def revisar(pergunta: str, resposta: str, problemas: list[str], contexto: str) -> str:
    """O revisor corrige a resposta reprovada pela verificação em código."""
    return _executar(
        prompts.REVISOR,
        prompts.REVISOR["descricao"],
        prompts.REVISOR["saida"],
        {
            "problemas": "\n".join(f"- {p}" for p in problemas),
            "contexto": contexto,
            "pergunta": pergunta,
            "resposta": resposta,
        },
    )


def conversar(pergunta: str) -> str:
    return _executar(
        prompts.ATENDENTE,
        prompts.ATENDENTE["descricao"],
        prompts.ATENDENTE["saida"],
        {"pergunta": pergunta},
    )
