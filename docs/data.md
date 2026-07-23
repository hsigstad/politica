# Data

## Input: TSE election data

### Source
- provider: Tribunal Superior Eleitoral (TSE)
- access: publicly available election data files

### Coverage
- Brazilian elections (federal, state, municipal)

## Output: Cleaned CSVs

### Location
- `build/clean/candidato.csv` — candidate-level data
- `build/clean/politico.csv` — politician-level data (deduplicated across elections)
- `build/clean/bem.txt` — asset declaration data (completion flag)
- `build/clean/receita.txt` — campaign revenue data (completion flag)
- `build/clean/eleicao.csv` — election results

### Campaign-finance coverage (receita / despesa)

- **receita** (`source/clean/receita.py` → `build/clean/receita_{year}.csv`):
  candidate donations for **all cycles 2002–2024**. Column names are harmonized
  across schema eras in `get_cols()`. 2010 has no consolidated national file, so
  all `candidato/{UF}/` partitions are concatenated. 2002 & 2006 carry no
  candidate CPF in-file (only a committee CNPJ); CPF is recovered by joining
  `consulta_cand` on `(SQ_CANDIDATO, SG_UE)` — see `add_cpf_via_sq_ue` (~99%
  match; SQ alone is not unique pre-2012, so the electoral unit is required).
- **despesa** — two families by schema era:
  - Post-2018 contratada/paga split (`despesa_contratada.py`, `despesa_paga.py`
    → `build/clean/despesa_{contratada,paga}.csv`): **2018, 2020, 2022, 2024**.
    Each row is tagged with CPF/`SQ_CANDIDATO` via a `SQ_PRESTADOR_CONTAS` merge
    to that year's receita file.
  - Pre-2018 single despesa file (`despesa.py` →
    `build/clean/despesa_{year}.csv`): **2002, 2004, 2006, 2008, 2010, 2012,
    2014, 2016** (all pre-2018 cycles). CPF recovery by schema: name-based
    `add_cpf_2004` for 2004; the `(SQ_CANDIDATO, SG_UE)` `add_cpf_via_sq_ue` for
    2002/2006/2008; 2010/2012/2014/2016 carry CPF in-file. Per-year totals track
    the matching receita totals (in ≈ out). 2016's despesas were re-fetched from
    TSE (`prestacao_contas_final_2016.zip`) on 2026-07-17 — the earlier snapshot
    had header-only despesa files. A `len(df)==0` guard in `despesa.py` skips any
    header-only source rather than writing a silent 0-row output.

### `politico_id` — cross-cycle person identifier

`politico_id` is the unified person key used across `candidato.csv` and
`politico.csv`. It is a **hybrid identifier** built in
`source/clean/candidato_politico.py`:

```
politico_id = CPF            when CPF is available
            = 'T' + titulo   otherwise (titulo eleitoral, digits only)
```

The "T" prefix marks titulo-based fallback IDs. A `politico_id` without "T"
is a CPF; one with "T" is a titulo eleitoral.

**Coverage by period:**

| Period    | CPF available? | `politico_id` basis | Notes |
|-----------|---------------|---------------------|-------|
| 1998–2000 | No            | T + titulo          | TSE files lack CPF entirely |
| 2002–2022 | Yes (~100%)   | CPF                 | Gold-standard person key |
| 2024      | Redacted      | CPF (~50%), T + titulo (~50%) | CPF recovered via titulo→CPF crosswalk built from 1998–2022 data; remaining candidates fall back to titulo |

**Reliability as a unique person identifier:**

- **CPF-based IDs** (no "T" prefix): reliable across cycles. CPF is unique
  per person in Brazil; same person in different elections gets the same
  `politico_id`.
- **Titulo-based IDs** ("T" prefix): best-effort. Titulo eleitoral is
  generally stable per person, but can change on re-registration or
  interstate transfer. The same person could in principle get two different
  T-prefixed IDs across cycles. Cross-cycle linkage for T-prefixed records
  is not guaranteed.

