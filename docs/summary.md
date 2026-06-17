# Summary

## What this pipeline does

Cleans and assembles Brazilian political data from TSE (Tribunal Superior
Eleitoral) into structured CSVs, a SQLite database, and analysis-ready
parquet files. Two sub-pipelines:

1. **Core political data** — candidates, assets, revenue, elections
   (1998–2024).
2. **2024 poll pipeline** — scrapes poll PDFs, extracts vote intentions
   via LLM, cleans, matches to candidate registry, and links sponsors.

## Core political data pipeline

### Pipeline stages

1. **Raw** (`source/raw/`): reference data (eleicoes.csv)
2. **Clean** (`source/clean/`): cleans TSE election data into structured CSVs
   - `candidato_politico.py` → `candidato.csv`, `politico.csv`
   - `bem.py` → asset declarations
   - `receita.py` → campaign revenue
   - `eleicao.py` → election results
   - `orgao_partidario.py` → party organs (members/positions)
   - `despesa_partidaria.py` → party expense filings
3. **Insert** (`source/insert/`): loads cleaned CSVs into SQLite
   (`build/insert/politica.db`)

### Build system

Uses SCons (`SConstruct`) to define the build graph for the core pipeline.

## 2024 poll pipeline

Not yet in SConstruct — run steps manually in order.

### Pipeline stages

```
source/scrape/tse_relatorio.py     Scrape poll PDF relatórios from TSE
        ↓
source/llm/poll_extract.py         LLM-extract vote intentions from PDFs
        ↓                          (via llmkit; see source/llm/schemas.py)
source/clean/poll_response_2024.py Join with TSE metadata + match candidates
        ↓                          to TSE registry (politico_id, cpf, party)
source/clean/poll_sponsor.py       Clean sponsor (contratante/pagante) data
                                   AND link sponsors to candidates via 4 routes:
                                     A: sponsor CPF = candidate CPF
                                     B: committee CNPJ name parse
                                     C: party directorate CNPJ (despesa_partidaria)
                                     D: party name from sponsor name
                                   Multi-year (YEARS=[2020, 2024]).
```

### Key outputs

| File | Description |
|------|-------------|
| `build/llm/poll_relatorio_2024.parquet` | Raw LLM extractions (long, one row per candidate×scenario×poll) |
| `build/clean/poll_response_2024.parquet` | Clean poll-response table with TSE metadata + candidate registry match |
| `build/clean/poll_sponsor_{year}.parquet` | Sponsor table with Routes A–D candidate classification (one row per sponsor per poll) |

### Data flow

The poll pipeline reads from the core pipeline (`candidato.csv`,
`politico.csv`, `despesa_partidaria.csv`) and from TSE registration
CSVs in `build/scrape/tse_polls_2024/`. See `docs/data.md` for column
schemas and external-mirror mirror locations.

### Downstream consumers

- `projects/DOWNSTREAM_PROJECT/` — within-candidate FE analysis
  of sponsor-driven poll bias
- `DOWNSTREAM_PROJECT` — polling effects of REDACTED filings ([an])
- `projects/REDACTED-PROJECT/` — 2024 poll assembly (wide format)
