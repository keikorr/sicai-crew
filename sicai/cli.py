"""Linha de comando para ingerir uma pasta local e fazer perguntas.

    python -m sicai.cli ingest --processo vernix --pasta processo_RAG
    python -m sicai.cli chat   --processo vernix "Quais equipamentos foram apreendidos?"
"""

import argparse
import json
import os
from pathlib import Path


def _ingest(args) -> None:
    pasta = Path(args.pasta).resolve()
    # DOCS_FOLDER precisa valer antes de o config ser importado.
    os.environ["DOCS_FOLDER"] = str(pasta)
    from sicai.flows.ingest_flow import executar_ingestao

    documentos = [
        {"document_id": pdf.relative_to(pasta).as_posix(), "pdf_name": pdf.name}
        for pdf in sorted(pasta.rglob("*.pdf"))
    ]
    if not documentos:
        raise SystemExit(f"Nenhum PDF encontrado em {pasta}")

    print(f"{len(documentos)} PDFs encontrados.")
    resumo = executar_ingestao(args.processo, documentos, not args.sem_agentes)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


def _chat(args) -> None:
    from sicai.flows.chat_flow import responder

    resultado = responder(args.processo, args.pergunta)
    print(resultado["response"])
    print(f"\n[rota: {resultado['rota']} | revisada: {resultado['revisada']}]")


def main() -> None:
    parser = argparse.ArgumentParser(prog="sicai")
    comandos = parser.add_subparsers(dest="comando", required=True)

    ingest = comandos.add_parser("ingest", help="Ingere todos os PDFs de uma pasta")
    ingest.add_argument("--processo", required=True)
    ingest.add_argument("--pasta", required=True)
    ingest.add_argument(
        "--sem-agentes",
        action="store_true",
        help="Só indexa e roda os extratores por regras",
    )
    ingest.set_defaults(func=_ingest)

    chat = comandos.add_parser("chat", help="Faz uma pergunta sobre o processo")
    chat.add_argument("--processo", required=True)
    chat.add_argument("pergunta")
    chat.set_defaults(func=_chat)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
