"""Crew de extração: lê uma página e devolve registros estruturados.

Cada categoria tem um agente e uma tarefa próprios (config/agents.yaml e
config/tasks.yaml). A crew é montada só com as tarefas pedidas em
`self.tarefas` e roda em sequência (uma GPU, um modelo).
"""

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from sicai import config
from sicai.crews import llm
from sicai.extraction import schemas
from sicai.extraction.rules import TIPOS_PECA

# categoria -> (tarefa, modelo de saída, campo com a lista)
_EXTRATORES = {
    "pessoas": ("extrair_pessoas", schemas.ListaPessoas, "pessoas"),
    "crimes": ("extrair_crimes", schemas.ListaCrimes, "crimes"),
    "equipamentos": ("extrair_equipamentos", schemas.ListaEquipamentos, "equipamentos"),
    "eventos": ("extrair_eventos", schemas.ListaEventos, "eventos"),
}


@CrewBase
class ExtractionCrew:
    """Crew de extratores de peças processuais"""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    # Nomes das tarefas que entram na crew desta execução.
    tarefas: list[str] = []

    def _agente(self, nome: str) -> Agent:
        return Agent(config=self.agents_config[nome], **llm.opcoes_do_agente(0.0))  # type: ignore[index]

    def _tarefa(self, nome: str, saida) -> Task:
        return Task(
            config=self.tasks_config[nome],  # type: ignore[index]
            output_pydantic=saida,
            # Cada extrator lê só a página; a saída do anterior não é contexto.
            context=[],
        )

    @agent
    def classificador_de_pecas(self) -> Agent:
        return self._agente("classificador_de_pecas")

    @agent
    def extrator_de_pessoas(self) -> Agent:
        return self._agente("extrator_de_pessoas")

    @agent
    def extrator_de_crimes(self) -> Agent:
        return self._agente("extrator_de_crimes")

    @agent
    def extrator_de_equipamentos(self) -> Agent:
        return self._agente("extrator_de_equipamentos")

    @agent
    def extrator_de_eventos(self) -> Agent:
        return self._agente("extrator_de_eventos")

    @task
    def classificar_peca(self) -> Task:
        return self._tarefa("classificar_peca", schemas.ClassificacaoPeca)

    @task
    def extrair_pessoas(self) -> Task:
        return self._tarefa("extrair_pessoas", schemas.ListaPessoas)

    @task
    def extrair_crimes(self) -> Task:
        return self._tarefa("extrair_crimes", schemas.ListaCrimes)

    @task
    def extrair_equipamentos(self) -> Task:
        return self._tarefa("extrair_equipamentos", schemas.ListaEquipamentos)

    @task
    def extrair_eventos(self) -> Task:
        return self._tarefa("extrair_eventos", schemas.ListaEventos)

    @crew
    def crew(self) -> Crew:
        """Monta a crew só com as tarefas de `self.tarefas`"""
        tarefas = [getattr(self, nome)() for nome in self.tarefas]
        return Crew(
            agents=[tarefa.agent for tarefa in tarefas],
            tasks=tarefas,
            process=Process.sequential,
            verbose=config.CREW_VERBOSE,
        )


def _crew(tarefas: list[str]) -> Crew:
    montadora = ExtractionCrew()
    montadora.tarefas = tarefas
    return montadora.crew()


def extrair_da_pagina(
    categorias: list[str],
    texto: str,
    documento: str,
    pagina: int,
    tipo_peca: str,
) -> dict[str, list[dict]]:
    """Roda os extratores pedidos sobre uma página. Saída ainda NÃO validada."""
    categorias = [c for c in categorias if c in _EXTRATORES]
    if not categorias:
        return {}

    resultado = _crew([_EXTRATORES[c][0] for c in categorias]).kickoff(inputs={
        "texto": texto,
        "documento": documento,
        "pagina": pagina,
        "tipo_peca": tipo_peca,
        "sufixo": llm.sufixo(),
    })

    extraido = {}
    for categoria, saida in zip(categorias, resultado.tasks_output):
        _, modelo, campo = _EXTRATORES[categoria]
        lido = llm.ler_saida(saida, modelo)
        if lido is None:
            print(f"  {documento} p.{pagina}: saída de '{categoria}' fora do formato")
            continue
        extraido[categoria] = [item.model_dump() for item in getattr(lido, campo)]
    return extraido


def classificar_peca(documento: str, texto: str) -> str:
    """Usado só quando as regras não reconhecem o tipo da peça."""
    resultado = _crew(["classificar_peca"]).kickoff(inputs={
        "documento": documento,
        "tipos": ", ".join(TIPOS_PECA),
        "texto": texto[:2500],
        "sufixo": llm.sufixo(),
    })
    lido = llm.ler_saida(resultado.tasks_output[0], schemas.ClassificacaoPeca)
    tipo = (lido.tipo_peca if lido else "").strip().lower()
    return tipo if tipo in TIPOS_PECA else "outro"
