"""Detecção determinística de divergências entre registros.

O código encontra; o agente de inconsistências só explica. Assim o modelo não
pode inventar uma divergência nem deixar de ver uma que existe na base.
"""

from itertools import combinations

from sicai.extraction.validation import LIMIAR_IDENTIFICACAO_INCERTA, similaridade_nomes
from sicai.text import normalizar


def _fontes(registro: dict) -> str:
    return "; ".join(f"{f['documento']}, p. {f['pagina']}" for f in registro["fontes"])


def _descricao_equipamento(dados: dict) -> str:
    partes = [dados.get("tipo", ""), dados.get("subtipo", ""), dados.get("marca", "")]
    return " / ".join(p for p in partes if p) or "não informado"


def divergencias_equipamentos(equipamentos: list[dict]) -> list[str]:
    """Mesmo lacre ou identificador aparecendo em registros com dados diferentes."""
    por_codigo: dict[str, list[dict]] = {}
    for registro in equipamentos:
        dados = registro["dados"]
        codigos = [dados.get("lacre", "")] + list(dados.get("identificadores", []))
        for codigo in {normalizar(c) for c in codigos if c}:
            por_codigo.setdefault(codigo, []).append(registro)

    achados = []
    for codigo, grupo in sorted(por_codigo.items()):
        if len(grupo) < 2:
            continue
        versoes = "\n".join(
            f"  - {_descricao_equipamento(r['dados'])}; quantidade: "
            f"{r['dados'].get('quantidade') or 'não informado'}; pessoa relacionada: "
            f"{r['dados'].get('pessoa_relacionada') or 'não informado'} ({_fontes(r)})"
            for r in grupo
        )
        achados.append(
            f"O código {codigo.upper()} aparece em {len(grupo)} registros de "
            f"equipamento com dados diferentes:\n{versoes}"
        )
    return achados


def divergencias_pessoas(pessoas: list[dict]) -> list[str]:
    achados = []

    for a, b in combinations(pessoas, 2):
        da, db = a["dados"], b["dados"]
        similaridade = similaridade_nomes(da["nome"], db["nome"])
        mesmo_nome = normalizar(da["nome"]) == normalizar(db["nome"])

        # Dois registros com o mesmo nome só existem quando os CPFs diferem.
        if mesmo_nome:
            achados.append(
                f"Mesmo nome com CPFs diferentes: '{da['nome']}' "
                f"({_fontes(a)}) e '{db['nome']}' ({_fontes(b)})."
            )
        elif similaridade >= LIMIAR_IDENTIFICACAO_INCERTA:
            achados.append(
                f"Identificação incerta: '{da['nome']}' ({_fontes(a)}) e "
                f"'{db['nome']}' ({_fontes(b)}) têm grafias parecidas e podem ou "
                "não ser a mesma pessoa."
            )

    for registro in pessoas:
        dados = registro["dados"]
        papeis: dict[str, list[str]] = {}
        for papel in dados.get("papeis", []):
            if normalizar(papel["papel"]) == "mencionado":
                continue
            papeis.setdefault(papel["papel"], []).append(
                f"{papel['documento']}, p. {papel['pagina']}"
            )
        if len({normalizar(p) for p in papeis}) > 1:
            versoes = "; ".join(
                f"{papel} ({', '.join(dict.fromkeys(fontes))})"
                for papel, fontes in papeis.items()
            )
            achados.append(
                f"'{dados['nome']}' aparece com papéis diferentes conforme a peça: {versoes}."
            )

    return achados


def detectar(pessoas: list[dict], equipamentos: list[dict]) -> list[str]:
    return divergencias_equipamentos(equipamentos) + divergencias_pessoas(pessoas)
