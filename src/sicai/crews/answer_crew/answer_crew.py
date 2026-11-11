"""Crew de resposta: atendente, especialistas por rota e revisor de citações.

Agentes e tarefas ficam em config/agents.yaml e config/tasks.yaml. Cada
execução usa uma única tarefa (`self.tarefa`) e o agente ligado a ela.
"""

from pathlib import Path

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from sicai import config
from sicai.crews import llm

REGRAS = (Path(__file__).parent / "config" / "regras.md").read_text(encoding="utf-8").strip()

# Rotas do roteador que têm especialista próprio; as demais usam o narrativo.
ROTAS_COM_ESPECIALISTA = (
    "pessoas", "crimes", "equipamentos", "custodia", "inconsistencias", "conformidade",
)


@CrewBase
class AnswerCrew:
    """Crew de resposta do assistente SICAI"""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    # Nome da tarefa que esta execução vai rodar.
    tarefa: str = "responder_narrativa"

    def _agente(self, nome: str) -> Agent:
        return Agent(config=self.agents_config[nome], **llm.opcoes_do_agente())  # type: ignore[index]

    def _tarefa(self, nome: str) -> Task:
        return Task(config=self.tasks_config[nome])  # type: ignore[index]

    @agent
    def atendente(self) -> Agent:
        return self._agente("atendente")

    @agent
    def especialista_pessoas(self) -> Agent:
        return self._agente("especialista_pessoas")

    @agent
    def especialista_crimes(self) -> Agent:
        return self._agente("especialista_crimes")

    @agent
    def especialista_equipamentos(self) -> Agent:
        return self._agente("especialista_equipamentos")

    @agent
    def analista_custodia(self) -> Agent:
        return self._agente("analista_custodia")

    @agent
    def analista_inconsistencias(self) -> Agent:
        return self._agente("analista_inconsistencias")

    @agent
    def analista_conformidade(self) -> Agent:
        return self._agente("analista_conformidade")

    @agent
    def analista_narrativa(self) -> Agent:
        return self._agente("analista_narrativa")

    @agent
    def revisor_citacoes(self) -> Agent:
        return self._agente("revisor_citacoes")

    @task
    def conversar(self) -> Task:
        return self._tarefa("conversar")

    @task
    def responder_pessoas(self) -> Task:
        return self._tarefa("responder_pessoas")

    @task
    def responder_crimes(self) -> Task:
        return self._tarefa("responder_crimes")

    @task
    def responder_equipamentos(self) -> Task:
        return self._tarefa("responder_equipamentos")

    @task
    def responder_custodia(self) -> Task:
        return self._tarefa("responder_custodia")

    @task
    def responder_inconsistencias(self) -> Task:
        return self._tarefa("responder_inconsistencias")

    @task
    def responder_conformidade(self) -> Task:
        return self._tarefa("responder_conformidade")

    @task
    def responder_narrativa(self) -> Task:
        return self._tarefa("responder_narrativa")

    @task
    def revisar(self) -> Task:
        return self._tarefa("revisar")

    @crew
    def crew(self) -> Crew:
        """Monta a crew com a tarefa de `self.tarefa` e o agente dela"""
        tarefa = getattr(self, self.tarefa)()
        return Crew(
            agents=[tarefa.agent],
            tasks=[tarefa],
            process=Process.sequential,
            verbose=config.CREW_VERBOSE,
        )


def _executar(tarefa: str, entradas: dict) -> str:
    montadora = AnswerCrew()
    montadora.tarefa = tarefa
    resultado = montadora.crew().kickoff(inputs={**entradas, "sufixo": llm.sufixo()})
    return llm.limpar_resposta(resultado.raw)


def responder(rota: str, pergunta: str, contexto: str, historico: str) -> str:
    """O especialista da rota redige a resposta a partir do contexto já montado."""
    if rota not in ROTAS_COM_ESPECIALISTA:
        rota = "narrativa"
    return _executar(f"responder_{rota}", {
        "regras": REGRAS,
        "historico": historico or "(sem histórico)",
        "contexto": contexto or "Nenhum trecho encontrado.",
        "pergunta": pergunta,
    })


def revisar(pergunta: str, resposta: str, problemas: list[str], contexto: str) -> str:
    """O revisor corrige a resposta reprovada pela verificação em código."""
    return _executar("revisar", {
        "regras": REGRAS,
        "problemas": "\n".join(f"- {p}" for p in problemas),
        "contexto": contexto,
        "pergunta": pergunta,
        "resposta": resposta,
    })


def conversar(pergunta: str) -> str:
    return _executar("conversar", {"pergunta": pergunta})
