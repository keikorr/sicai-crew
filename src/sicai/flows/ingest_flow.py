"""Flow de ingestão (plano offline).

carregar -> indexar -> extrair por regras -> extrair por agentes -> consolidar

A ingestão é incremental: reingerir um documento substitui só os trechos e os
registros dele, sem tocar no resto do processo.
"""

from crewai.flow import Flow, listen, start
from pydantic import BaseModel, Field

from sicai import config, jobs
from sicai.extraction import inventory_regex, resolver, rules, validation
from sicai.ingest.pdf import baixar_pdf, extrair_paginas
from sicai.store.case_db import obter_db
from sicai.store.vector_store import VectorStore
from sicai.text import dividir, nome_curto

_VALIDADORES = {
    "pessoas": validation.validar_pessoa,
    "crimes": validation.validar_crime,
    "equipamentos": validation.validar_equipamento,
    "eventos": validation.validar_evento,
}


class IngestState(BaseModel):
    processo_id: str = ""
    # [{"document_id": ..., "pdf_name": ...}], mesmo contrato do endpoint original
    documentos: list[dict] = Field(default_factory=list)
    extrair_com_agentes: bool = True
    job_id: str = ""
    # [{"document_id", "nome", "tipo_peca", "paginas": [{"pagina", "texto"}], "inventario"}]
    carregados: list[dict] = Field(default_factory=list)
    resumo: dict = Field(default_factory=dict)


