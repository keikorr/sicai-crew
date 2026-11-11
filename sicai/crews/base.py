"""Peças comuns às crews: modelo de linguagem, fábrica de agentes e leitura de saída."""

import json
import os
import re
from functools import lru_cache

# O conteúdo é sigiloso: a telemetria do CrewAI fica desligada antes do import.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from crewai import LLM, Agent  # noqa: E402

from sicai import config  # noqa: E402


@lru_cache(maxsize=4)
def criar_llm(temperatura: float = 0.2) -> LLM:
    """Modelo local servido pelo Ollama (via LiteLLM: instale `crewai[litellm]`)."""
    return LLM(
        model=f"ollama/{config.OLLAMA_MODEL}",
        base_url=config.OLLAMA_HOST,
        temperature=temperatura,
        max_tokens=config.OLLAMA_NUM_PREDICT,
        timeout=config.OLLAMA_TIMEOUT,
        num_ctx=config.OLLAMA_NUM_CTX,
    )


def criar_agente(perfil: dict, temperatura: float = 0.2) -> Agent:
    """Agente sem ferramentas e sem delegação: uma chamada ao modelo por tarefa.

    O contexto é montado em código antes da tarefa. Modelos locais pequenos
    erram muito em laços de ferramentas, então eles não são usados aqui.
    """
    return Agent(
        role=perfil["role"],
        goal=perfil["goal"],
        backstory=perfil["backstory"],
        llm=criar_llm(temperatura),
        allow_delegation=False,
        verbose=config.CREW_VERBOSE,
        max_iter=3,
    )


def descricao(texto: str) -> str:
    """Acrescenta o desligamento do raciocínio separado do qwen3, se configurado."""
    return texto + ("\n\n/no_think" if config.OLLAMA_NO_THINK else "")


def limpar_resposta(texto: str) -> str:
    """Remove o bloco <think> que alguns modelos devolvem junto da resposta."""
    return re.sub(r"(?s)<think>.*?</think>", "", texto or "").strip()


def ler_saida(saida_da_tarefa, modelo):
    """Devolve a saída como instância de `modelo`, ou None se não for aproveitável.

    O CrewAI preenche `.pydantic` quando consegue; se não, tentamos ler o JSON
    do texto bruto, que modelos pequenos às vezes cercam de comentários.
    """
    if getattr(saida_da_tarefa, "pydantic", None) is not None:
        return saida_da_tarefa.pydantic

    bruto = limpar_resposta(getattr(saida_da_tarefa, "raw", "") or "")
    inicio, fim = bruto.find("{"), bruto.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        return modelo.model_validate(json.loads(bruto[inicio:fim + 1]))
    except (ValueError, TypeError):
        return None
