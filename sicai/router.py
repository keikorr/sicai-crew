"""Roteador por regras (ampliado a partir de `identificar_estrategia_busca` da mock).

Não usa o modelo: as regras custam zero e são previsíveis. O que nenhuma regra
reconhece cai na rota narrativa, que usa a busca híbrida.
"""

import re

from sicai.text import extrair_identificadores, normalizar

ROTAS = (
    "casual",
    "identificador",
    "inconsistencias",
    "conformidade",
    "custodia",
    "equipamentos",
    "crimes",
    "pessoas",
    "narrativa",
)

_CASUAL = re.compile(
    r"^(oi+|ola|opa|e ai|bom dia|boa tarde|boa noite|tudo bem|obrigad[oa]|valeu|"
    r"tchau|ate logo|ate mais|ok|certo|entendi|beleza)\b[\s!.,?]*"
    r"(tudo bem|tudo bom|como vai|obrigad[oa])?[\s!.,?]*$"
)

_TERMOS = {
    "inconsistencias": ("inconsisten", "divergen", "contradi", "conflit", "discrepan"),
    "conformidade": ("conformidade", "158-", "codigo de processo penal", "cpp",
                     "protocolo", "previsto em lei", "exigencia legal", "normativ"),
    "custodia": ("cadeia de custodia", "custodia", "linha do tempo", "sequencia documental",
                 "exibidor", "quem apresentou", "quem exibiu", "encaminhad", "rastre"),
    "equipamentos": ("apreens", "inventario", "lacre", "imei", "numero de serie", "serial",
                     "auto de apreensao", "termo de apreensao", "equipamento", "aparelho",
                     "celular", "notebook", "objeto apreendido", "bem apreendido"),
    "crimes": ("crime", "delito", "tipifica", "artigo", "imputa", "acusacao", "acusad",
               "denuncia", "pena", "condena"),
    "pessoas": ("quem e", "quem sao", "quais pessoas", "pessoas", "reu", "reus", "vitima",
                "testemunha", "investigad", "indiciad", "envolvid", "papel de", "cpf"),
}

_ITENS = ("objeto", "equipamento", "bem", "item", "aparelho", "material")
_APREENSAO = ("apreendid", "arrecad", "recolhid")


def _tem(texto: str, termos: tuple[str, ...]) -> bool:
    """Termos longos valem como prefixo ("apreens" pega "apreensão"); os de até
    4 letras só como palavra inteira, para "reu" não casar com "reunião"."""
    for termo in termos:
        fim = r"\b" if len(termo) <= 4 else ""
        if re.search(rf"\b{re.escape(termo)}{fim}", texto):
            return True
    return False


def classificar(mensagem: str) -> str:
    texto = normalizar(mensagem)

    if len(texto) <= 60 and _CASUAL.match(texto):
        return "casual"

    # Análises transversais têm prioridade sobre o assunto (pessoa, item...).
    for rota in ("inconsistencias", "conformidade", "custodia"):
        if _tem(texto, _TERMOS[rota]):
            return rota

    # Lacre, IMEI ou outro código na pergunta: busca literal, não semântica.
    if extrair_identificadores(mensagem):
        return "identificador"

    if _tem(texto, _TERMOS["equipamentos"]) or (
        _tem(texto, _ITENS) and _tem(texto, _APREENSAO)
    ):
        return "equipamentos"

    for rota in ("crimes", "pessoas"):
        if _tem(texto, _TERMOS[rota]):
            return rota

    return "narrativa"
