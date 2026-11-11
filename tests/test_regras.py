"""Roteador, texto, validação literal e regras de extração (dados fictícios)."""

import pytest

from sicai import config
from sicai.extraction import inventory_regex, rules, validation
from sicai.router import classificar
from sicai.text import dividir, extrair_identificadores, nome_curto, normalizar

PAGINA = (
    "O Ministério Público denuncia JOÃO DA SILVA SAURO, CPF 123.456.789-09, "
    "como incurso no art. 33 da Lei 11.343/2006. Foi apreendido um celular "
    "Samsung, IMEI 351234567890123, lacre ABC12345, em 05/03/2021, pelo "
    "policial Carlos Pereira Lima."
)

AUTO = """AUTO DE EXIBIÇÃO E APREENSÃO
Presente o Doutor(a) Mário Andrade Costa, Delegado(a) de Polícia.
EXIBIDOR(A): Fulano de Tal Silva, RG 1234567
Objetos apreendidos:
- Tipo: Telefone - Subtipo: Celular - Qtde: 1 - Unidade: UN
- Marca: Acme - Observações: IMEI 351234567890123 LACRADO SOB N. ABC12345
Pessoa relacionada: Beltrano Souza Origem: Residência
- Tipo: Informática - Subtipo: Notebook - Qtde: 2 - Unidade: UN
- Marca: Zeta - Observações: sem lacre
Pessoa relacionada: Beltrano Souza Origem: Residência
"""


# ------------------------------------------------------------------- texto

def test_normalizar_tira_acentos_e_espacos():
    assert normalizar("  Apreensão   de  VEÍCULO ") == "apreensao de veiculo"


def test_identificadores_ignoram_codigos_curtos():
    achados = extrair_identificadores("lacre ABC12345, IMEI 351234567890123 e o J5")
    assert achados == ["ABC12345", "351234567890123"]


def test_dividir_respeita_sobreposicao():
    blocos = dividir("a" * 4000, tamanho=1800, sobreposicao=200)
    assert [len(b) for b in blocos] == [1800, 1800, 800]


def test_nome_curto():
    assert nome_curto("Vernix\\PROCESSO/Laudo X.PDF") == "Laudo X"


def test_processo_id_nao_sai_da_pasta():
    assert config.validar_processo_id("vernix-2022") == "vernix-2022"
    for ruim in ("../etc", "a/b", "", "..", "x" * 65):
        with pytest.raises(ValueError):
            config.validar_processo_id(ruim)


# ---------------------------------------------------------------- roteador

@pytest.mark.parametrize("mensagem, rota", [
    ("Bom dia!", "casual"),
    ("obrigado", "casual"),
    ("O que consta sobre o lacre ABC12345?", "identificador"),
    ("Quais equipamentos foram apreendidos?", "equipamentos"),
    ("Que objetos foram recolhidos na casa?", "equipamentos"),
    ("Quais crimes foram imputados na denúncia?", "crimes"),
    ("Quem são os réus?", "pessoas"),
    ("Descreva a cadeia de custódia do celular", "custodia"),
    ("Há divergências entre o laudo e o auto?", "inconsistencias"),
    ("A apreensão seguiu o art. 158-A do CPP?", "conformidade"),
    ("Resuma o relatório final", "narrativa"),
    ("O que foi decidido na reunião?", "narrativa"),
])
def test_rotas(mensagem, rota):
    assert classificar(mensagem) == rota


# --------------------------------------------------------------- validação

def test_pessoa_valida_recebe_papel_pelo_radical():
    pessoa = validation.validar_pessoa(
        {"nome": "João da Silva Sauro", "cpf": "123.456.789-09", "papel": "denunciado"},
        PAGINA,
    )
    assert pessoa == {
        "nome": "João da Silva Sauro",
        "cpf": "12345678909",
        "papel": "denunciado",
        "contexto": "",
    }


def test_pessoa_que_nao_esta_na_pagina_e_descartada():
    assert validation.validar_pessoa({"nome": "Maria Inventada Souza"}, PAGINA) is None
    assert validation.validar_pessoa({"nome": "João"}, PAGINA) is None


def test_cpf_e_papel_inventados_sao_esvaziados():
    pessoa = validation.validar_pessoa(
        {"nome": "Carlos Pereira Lima", "cpf": "999.999.999-99", "papel": "réu"}, PAGINA
    )
    assert pessoa["cpf"] == ""
    assert pessoa["papel"] == "mencionado"


