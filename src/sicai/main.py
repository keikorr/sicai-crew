#!/usr/bin/env python
"""Pontos de entrada do projeto CrewAI (ver [project.scripts] no pyproject.toml).

    crewai run        -> kickoff(): conversa no terminal sobre um processo
    crewai flow plot  -> plot(): desenha os dois flows em HTML
    uv run serve      -> serve(): sobe a API e a interface web
    uv run ingest     -> ingest(): ingere uma pasta de PDFs
"""

import os

from sicai.flows.chat_flow import ChatFlow, responder
from sicai.flows.ingest_flow import IngestFlow


def kickoff():
    """Conversa no terminal. PROCESSO_ID no ambiente evita a primeira pergunta."""
    processo_id = os.getenv("PROCESSO_ID") or input("Processo: ").strip()
    historico: list[dict] = []
    print("Pergunte sobre o processo (linha vazia encerra).")
    while True:
        pergunta = input("\n> ").strip()
        if not pergunta:
            break
        resultado = responder(processo_id, pergunta, historico)
        print(f"\n{resultado['response']}\n[rota: {resultado['rota']}]")
        historico += [
            {"role": "user", "content": pergunta},
            {"role": "assistant", "content": resultado["response"]},
        ]


def plot():
    ChatFlow().plot("chat_flow")
    IngestFlow().plot("ingest_flow")


def serve():
    import uvicorn

    uvicorn.run("sicai.api:app", host="0.0.0.0", port=int(os.getenv("PORT", "3000")))


def ingest():
    from sicai.cli import main

    main()


if __name__ == "__main__":
    kickoff()
