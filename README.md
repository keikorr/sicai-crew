# SICAI Crew

Assistente multiagente para análise de processos criminais, construído com
[CrewAI](https://docs.crewai.com) sobre um modelo local servido pelo Ollama.
Consolida as branches `main`, `mock`, `reus` e `feature/ingest` do
`sicai_mlops` numa única arquitetura.

Responde perguntas sobre pessoas, crimes, equipamentos apreendidos, cadeia de
custódia e divergências entre peças, sempre citando documento e página.

O projeto segue o esqueleto de `crewai create flow`: Flows orquestram, e cada
crew tem seus agentes e tarefas declarados em YAML.

## Como funciona

```
PLANO OFFLINE  (IngestFlow)

  PDF (interface, pasta local ou Garage)
    -> texto por página (OCR opcional)
    -> índice de trechos por processo (denso + BM25 + literal)
    -> extração por regras     autos de apreensão em layout conhecido (regex)
    -> ExtractionCrew          pessoas | crimes | equipamentos | eventos
    -> validação literal       nada entra se não estiver escrito na página
    -> base estruturada        SQLite, registros com fontes (documento, página)

PLANO ONLINE  (ChatFlow)

  pergunta
    -> roteador por regras
         casual   -> AnswerCrew: atendente
         processo -> contexto montado em código para a rota
                  -> AnswerCrew: especialista da rota
                  -> verificador de citações (código)
                  -> AnswerCrew: revisor, uma vez, só se a verificação reprovar
```

### Agentes

| Crew | Agente | Função |
|---|---|---|
| ExtractionCrew | Classificador de peças | Tipo da peça, quando as regras não reconhecem |
| ExtractionCrew | Extrator de pessoas | Nome, CPF e papel como constam na página |
| ExtractionCrew | Extrator de crimes | Crime, artigo, autor apontado e status |
| ExtractionCrew | Extrator de equipamentos | Objetos apreendidos fora do layout conhecido |
| ExtractionCrew | Extrator de eventos | Atos sobre os vestígios (base da custódia) |
| AnswerCrew | Atendente | Saudações e conversa casual |
| AnswerCrew | Especialista em pessoas / crimes / equipamentos | Responde a partir da base estruturada |
| AnswerCrew | Analista de cadeia de custódia | Linha do tempo dos atos, sem opinar |
| AnswerCrew | Analista de inconsistências | Explica divergências detectadas em código |
| AnswerCrew | Analista de conformidade | Compara atos com o corpus normativo |
| AnswerCrew | Analista de peças | Perguntas narrativas, com busca híbrida |
| AnswerCrew | Revisor de citações | Corrige respostas reprovadas |

Para mudar o comportamento de um agente, edite o YAML da crew:
`src/sicai/crews/<crew>/config/agents.yaml` e `tasks.yaml`. As regras comuns
de resposta estão em `src/sicai/crews/answer_crew/config/regras.md`.

### Decisões de desenho

- **Orquestração determinística.** O roteador, a montagem de contexto, a
  detecção de divergências e a verificação de citações são código. Os agentes
  não usam ferramentas nem delegam: cada um faz uma chamada ao modelo com o
  contexto pronto. Modelos locais de 4B a 8B erram muito em laços de
  ferramentas e planejamento livre.
- **No máximo duas chamadas ao modelo por pergunta** (especialista e, se
  preciso, revisor).
- **Listagens saem da base estruturada**, não dos trechos mais parecidos.
  Quando a lista não cabe no contexto, o modelo é avisado de que está incompleta.
- **Validação literal** (da branch `reus`): nome, CPF, artigo, lacre, IMEI e
  data propostos pelo modelo só são gravados se estiverem na página.
- **Pessoas só são unidas por CPF igual ou nome idêntico.** Grafias parecidas
  ficam separadas e aparecem como "identificação incerta". A `reus` unia nomes
  com similaridade acima de 0,92, o que também une "Ferreira" e "Pereira".
- **Tudo é separado por `processo_id`**: índice, base e API.
- **Ingestão incremental**: reingerir um documento substitui só os trechos e
  registros dele.
- **Telemetria do CrewAI desligada**, porque o conteúdo é sigiloso.

## Uso com Docker

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

```bash
docker exec -it ollama ollama pull qwen3:8b
```

Abra http://localhost:3000. Na interface você:

1. abre um processo (um identificador como `vernix-2022`);
2. envia os PDFs, com ou sem extração por agentes;
3. conversa com os agentes na aba **Conversa**;
4. confere o que foi extraído na aba **Base estruturada**.

Cada resposta mostra qual agente respondeu, se as citações foram conferidas ou
corrigidas pelo revisor, e as fontes que o agente recebeu.

A extração por agentes lê página a página e é demorada. Sem ela, a ingestão só
indexa e roda os extratores por regras, sem chamar o modelo.

## Uso como projeto CrewAI

```bash
crewai install
```

| Comando | O que faz |
|---|---|
| `crewai run` | Conversa no terminal sobre um processo (`kickoff`) |
| `crewai flow plot` | Desenha `chat_flow.html` e `ingest_flow.html` |
| `uv run serve` | Sobe a API e a interface em `:3000` |
| `uv run ingest ingest --processo vernix --pasta processo_RAG` | Ingere uma pasta de PDFs |
| `uv run ingest chat --processo vernix "pergunta"` | Uma pergunta pela linha de comando |

Fora do Docker, aponte `OLLAMA_HOST` para `http://localhost:11434` no `.env`.

## API

Documentação interativa em http://localhost:3000/docs.

| Rota | Descrição |
|---|---|
| `POST /api/chat` | `{processo_id, message, history}`. Devolve `response`, `rota`, `revisada`, `pendencias` e `fontes` |
| `POST /api/processos/{id}/documentos` | Envio de PDFs (multipart) com ingestão em segundo plano |
| `POST /api/ingest` | `{processo_id, documents: [{document_id, pdf_name}], extrair_com_agentes}` para documentos já no Garage ou na pasta |
| `GET /api/ingest/{job_id}` | Andamento da ingestão |
| `GET /api/processos` | Processos com documentos ingeridos |
| `GET /api/processos/{id}` | Documentos e contagem de registros |
| `GET /api/processos/{id}/registros/{categoria}` | `pessoa`, `crime`, `equipamento` ou `evento` |

Com `API_KEY` definida no `.env`, as rotas `/api` exigem o cabeçalho
`X-API-Key`, e a interface pede a chave.

### Origem dos documentos

`document_id` é procurado primeiro em `DOCS_FOLDER`; se não estiver lá, é
baixado do Garage (S3 compatível) usando `document_id` como chave do objeto no
bucket `GARAGE_BUCKET`. Se a chave real for outra, ajuste `baixar_pdf` em
`src/sicai/ingest/pdf.py`.

### Conformidade normativa

A rota de conformidade lê trechos de um índice separado, o processo `_normas`.
Para carregá-lo, ingira os PDFs da legislação e dos protocolos nesse processo,
sem extração por agentes. Sem esse índice, o analista informa que a base
normativa não foi carregada.

## Testes

```bash
pip install -e ".[dev]" && pytest
```

Os testes de `tests/test_crewai_integracao.py` rodam as crews, os flows e a
API no CrewAI real, com um modelo falso no lugar do Ollama.

## Estrutura

```
pyproject.toml                 [tool.crewai] type = "flow"
src/sicai/
  main.py                      kickoff, plot, serve, ingest
  flows/
    chat_flow.py               ChatFlow
    ingest_flow.py             IngestFlow
  crews/
    llm.py                     modelo do Ollama e opções dos agentes
    answer_crew/
      answer_crew.py           @CrewBase AnswerCrew
      config/agents.yaml
      config/tasks.yaml
      config/regras.md
    extraction_crew/
      extraction_crew.py       @CrewBase ExtractionCrew
      config/agents.yaml
      config/tasks.yaml
  tools/                       vazia: os agentes não usam ferramentas
  web/index.html               interface
  api.py                       rotas HTTP
  router.py                    roteador por regras
  context.py                   contexto de cada rota
  verifier.py                  verificador de citações
  analysis/                    detecção de divergências
  extraction/                  regras, regex de autos, validação literal, entidades
  ingest/                      download e leitura de PDF
  store/                       índice de trechos e base estruturada
tests/
```

## Dados sigilosos

Peças, índices e a base estruturada contêm dados pessoais e de processo
criminal. O `.gitignore` exclui `data/`, as pastas `processo_*` e arquivos
`.pdf`, `.sqlite` e `.npy`. Não os adicione ao repositório.