def test_crime_perde_artigo_que_nao_esta_na_pagina():
    crime = validation.validar_crime(
        {
            "descricao": "tráfico de drogas",
            "artigo": "art. 35 da Lei 11.343/2006",
            "autores": ["João da Silva Sauro", "Pessoa Inexistente"],
            "status": "Acusação (denúncia)",
        },
        PAGINA,
    )
    assert crime["artigo"] == ""
    assert crime["autores"] == ["João da Silva Sauro"]
    assert crime["status"] == "acusação"


def test_equipamento_so_guarda_codigos_literais():
    equipamento = validation.validar_equipamento(
        {
            "tipo": "celular",
            "marca": "Samsung",
            "identificadores": ["351234567890123", "351234567890124"],
            "lacre": "ABC12346",
        },
        PAGINA,
    )
    assert equipamento["identificadores"] == ["351234567890123"]
    assert equipamento["lacre"] == ""
    assert equipamento["marca"] == "Samsung"
    assert validation.validar_equipamento({"tipo": "notebook"}, PAGINA) is None


def test_evento_com_data_inventada_e_sem_ancora_e_descartado():
    assert validation.validar_evento({"tipo_evento": "perícia", "data": "09/09/2023"}, PAGINA) is None
    evento = validation.validar_evento(
        {"tipo_evento": "apreensão", "data": "05/03/2021", "responsavel": "Carlos Pereira Lima"},
        PAGINA,
    )
    assert evento["data"] == "05/03/2021"
    assert evento["responsavel"] == "Carlos Pereira Lima"


def test_mesma_pessoa():
    a = {"nome": "Willian de Souza Prado", "cpf": ""}
    assert validation.mesma_pessoa(a, {"nome": "WILLIAN DE SOUZA  PRADO", "cpf": ""})
    # Grafia parecida não basta: Ferreira e Pereira são pessoas diferentes.
    assert not validation.mesma_pessoa(a, {"nome": "Willians de Sousa Prado", "cpf": ""})
    com_cpf = {"nome": "Willian de Souza Prado", "cpf": "11111111111"}
    assert validation.mesma_pessoa(com_cpf, {"nome": "Willians de Sousa Prado", "cpf": "11111111111"})
    assert not validation.mesma_pessoa(com_cpf, {**com_cpf, "cpf": "22222222222"})


# ------------------------------------------------------------------ regras

def test_classificar_peca():
    assert rules.classificar_peca_por_regras("Recebimento da denúncia", "") == "decisão judicial"
    assert rules.classificar_peca_por_regras("Samsung J5 - Auto Apreensão", "") == "auto de apreensão"
    assert rules.classificar_peca_por_regras("doc 6", "LAUDO PERICIAL nº 10") == "laudo pericial"
    assert rules.classificar_peca_por_regras("doc 6", "texto qualquer") == "outro"


def test_categorias_da_pagina():
    assert set(rules.categorias_da_pagina(PAGINA)) == {
        "pessoas", "crimes", "equipamentos", "eventos"
    }
    assert rules.categorias_da_pagina("página em branco") == []


def test_inventario_por_tipo():
    paginas = [{"pagina": 3, "texto": AUTO}]
    itens = inventory_regex.extrair_inventario("Auto 31-2021", paginas)
    assert len(itens) == 2
    celular, notebook = itens
    assert celular["tipo"] == "Telefone"
    assert celular["subtipo"] == "Celular"
    assert celular["quantidade"] == "1"
    assert celular["marca"] == "Acme"
    assert celular["lacre"] == "ABC12345"
    assert celular["pessoa_relacionada"] == "Beltrano Souza"
    assert celular["fontes"] == [{"documento": "Auto 31-2021", "pagina": 3}]
    assert notebook["quantidade"] == "2"
    assert notebook["lacre"] == ""


def test_inventario_une_copias_e_ignora_relatorio_narrativo():
    paginas = [{"pagina": 1, "texto": AUTO}, {"pagina": 9, "texto": AUTO}]
    itens = inventory_regex.extrair_inventario("Auto", paginas)
    assert len(itens) == 2
    assert [f["pagina"] for f in itens[0]["fontes"]] == [1, 9]

    narrativo = [{"pagina": 1, "texto": "Conforme o auto de apreensão, havia um celular."}]
    assert inventory_regex.extrair_inventario("Relatório", narrativo) == []


def test_papeis_documentais():
    papeis = inventory_regex.extrair_papeis_documentais("Auto", [{"pagina": 3, "texto": AUTO}])
    assert {(p["nome"], p["papel"]) for p in papeis} == {
        ("Fulano de Tal Silva", "Exibidor(a)"),
        ("Mário Andrade Costa", "Delegado(a) de Polícia presente no auto"),
    }