**Deduplication:** `politico.csv` is deduplicated on `politico_id` (one row
per person, keeping first occurrence across all election years).
`candidato.csv` retains all candidate-year appearances.

**Known limitation:** No fuzzy matching (name, birthdate, municipality) is
applied. Politicians whose CPF is unavailable in one cycle and whose titulo
changed between cycles will appear as separate persons.

## Output: proposta de governo (candidate manifesto text)

Full text of every mayoral candidate's *proposta de governo* — the
government plan / manifesto that majoritarian candidates are legally
required to file with their candidacy registration (Lei 9.504/1997 art. 11
§1 IX). Among municipal offices only *prefeito* files one, so this table is
implicitly mayor-only. Produced by `source/clean/proposta_governo.py`.

### Location
- `build/clean/proposta_governo.parquet` — one row per candidate plan.
- `data/proposta_governo_ocr_cache/{basename}.txt` — per-PDF OCR cache
  (gitignored; beside the raw data so a `build/` wipe does not force
  re-OCR). Override with `PROPOSTA_GOVERNO_OCR_CACHE`.

### Source
- provider: TSE, Portal de Dados Abertos (`proposta_governo` dataset,
  linked from the per-year candidatos dataset). Bulk per-UF zips at
  `cdn.tse.jus.br/estatistica/sead/odsele/proposta_governo/proposta_governo_{YEAR}_{UF}.zip`.
- staged (gitignored) at `data/proposta_governo/`; override with
  `PROPOSTA_GOVERNO_RAW`. The TSE CDN is blocked from the sandbox — pull
  the zips on a machine with open egress.
- coverage: **2012, 2016, 2020, 2024**; 26 UFs per year (no DF — Brasília has
  no prefeitura), except 2016 = 25 (one UF zip missing — TODO). Each zip holds
  `{UF}/{YEAR}{UF}{SQ}.pdf` (2012/2016/2020) or `{YEAR}{UF}{SQ}_{NN}.pdf`
  (2024, `_NN` = document part), plus a `LEIAME.pdf` readme that is skipped.

### Unit of observation
One row per **(year, estado, SQ_CANDIDATO)** — one plan per mayoral
candidate. **65,271 plans** (2012: 17,608; 2016: 14,671; 2020: 17,432;
2024: 15,560) from 65,563 source PDFs. Multi-part 2024 plans (`_01`, `_02`, …)
are reassembled: text concatenated in sequence order, `n_docs` records how
many parts. **~9,300 plans are image-only scans awaiting OCR** (`text_source`
contains `sparse`; older cycles are scan-heavy — 2012: 4,532, 2016: 2,183,
2020: 1,566, 2024: 1,016); the rest carry an embedded text layer.

### Join key
`SQ_CANDIDATO` (nullable Int64) joins `candidato.csv` on **(year, estado,
SQ_CANDIDATO)**. **Cast note:** `candidato.csv` stores `SQ_CANDIDATO` as float
(e.g. `10000854328.0`); cast before merging —
`candidato['SQ_CANDIDATO'].astype('Int64')`. Match rate by cycle: 2024 99.0%,
2020 96.7%, 2016 94.5%, **2012 82.7%**. The residual are withdrawn /
*indeferido* candidacies and candidato.csv vintage — **plus, for 2012, a
known SQ-scheme boundary**: for a subset of 2012 the filename `SQ` is not
`candidato`'s `SQ_CANDIDATO` (the pre-2012 per-município SQ era, before
`SQ_CANDIDATO` became nationally unique). Treat 2012 joins with care; 2016+
are clean.

### Columns
- `year`, `estado` (UF), `SQ_CANDIDATO` — identity / join key.
- `n_docs` — number of source PDFs reassembled (1 for all of 2020).
- `n_pages`, `n_chars` — size of the plan.
- `text_source` — where the final text came from: `embedded` (PDF text
  layer), `ocr` / `ocr_cache` (image-only scan, tesseract `por`),
  `embedded_sparse` (scan seen under `--no-ocr`, awaiting OCR), or `error`.
  Multi-part plans mixing sources show e.g. `embedded+ocr`.
