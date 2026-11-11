"""Extração determinística de autos de apreensão (portada da branch `mock`).

Reconhece os dois layouts presentes nos autos já ingeridos:
  1. "- Tipo: ... - Subtipo: ... - Qtde: ..."
  2. "Objeto.....: / Subtipo....: / Quantidade.:"
Documentos em outro layout não são reconhecidos aqui e ficam para o agente
extrator de equipamentos.
"""

import re

from sicai.text import limpar_valor, normalizar

_MARCADORES_FORMAIS = (
    "auto de exibicao/apreensao",
    "auto de exibicao e apreensao",
    "auto de apreensao",
    "termo de apreensao",
)


def pagina_contem_inventario(texto: str) -> bool:
    """Exige título formal ou lista de objetos E a estrutura de um registro.

    "Auto de apreensão" também aparece em relatórios narrativos; só a
    presença dos campos estruturados indica que a página é o próprio auto.
    """
    conteudo = (texto or "").casefold()
    sem_acento = normalizar(texto)
    campos = ("objeto....." in conteudo and "subtipo...." in conteudo) or (
        "tipo:" in conteudo and "qtde:" in conteudo
    )
    titulo = any(marcador in sem_acento for marcador in _MARCADORES_FORMAIS)
    lista = "objetos apreendidos" in sem_acento
    return campos and (titulo or lista)


def extrair_lacre(texto: str) -> str:
    achado = re.search(
        r"(?:LACRADO(?:S)?\s+SOB\s+N\.?|LACRE)\s*(?:-|:)?\s*([A-Z]{0,8}\d{4,})",
        texto or "",
        flags=re.IGNORECASE,
    )
    return achado.group(1) if achado else ""


def _registros_por_tipo(
    texto: str,
    documento: str,
    pagina: int,
    limite_inicio: int,
    pagina_continuacao: int | None,
) -> list[dict]:
    registros = []
    padrao = re.compile(r"(?ms)^\s*-\s*Tipo:\s*(.*?)(?=^\s*-\s*Tipo:|\Z)")

    for achado in padrao.finditer(texto):
        # O texto inclui a página seguinte; registros que começam nela são dela.
        if achado.start() >= limite_inicio:
            continue

        bloco = achado.group(0)
        tipo = re.search(r"Tipo:\s*(.*?)(?=\s*-\s*Subtipo:)", bloco, re.S)
        subtipo = re.search(r"Subtipo:\s*(.*?)(?=\s*-\s*Qtde:|\n|\Z)", bloco, re.S)
        if not tipo or not subtipo:
            continue

        quantidade = re.search(r"Qtde:\s*([^\n-]+)", bloco, re.S)
        unidade = re.search(r"Unidade\.?:\s*([^\n-]+)", bloco, re.S)
        marca = re.search(r"Marca:\s*(.*?)(?=\s*-\s*Observações:|\n|\Z)", bloco, re.S)
        observacoes = re.search(
            r"Observações:\s*(.*?)(?=\s*Pessoa relacionada:|\Z)", bloco, re.S
        )
        pessoa = re.search(r"Pessoa relacionada:\s*([^\n]+)", bloco, re.S)

        texto_obs = limpar_valor(observacoes.group(1) if observacoes else "")
        fontes = [{"documento": documento, "pagina": pagina}]

        # A página seguinte só vira fonte quando completa este registro.
        na_pagina_atual = texto[achado.start():limite_inicio]
        incompleto = not re.search(r"Pessoa relacionada:", na_pagina_atual, re.I)
        if pagina_continuacao and achado.end() > limite_inicio and incompleto:
            fontes.append({"documento": documento, "pagina": pagina_continuacao})

        registros.append({
            "tipo": limpar_valor(tipo.group(1)),
            "subtipo": limpar_valor(subtipo.group(1)),
            "quantidade": limpar_valor(quantidade.group(1) if quantidade else ""),
            "unidade": limpar_valor(unidade.group(1) if unidade else ""),
            "marca": limpar_valor(marca.group(1) if marca else ""),
            "observacoes": texto_obs,
            "lacre": extrair_lacre(texto_obs),
            "identificadores": [],
            "pessoa_relacionada": limpar_valor(
                re.split(r"\s+Origem:", pessoa.group(1) if pessoa else "", flags=re.I)[0]
            ),
            "fontes": fontes,
        })

    return registros


