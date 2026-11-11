"""Regras baratas que decidem o que vale mandar para os agentes extratores."""

import re

from sicai.text import normalizar

TIPOS_PECA = (
    "denúncia",
    "auto de apreensão",
    "boletim de ocorrência",
    "laudo pericial",
    "decisão judicial",
    "relatório policial",
    "carta precatória",
    "certidão",
    "termo de depoimento",
    "outro",
)

# Ordem importa: o primeiro marcador encontrado define o tipo.
# No nome do arquivo valem palavras soltas ("laudo", "relatorio").
_MARCADORES_NOME = (
    ("auto de apreensão", ("auto de exibicao", "auto de apreensao", "autos de apreensao",
                           "auto apreensao", "termo de apreensao")),
    ("carta precatória", ("carta precatoria",)),
    ("decisão judicial", ("recebimento da denuncia", "prisao preventiva", "decisao", "sentenca")),
    ("denúncia", ("denuncia",)),
    ("laudo pericial", ("laudo",)),
    ("boletim de ocorrência", ("boletim de ocorrencia",)),
    ("relatório policial", ("relatorio",)),
    ("certidão", ("certidao",)),
    ("termo de depoimento", ("depoimento", "declaracoes", "oitiva")),
)
# No texto, essas palavras aparecem em qualquer peça; só expressões formais valem.
_MARCADORES_TEXTO = (
    ("auto de apreensão", ("auto de exibicao/apreensao", "auto de exibicao e apreensao",
                           "auto de apreensao", "termo de apreensao")),
    ("carta precatória", ("carta precatoria",)),
    ("denúncia", ("oferece denuncia", "oferecer denuncia", "vem oferecer a presente denuncia")),
    ("laudo pericial", ("laudo pericial", "laudo de pericia")),
    ("decisão judicial", ("recebo a denuncia", "decreto a prisao", "ante o exposto")),
    ("boletim de ocorrência", ("boletim de ocorrencia",)),
    ("relatório policial", ("relatorio final", "relatorio de investigacao")),
    ("certidão", ("certifico",)),
    ("termo de depoimento", ("termo de depoimento", "termo de declaracoes")),
)

# Só vai para o agente a página que tiver algum gatilho da categoria.
_GATILHOS = {
    "pessoas": re.compile(
        r"\b(reus?|res?|cpf|rg)\b|acusad|denunciad|querelad|condenad|investigad|"
        r"indiciad|vitima|testemunha|qualificad|declarante|depoente"
    ),
    "crimes": re.compile(
        r"\bart(\.|igo)|\blei n|crime|delito|tipific|incurs|denuncia|condena|imputa"
    ),
    "equipamentos": re.compile(
        r"apreen|lacre|imei|celular|aparelho|notebook|computador|chip|pendrive|"
        r"numero de serie|hd externo"
    ),
    "eventos": re.compile(
        r"apreen|lacr|pericia|laudo|encaminh|recebid|devolv|custodia|extracao|"
        r"deposit|entreg"
    ),
}


def classificar_peca_por_regras(nome: str, primeiras_paginas: str) -> str:
    """Tipo da peça pelo nome do arquivo e pelo início do texto."""
    for texto, tabela in (
        (normalizar(nome), _MARCADORES_NOME),
        (normalizar(primeiras_paginas[:3000]), _MARCADORES_TEXTO),
    ):
        for tipo, marcadores in tabela:
            if any(marcador in texto for marcador in marcadores):
                return tipo
    return "outro"


def categorias_da_pagina(texto: str) -> list[str]:
    """Quais extratores devem ler esta página."""
    pagina = normalizar(texto)
    if len(pagina) < 80:
        return []
    return [categoria for categoria, padrao in _GATILHOS.items() if padrao.search(pagina)]