- `extract_error`, `source_file` (`;`-joined for multi-part) — provenance.
- `text` — the extracted plan text.

### OCR
Image-only scans (embedded text < 100 chars/page) are OCR'd in-process
(PyMuPDF render → tesseract `por`, staged at `data/tessdata/`). OCR output
is cached per PDF, so only unseen scans are OCR'd on a re-run; `--refresh-ocr`
rewrites the cache, `--no-ocr` skips OCR for a fast text-only pass.

## Output: SQLite database

### Location
- `build/insert/politica.db`

### Tables
- candidato: candidate-election level data
- politico: politician-level data
- bem: asset declarations
- receita: campaign revenue
- eleicao: election results

## Output: 2024 poll relatório LLM extractions

Per-candidate vote intentions extracted from the 2024 TSE-registered poll
relatório PDFs (`pesquisa_eleitoral`). Produced by `source/llm/poll_extract.py`
(runner) via `source/llm/poll_relatorio.py` (llmkit wrapper); schema in
`source/llm/schemas.py` (`PollRelatorio`, `schema_version = "v1"`).

### Location
- `build/llm/poll_relatorio_2024.parquet` — assembled long table.
- `build/llm/poll_relatorio/<hash>.json` — raw llmkit cache, one file per
  poll (composite-key filenames). Not committed (292 MB); see the external
  mirror below.

### Unit of observation
One row per **candidate × scenario × poll**. 149,934 rows from 8,169 distinct
polls across 25 states.

### Columns
- `protocol` — TSE protocol, compact form (e.g. `PE004282024`); join key to
  the registration CSVs and relatório PDFs.
- `tse_protocol_display` — human-readable protocol (e.g. `PE-00428/2024`),
  echoed from the PDF for join-back validation.
- `scenario_type` — controlled vocabulary: `espontaneo`, `estimulado`,
  `votos_validos`, `rejeicao`, `avaliacao_governo`,
  `segundo_turno_simulacao`, `outro` (a few stray buckets like
  `expectativa_vitoria` leak from `outro`; treat anything outside the seven
  as `outro`).
- `scenario_label` — exact label as printed in the PDF.
- `candidate_name` — candidate display name; aggregate rows carry descriptive
  labels (`Branco/Nulo`, `Não sabe`, ...).
- `party` — party abbreviation when shown next to the name, else null.
- `percent` — vote-intention percentage in that scenario, 0–100.
- `extraction_notes` — per-poll note on any ambiguity or judgment call.
- `source` — extraction provenance tag (`llmkit`).

### External mirror
Both outputs are mirrored alongside the source relatórios on external
storage:
- `poll_relatorio_2024.parquet` (the table above).
- `poll_relatorio_cache.tar.zst` (the raw JSON cache, 292 MB → 21 MB;
  restore with `tar --use-compress-program='zstd -d' -xf` → `poll_relatorio/`).

### Coverage and known gaps

The 2024 mayoral poll registration universe is **14,876 protocols** (per-UF
`pesquisa_eleitoral_2024_*.csv`). Coverage at each step:

**Scrape (`source/scrape/tse_relatorio.py`):** the canonical complete
PDF set (all 11,372) is archived on the project's shared Dropbox under
`data/TSE/2024/pesquisa_eleitoral/relatorios/` (per-UF
`.tar.zst` + `_logs.tar.zst` with the `_runlog.jsonl`). The local
`build/scrape/tse_relatorio/2024/` dir is a partial working copy and may
hold fewer — pull from Dropbox when you need the full set. Counts below
are the logical (complete) dataset:
- 11,372 PDFs downloaded.
- 3,415 protocols have no relatório uploaded to TSE (the divulgação
  portal returns an empty result; logged as `no_relatorio` in
  `_runlog.jsonl`). The scraper docstring acknowledges this — ~2020-era
  polls and a minority of 2024 polls were never published. Not
  recoverable from TSE; treat as missing-at-source.