class IngestFlow(Flow[IngestState]):

    def _etapa(self, texto: str) -> None:
        print(f"[ingestão {self.state.processo_id}] {texto}")
        jobs.atualizar(self.state.job_id, status="em andamento", etapa=texto)

    @start()
    def carregar_documentos(self):
        config.validar_processo_id(self.state.processo_id)
        usar_agentes = self.state.extrair_com_agentes and config.EXTRACAO_LLM
        erros = []

        for doc in self.state.documentos:
            document_id, nome = doc["document_id"], nome_curto(doc["pdf_name"])
            self._etapa(f"lendo {nome}")
            try:
                paginas = extrair_paginas(baixar_pdf(document_id))
            except Exception as erro:
                erros.append({"document_id": document_id, "erro": str(erro)})
                continue

            inicio = "\n".join(p["texto"] for p in paginas[:2])
            tipo = rules.classificar_peca_por_regras(nome, inicio)
            if tipo == "outro" and usar_agentes and inicio.strip():
                from sicai.crews.extraction_crew.extraction_crew import classificar_peca

                tipo = classificar_peca(nome, inicio)

            self.state.carregados.append({
                "document_id": document_id,
                "nome": nome,
                "tipo_peca": tipo,
                "paginas": [{"pagina": p["pagina"], "texto": p["texto"]} for p in paginas],
                "inventario": False,
            })

        self.state.resumo = {"erros": erros, "documentos": [], "paginas_lidas_por_agentes": 0}

    @listen(carregar_documentos)
    def indexar(self):
        from sicai.store.embeddings import embutir

        db = obter_db()
        store = VectorStore.abrir(self.state.processo_id)

        for doc in self.state.carregados:
            self._etapa(f"indexando {doc['nome']}")
            chunks, textos = [], []
            for pagina in doc["paginas"]:
                blocos = dividir(pagina["texto"], config.CHUNK_SIZE, config.CHUNK_OVERLAP)
                for chunk_id, bloco in enumerate(blocos):
                    if len(bloco.strip()) < 30:
                        continue
                    chunks.append({
                        "document_id": doc["document_id"],
                        "documento": doc["nome"],
                        "tipo_peca": doc["tipo_peca"],
                        "pagina": pagina["pagina"],
                        "chunk_id": chunk_id,
                        "content": bloco,
                    })
                    textos.append(
                        f"File: {doc['nome']}\n\nPágina: {pagina['pagina']}\n\n{bloco}"
                    )

            vetores = embutir(textos) if textos else []
            store.substituir_documento(doc["document_id"], chunks, vetores)
            db.salvar_documento(
                self.state.processo_id,
                doc["document_id"],
                doc["nome"],
                doc["tipo_peca"],
                doc["paginas"],
            )
            # Os registros que só esta versão antiga do documento sustentava saem.
            db.remover_fontes_do_documento(self.state.processo_id, doc["nome"])
            self.state.resumo["documentos"].append({
                "document_id": doc["document_id"],
                "nome": doc["nome"],
                "tipo_peca": doc["tipo_peca"],
                "paginas": len(doc["paginas"]),
                "trechos": len(chunks),
            })

        store.salvar()

    @listen(indexar)
    def extrair_por_regras(self):
        """Autos de apreensão em layout conhecido: regex, sem modelo."""
        db = obter_db()
        for doc in self.state.carregados:
            itens = inventory_regex.extrair_inventario(doc["nome"], doc["paginas"])
            doc["inventario"] = bool(itens)
            for item in itens:
                resolver.integrar_equipamento(db, self.state.processo_id, item)
            for papel in inventory_regex.extrair_papeis_documentais(doc["nome"], doc["paginas"]):
                fonte = {"documento": papel["documento"], "pagina": papel["pagina"]}
                resolver.integrar_pessoa(db, self.state.processo_id, papel, fonte)

    @listen(extrair_por_regras)
    def extrair_por_agentes(self):
        """Crew de extratores, página a página, com validação literal da saída."""
        if not (self.state.extrair_com_agentes and config.EXTRACAO_LLM):
            return

        from sicai.crews.extraction_crew.extraction_crew import extrair_da_pagina

        db = obter_db()
        for doc in self.state.carregados:
            anterior = ""
            for pagina in doc["paginas"]:
                # Listas costumam quebrar entre páginas: leva o fim da anterior junto.
                texto = (anterior[-600:] + "\n" + pagina["texto"])[:config.EXTRACAO_MAX_CHARS]
                anterior = pagina["texto"]

                categorias = rules.categorias_da_pagina(texto)
                if doc["inventario"] and "equipamentos" in categorias:
                    categorias.remove("equipamentos")  # o regex já cobriu este documento
                if not categorias:
                    continue

                self._etapa(f"extraindo {doc['nome']} p.{pagina['pagina']}")
                try:
                    extraido = extrair_da_pagina(
                        categorias, texto, doc["nome"], pagina["pagina"], doc["tipo_peca"]
                    )
                except Exception as erro:
                    self.state.resumo["erros"].append({
                        "document_id": doc["document_id"],
                        "pagina": pagina["pagina"],
                        "erro": str(erro),
                    })
                    continue

                self.state.resumo["paginas_lidas_por_agentes"] += 1
                fonte = {"documento": doc["nome"], "pagina": pagina["pagina"]}
                self._gravar(db, extraido, texto, fonte)

    def _gravar(self, db, extraido: dict, texto: str, fonte: dict) -> None:
        processo_id = self.state.processo_id
        for categoria, itens in extraido.items():
            for item in itens:
                validado = _VALIDADORES[categoria](item, texto)
                if validado is None:
                    continue
                if categoria == "pessoas":
                    resolver.integrar_pessoa(db, processo_id, validado, fonte)
                elif categoria == "crimes":
                    resolver.integrar_crime(db, processo_id, validado, fonte)
                elif categoria == "equipamentos":
                    resolver.integrar_equipamento(
                        db, processo_id, {**validado, "fontes": [fonte]}
                    )
                else:
                    resolver.integrar_evento(db, processo_id, validado, fonte)

    @listen(extrair_por_agentes)
    def consolidar(self):
        VectorStore.invalidar(self.state.processo_id)
        self.state.resumo["registros"] = obter_db().contagem(self.state.processo_id)
        return self.state.resumo


def executar_ingestao(
    processo_id: str,
    documentos: list[dict],
    extrair_com_agentes: bool = True,
    job_id: str = "",
) -> dict:
    flow = IngestFlow()
    try:
        flow.kickoff(inputs={
            "processo_id": processo_id,
            "documentos": documentos,
            "extrair_com_agentes": extrair_com_agentes,
            "job_id": job_id,
        })
    except Exception as erro:
        jobs.atualizar(job_id, status="falhou", erro=str(erro))
        raise
    resumo = flow.state.resumo
    jobs.atualizar(job_id, status="concluída", etapa="", resumo=resumo)
    return resumo
