"""Formato de saída que cada agente extrator deve devolver."""

from pydantic import BaseModel, Field


class PessoaExtraida(BaseModel):
    nome: str = Field(description="Nome completo, igual ao texto")
    cpf: str = Field(default="", description="CPF se estiver na página, senão vazio")
    papel: str = Field(
        default="",
        description="Papel como consta na página: réu, denunciado, investigado, "
        "vítima, testemunha, policial, perito, advogado, juiz, promotor ou outro",
    )
    contexto: str = Field(default="", description="Frase curta sobre a menção")


class ListaPessoas(BaseModel):
    pessoas: list[PessoaExtraida] = Field(default_factory=list)


class CrimeExtraido(BaseModel):
    descricao: str = Field(description="Crime como descrito na página")
    artigo: str = Field(default="", description="Artigo e lei, se constarem")
    autores: list[str] = Field(default_factory=list, description="Nomes apontados como autores")
    status: str = Field(
        default="",
        description="acusação, indício ou decisão judicial, conforme o documento",
    )


class ListaCrimes(BaseModel):
    crimes: list[CrimeExtraido] = Field(default_factory=list)


class EquipamentoExtraido(BaseModel):
    tipo: str = Field(description="Tipo do objeto (celular, notebook, chip...)")
    subtipo: str = Field(default="")
    marca: str = Field(default="", description="Marca e modelo")
    quantidade: str = Field(default="")
    identificadores: list[str] = Field(
        default_factory=list, description="IMEI, número de série, patrimônio"
    )
    lacre: str = Field(default="")
    pessoa_relacionada: str = Field(default="", description="De quem foi apreendido")
    observacoes: str = Field(default="")


class ListaEquipamentos(BaseModel):
    equipamentos: list[EquipamentoExtraido] = Field(default_factory=list)


class EventoExtraido(BaseModel):
    tipo_evento: str = Field(
        description="apreensão, lacração, encaminhamento, recebimento, perícia, "
        "extração de dados, devolução ou outro"
    )
    data: str = Field(default="", description="Data como escrita na página")
    item: str = Field(default="", description="Objeto ou lacre a que o evento se refere")
    responsavel: str = Field(default="", description="Quem praticou o ato")
    descricao: str = Field(default="")


class ListaEventos(BaseModel):
    eventos: list[EventoExtraido] = Field(default_factory=list)


class ClassificacaoPeca(BaseModel):
    tipo_peca: str = Field(description="Um dos tipos permitidos")
