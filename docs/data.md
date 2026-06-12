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
  poll (composite-key filenames). Not committed (292 MB); see external-mirror below.

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

### external-mirror
Both outputs are mirrored alongside the source relatórios at
`EXTERNAL_MIRROR`:
- `poll_relatorio_2024.parquet` (the table above).
- `poll_relatorio_cache.tar.zst` (the raw JSON cache, 292 MB → 21 MB;
  restore with `tar --use-compress-program='zstd -d' -xf` → `poll_relatorio/`).

### Coverage and known gaps

The 2024 mayoral poll registration universe is **14,876 protocols** (per-UF
`pesquisa_eleitoral_2024_*.csv`). Coverage at each step:

**Scrape (`source/scrape/tse_relatorio.py`, on disk at
`projects/REDACTED-PROJECT/build/scrape/tse_relatorio/2024/`):**
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
- 110 additional protocols (48 AC + 62 AL + 1 stray) sit in the legacy-pilot
  legacy pilot cache at
  `projects/REDACTED-PROJECT/build/llm/poll_relatorio/{PROTOCOL}.json`
  — written before the extractor moved into politica (2026-05-28).
  These are picked up automatically by `assemble_long_table()`'s
  legacy fallback and by `extract_poll_relatorio`'s
  `_read_legacy_pilot()`. They count as `cached` hits on re-runs even
  though they're not under `CANONICAL_CACHE_DIR` — so an inventory of
  the new cache by `_cache_meta.doc_id` will show 0 AC entries even
  though AC is fully covered. **Don't read the new-cache file
  distribution as a coverage report;** use the parquet.
- SP (1,635 PDFs) was extracted earlier on a separate host; that cache lives
  on a separate host only. The laptop-assembled parquet therefore has 0 SP
  rows. The a separate host parquet has SP merged in.

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