- 89 protocols hit transient portal/network errors (logged as `error`).
  Re-running the scraper picks these up; they queue at the end of the
  worklist.

**LLM extraction (`source/llm/poll_extract.py`):**
- The new-format llmkit cache at `build/llm/poll_relatorio/` has 9,325
  entries from a single bulk run on 2026-06-01 (10:20–15:12 UTC,
  `gpt-4o-mini`, all UFs except SP).
- 110 additional protocols (48 AC + 62 AL + 1 stray) sit in a legacy
  pilot cache (`{PROTOCOL}.json`), written before the extractor was
  migrated to llmkit.
  These are picked up automatically by `assemble_long_table()`'s
  legacy fallback and by `extract_poll_relatorio`'s
  `_read_legacy_pilot()`. They count as `cached` hits on re-runs even
  though they're not under `CANONICAL_CACHE_DIR` — so an inventory of
  the new cache by `_cache_meta.doc_id` will show 0 AC entries even
  though AC is fully covered. **Don't read the new-cache file
  distribution as a coverage report;** use the parquet.
- SP (1,635 PDFs) was extracted earlier on a separate host; that cache
  lives on that host only. The parquet assembled elsewhere therefore has
  0 SP rows. The parquet assembled on that host has SP merged in.

Of the 9,737 non-SP PDFs on disk, the parquet covers ~8,169 distinct
polls (149,934 candidate-scenario rows across 25 states). The
~1,500-protocol gap is dominated by image-only PDFs that the
`pdftotext` gate skips at `MIN_TEXT_CHARS = 200`:

| UF | PDFs | image-only | extractable | in parquet |
| --- | --- | --- | --- | --- |
| TO | 475 | 157 | 318 | 275 |
| SE | 373 | 39 | 334 | (per parquet) |
| ES | 342 | 15 | 327 | (per parquet) |
| RS | 205 | 15 | 190 | (per parquet) |
| AL | 148 | 5 | 143 | 130 |
| AC | 48 | 1 | 47 | 46 |

TO image-only is the heaviest — 157 scanned institute reports, would
need OCR to recover. The small remaining shortfalls (e.g. AC 47→46,
AL 143→130, TO 318→275) are schema-validation drops at parquet-assembly
time (the assembler silently drops entries that don't validate against
`PollRelatorio`); the cache itself has them. Re-running the extractor
on these UFs does not recover them — the prompt would have to be fixed.

## Output: pollingdata.com.br poll archive (president / governor / senate)

### Source
- provider: pollingdata.com.br (public poll aggregator; static site)
- scraper: `source/scrape/pollingdata_acervo.py` reads the master election
  index, then for each election fetches the archive page → embedded data
  widget and parses the per-poll reactable payload. One parquet per election
  under `build/scrape/pollingdata_acervo/` (`_index.csv` lists all elections).
- cleaner: `source/clean/poll_response_pollingdata.py` →
  `build/clean/poll_response_pollingdata.parquet`.

### Unit of observation
- one row per (election, poll, scenario, candidate): the candidate's vote
  intention. Aggregate rows ("Não Válido") kept and flagged (`is_aggregate`);
  `pct_on_real` = share among non-aggregate candidates.

### Key fields
- `protocolo` — TSE registration number (e.g. `BR-05339/2022`); join key to the
  TSE poll registry for sponsor / methodology.
- `poll_date`, `institute` (+ `institute_raw`), `mode`, `sample_size`,
  `cenario`, `candidate`, `party`, `pct`, `year`, `office`, `uf`, `turno`.

### Coverage (initial pull, 2026-07)
- president + governor, 2018 + 2022 = 135 elections, ~1.6k polls, 148 institutes
  (Ipec, Paraná, Quaest, Ipespe, DataPoder360, Datafolha, Real Time, Atlas, …).
- 2022 president alone: 823 polls (national + 27 states), 2019→Oct-2022.
- Extend to senate / other cycles via the scraper's `--offices` / `--years` flags.
