"""Flow de resposta (plano online).

preparar -> rotear -+-> casual   -> atendente
                    +-> processo -> contexto em código -> especialista -> verificar
                                                                          (-> revisor, 1 vez)

No máximo duas chamadas ao modelo por pergunta: o especialista e, só se a
verificação reprovar, o revisor.
"""

from typing import Literal

from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, Field

from sicai import config, context, verifier
from sicai.crews import answer_crew
from sicai.router import classificar
from sicai.store.case_db import obter_db

AVISO = (
    "\n\n> Aviso: a verificação automática não conseguiu confirmar todas as "
    "citações desta resposta. Confira os pontos abaixo nos autos:\n"
)


class ChatState(BaseModel):
    processo_id: str = ""
    mensagem: str = ""
    historico: list[dict] = Field(default_factory=list)
    consulta: str = ""
    rota: str = ""
    contexto: str = ""
    fontes: list[tuple[str, int]] = Field(default_factory=list)
    resposta: str = ""
    revisada: bool = False
    pendencias: list[str] = Field(default_factory=list)


class ChatFlow(Flow[ChatState]):

    @start()
    def preparar(self):
        config.validar_processo_id(self.state.processo_id)
        # A pergunta anterior ajuda em seguimentos como "e ele, que crime cometeu?".
        anteriores = [m["content"] for m in self.state.historico if m.get("role") == "user"]
        self.state.consulta = (
            f"{anteriores[-1][:300]}\n{self.state.mensagem}" if anteriores else self.state.mensagem
        )
        # A rota considera só a mensagem atual: códigos do histórico não contaminam.
        self.state.rota = classificar(self.state.mensagem)

    @router(preparar)
    def rotear(self) -> Literal["casual", "processo"]:
        return "casual" if self.state.rota == "casual" else "processo"

    @listen("casual")
    def responder_casual(self):
        self.state.resposta = answer_crew.conversar(self.state.mensagem)

    @listen("processo")
    def responder_processo(self):
        montado = context.montar(
            self.state.rota,
            self.state.processo_id,
            self.state.mensagem,
            self.state.consulta,
            obter_db(),
        )
        self.state.contexto = montado.texto
        self.state.fontes = montado.fontes

        historico = "\n".join(
            f"{m.get('role')}: {str(m.get('content', ''))[:600]}"
            for m in self.state.historico[-4:]
            if m.get("role") in ("user", "assistant")
        )
        self.state.resposta = answer_crew.responder(
            self.state.rota, self.state.mensagem, self.state.contexto, historico
        )

    @listen(responder_processo)
    def verificar(self):
        problemas = self._problemas()
        if problemas:
            revisada = answer_crew.revisar(
                self.state.mensagem, self.state.resposta, problemas, self.state.contexto
            )
            if revisada:
                self.state.resposta = revisada
                self.state.revisada = True
            problemas = self._problemas()

        self.state.pendencias = problemas
        if problemas:
            self.state.resposta += AVISO + "\n".join(f"> - {p}" for p in problemas)

    def _problemas(self) -> list[str]:
        return verifier.verificar(
            self.state.resposta, self.state.contexto, self.state.fontes, self.state.mensagem
        )


def responder(processo_id: str, mensagem: str, historico: list[dict] | None = None) -> dict:
    flow = ChatFlow()
    flow.kickoff(inputs={
        "processo_id": processo_id,
        "mensagem": mensagem,
        "historico": historico or [],
    })
    estado = flow.state
    return {
        "response": estado.resposta,
        "rota": estado.rota,
        "revisada": estado.revisada,
        "pendencias": estado.pendencias,
        "fontes": [{"documento": doc, "pagina": pag} for doc, pag in estado.fontes],
    }
