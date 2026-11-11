# SICAI Crew

Assistente multiagente para análise de processos criminais, construído com
[CrewAI](https://docs.crewai.com) sobre um modelo local servido pelo Ollama.
Consolida as branches `main`, `mock`, `reus` e `feature/ingest` do
`sicai_mlops` numa única arquitetura.

Responde perguntas sobre pessoas, crimes, equipamentos apreendidos, cadeia de
custódia e divergências entre peças, sempre citando documento e página.

## Como funciona

Dois planos, cada um orquestrado por um Flow do CrewAI.

```
PLANO OFFLINE  (IngestFlow, disparado por POST /api/ingest)

  PDF (Garage ou pasta local)
    -> texto por página (OCR opcional)
    -> índice de trechos por processo (denso + BM25 + literal)
    -> extração por regras     autos de apreensão em layout conhecido (regex)
    -> crew de extratores      pessoas | crimes | equipamentos | eventos
    -> validação literal       nada entra se não estiver escrito na página
    -> base estruturada        SQLite, registros com fontes (documento, página)

PLANO ONLINE  (ChatFlow, POST /api/chat)

  pergunta
    -> roteador por regras
         casual   -> atendente
         processo -> contexto montado em código para a rota
                  -> especialista da rota redige a resposta
                  -> verificador de citações (código)
                  -> revisor, uma vez, só se a verificação reprovar
```

### Agentes

| Agente | Plano | Função |
|---|---|---|
| Classificador de peças | offline | Tipo da peça, quando as regras não reconhecem |
| Extrator de pessoas | offline | Nome, CPF e papel como constam na página |
| Extrator de crimes | offline | Crime, artigo, autor apontado e status |
| Extrator de equipamentos | offline | Objetos apreendidos fora do layout conhecido |
| Extrator de eventos | offline | Atos sobre os vestígios (base da custódia) |
| Atendente | online | Saudações e conversa casual |
| Especialista em pessoas / crimes / equipamentos | online | Responde a partir da base estruturada |
| Analista de cadeia de custódia | online | Linha do tempo dos atos, sem opinar |
| Analista de inconsistências | online | Explica divergências detectadas em código |
| Analista de conformidade | online | Compara atos com o corpus normativo |
| Analista de peças | online | Perguntas narrativas, com busca híbrida |
| Revisor de citações | online | Corrige respostas reprovadas |

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

## Uso

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

```bash
docker exec -it ollama ollama pull qwen3:8b
```

Ingerir uma pasta de PDFs pela linha de comando (coloque-os em `processo_RAG/`):

```bash
docker compose exec chatbot python -m sicai.cli ingest --processo vernix --pasta processo_RAG
```

Acrescente `--sem-agentes` para só indexar e rodar os extratores por regras,
sem chamar o modelo. A extração com agentes lê página a página e é demorada.

Perguntar:

```bash
docker compose exec chatbot python -m sicai.cli chat --processo vernix "Quais equipamentos foram apreendidos?"
```

### API

Documentação interativa em http://localhost:3000/docs.

| Rota | Descrição |
|---|---|
| `POST /api/ingest` | `{processo_id, documents: [{document_id, pdf_name}], extrair_com_agentes}`. Roda em segundo plano e devolve `job_id` |
| `GET /api/ingest/{job_id}` | Andamento da ingestão |
| `POST /api/chat` | `{processo_id, message, history}`. Devolve `response`, `rota`, `revisada`, `pendencias` e `fontes` |
| `GET /api/processos/{processo_id}` | Documentos e contagem de registros |
| `GET /api/processos/{processo_id}/registros/{categoria}` | `pessoa`, `crime`, `equipamento` ou `evento` |

Com `API_KEY` definida no `.env`, as rotas `/api` exigem o cabeçalho `X-API-Key`.

### Origem dos documentos

`document_id` é procurado primeiro em `DOCS_FOLDER`; se não estiver lá, é
baixado do Garage (S3 compatível) usando `document_id` como chave do objeto no
bucket `GARAGE_BUCKET`. Se a chave real for outra, ajuste `baixar_pdf` em
`sicai/ingest/pdf.py`.

### Conformidade normativa

A rota de conformidade lê trechos de um índice separado, o processo `_normas`.
Para carregá-lo, ingira os PDFs da legislação e dos protocolos com
`--processo _normas --sem-agentes`. Sem esse índice, o analista informa que a
base normativa não foi carregada.

## Testes

```bash
pip install -r requirements-dev.txt && pytest
```

Os testes de `tests/test_crewai_integracao.py` rodam as crews e os flows no
CrewAI real com um modelo falso no lugar do Ollama, e são pulados se o CrewAI
não estiver instalado.

## Estrutura

```
sicai/
  api.py                 rotas HTTP
  cli.py                 ingestão de pasta e pergunta pela linha de comando
  config.py              variáveis de ambiente
  router.py              roteador por regras
  context.py             contexto de cada rota
  verifier.py            verificador de citações
  analysis/              detecção de divergências
  extraction/            regras, regex de autos, validação literal, resolução de entidades
  crews/                 agentes, prompts e crews do CrewAI
  flows/                 IngestFlow e ChatFlow
  ingest/                download e leitura de PDF
  store/                 índice de trechos e base estruturada
```

## Dados sigilosos

Peças, índices e a base estruturada contêm dados pessoais e de processo
criminal. O `.gitignore` exclui `data/`, as pastas `processo_*` e arquivos
`.pdf`, `.sqlite` e `.npy`. Não os adicione ao repositório.