def _registros_por_objeto(texto: str, documento: str, pagina: int) -> list[dict]:
    registros = []
    padrao = re.compile(r"(?ms)^\s*Objeto\.*:\s*(.*?)(?=^\s*Objeto\.*:|\Z)")

    for achado in padrao.finditer(texto):
        bloco = achado.group(0)

        def campo(nome: str) -> str:
            valor = re.search(rf"(?mi)^\s*{nome}\.*:\s*(.+?)\s*$", bloco)
            return limpar_valor(valor.group(1)) if valor else ""

        tipo, subtipo = campo("Objeto"), campo("Subtipo")
        if not tipo or not subtipo:
            continue

        observacoes = campo("Observações")
        registros.append({
            "tipo": tipo,
            "subtipo": subtipo,
            "quantidade": campo("Quantidade"),
            "unidade": campo("Unidade"),
            "marca": campo("Marca"),
            "observacoes": observacoes,
            "lacre": extrair_lacre(observacoes),
            "identificadores": [],
            "pessoa_relacionada": "",
            "fontes": [{"documento": documento, "pagina": pagina}],
        })

    return registros


def chave_equipamento(registro: dict) -> str:
    campos = ("tipo", "subtipo", "quantidade", "marca", "lacre", "observacoes")
    return "|".join(normalizar(registro.get(campo, "")) for campo in campos)


def consolidar(registros: list[dict]) -> list[dict]:
    """Une cópias do mesmo registro (autos repetidos em vários PDFs)."""
    unicos: dict[str, dict] = {}
    for registro in registros:
        chave = chave_equipamento(registro)
        if chave not in unicos:
            unicos[chave] = registro
            continue
        atual = unicos[chave]
        if not atual["pessoa_relacionada"] and registro["pessoa_relacionada"]:
            atual["pessoa_relacionada"] = registro["pessoa_relacionada"]
        for fonte in registro["fontes"]:
            if fonte not in atual["fontes"]:
                atual["fontes"].append(fonte)
    return list(unicos.values())


def extrair_inventario(documento: str, paginas: list[dict]) -> list[dict]:
    """Itens apreendidos de um documento. `paginas`: [{"pagina", "texto"}]."""
    paginas = sorted(paginas, key=lambda p: p["pagina"])
    # Um registro pode continuar na página seguinte sem repetir o cabeçalho,
    # então basta uma página de auto para o documento inteiro ser examinado.
    if not any(pagina_contem_inventario(p["texto"]) for p in paginas):
        return []

    por_tipo = []
    for posicao, atual in enumerate(paginas):
        seguinte = paginas[posicao + 1] if posicao + 1 < len(paginas) else None
        por_tipo.extend(_registros_por_tipo(
            atual["texto"] + "\n" + (seguinte["texto"] if seguinte else ""),
            documento,
            atual["pagina"],
            limite_inicio=len(atual["texto"]),
            pagina_continuacao=seguinte["pagina"] if seguinte else None,
        ))

    # A versão por "Tipo" é mais completa que a versão visual do mesmo auto;
    # usar as duas duplicaria os itens.
    if por_tipo:
        return consolidar(por_tipo)

    por_objeto = []
    for pagina in paginas:
        por_objeto.extend(_registros_por_objeto(pagina["texto"], documento, pagina["pagina"]))
    return consolidar(por_objeto)


def extrair_papeis_documentais(documento: str, paginas: list[dict]) -> list[dict]:
    """Funções rotuladas no cabeçalho do auto: exibidor e delegado.

    Não interpreta assinaturas soltas como se fossem exibidores.
    """
    if not any(pagina_contem_inventario(p["texto"]) for p in paginas):
        return []

    achados = []
    padroes = (
        (r"(?is)EXIBIDOR\(A\)\s*:\s*([^,\n]+?)(?=\s*,\s*RG\b|\s*,\s*CPF\b)", "Exibidor(a)"),
        (
            r"(?is)Doutor\(a\)\s+([^,\n]+?),\s*Delegado\(a\)\s+de\s+Pol[ií]cia",
            "Delegado(a) de Polícia presente no auto",
        ),
    )
    for pagina in paginas:
        for padrao, papel in padroes:
            for achado in re.finditer(padrao, pagina["texto"]):
                nome = limpar_valor(achado.group(1))
                if nome:
                    achados.append({
                        "nome": nome,
                        "cpf": "",
                        "papel": papel,
                        "contexto": "",
                        "documento": documento,
                        "pagina": pagina["pagina"],
                    })
    return achados
