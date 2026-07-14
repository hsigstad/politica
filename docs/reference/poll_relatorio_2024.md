# 2024 TSE poll relatório — extractions and source PDFs

Per-candidate vote intentions extracted from the 2024 TSE-registered
electoral poll relatórios (mayoral races). This README accompanies the
shareable artifacts on the external data mirror.

Produced by the politica pipeline
(<https://github.com/hsigstad/politica>) — runner
`source/llm/poll_extract.py`, wrapper `source/llm/poll_relatorio.py`,
schema `source/llm/schemas.py` (`PollRelatorio`, `schema_version="v1"`).

## What's in the bundle

```
pesquisa_eleitoral/
  relatorios/
    <UF>.tar.zst                       per-UF tarball of source PDFs
                                       (compact protocol filenames)
  extractions/
    poll_relatorio_2024.parquet        assembled long table (this README's
                                       primary deliverable)
    poll_relatorio_cache.tar.zst       raw per-poll LLM JSON cache
                                       (292 MB → 21 MB compressed)
    README.md                          this file
```

Restore the JSON cache with:
```bash
tar --use-compress-program='zstd -d' -xf poll_relatorio_cache.tar.zst
# → poll_relatorio/<hash>.json  (one file per extraction, content-hashed)
```

## The parquet

`poll_relatorio_2024.parquet` — **149,934 rows**, one per
*(candidate × scenario × poll)*, from **8,169 distinct polls across
25 states**.

| column                  | type   | description                                                                                  |
| ----------------------- | ------ | -------------------------------------------------------------------------------------------- |
| `protocol`              | str    | TSE protocol, compact form (e.g. `PE004282024`). Join key to registration CSVs and PDFs.     |
| `tse_protocol_display`  | str    | Human-readable protocol (e.g. `PE-00428/2024`); echoed from the PDF for join-back validation.|
| `scenario_type`         | str    | One of: `espontaneo`, `estimulado`, `votos_validos`, `rejeicao`, `avaliacao_governo`, `segundo_turno_simulacao`, `outro`. A few stray buckets like `expectativa_vitoria` leak from `outro`; treat anything outside these seven as `outro`. |
| `scenario_label`        | str    | Exact label as printed in the PDF.                                                            |
| `candidate_name`        | str    | Candidate display name; aggregate rows carry descriptive labels (`Branco/Nulo`, `Não sabe`, …). |
| `party`                 | str?   | Party abbreviation when shown next to the name, else null.                                   |
| `percent`               | float  | Vote-intention percentage in that scenario, 0–100.                                           |
| `extraction_notes`      | str?   | Per-poll note on any ambiguity or judgment call.                                             |
| `source`                | str    | Extraction provenance tag: `llmkit` (2026-06-01 bulk run) or `legacy_pilot`.                  |

Load:
```python
import pandas as pd
df = pd.read_parquet("poll_relatorio_2024.parquet")
```

## How it was built

1. **Scrape.** `source/scrape/tse_relatorio.py` iterates the
   per-UF registration CSVs (`pesquisa_eleitoral_2024_<UF>.csv` from
   <https://dadosabertos.tse.jus.br>) and downloads the
   "Relatório completo com o resultado de pesquisa" PDF for each
   mayoral protocol from the TSE divulgação portal
   (<https://pesqele-divulgacao.tse.jus.br>). One file per protocol,
   under `build/scrape/tse_relatorio/2024/<PROTOCOL>.pdf`. Idempotent;
   logs to `_runlog.jsonl`.
2. **Extract.** `source/llm/poll_extract.py` runs each PDF through
   `gpt-4o-mini` via `llmkit`. The wrapper checks the cache first
   (composite key of protocol + text-hash + model), falls back to an
   in-house legacy cache (the legacy pilot, see below), and only calls the
   LLM on a true miss. Image-only PDFs (`pdftotext` output below
   `MIN_TEXT_CHARS = 200`) are skipped — OCR is future work.
3. **Assemble.** `assemble_long_table()` walks the new-format cache,
   then the legacy pilot cache, deduplicating by `protocol`. Entries
   that fail validation against `PollRelatorio` are dropped (warned).
   Output: the parquet above.

Bulk LLM run: 2026-06-01, 10:20–15:12 UTC, `gpt-4o-mini`, 8 workers,
all UFs except SP. SP was extracted earlier on a separate host.

## Coverage and known gaps

The 2024 mayoral poll **registration universe is 14,876 protocols**
(per-UF CSVs from TSE). Coverage at each step:

### Scrape: 11,372 PDFs (76.4% of universe)

| status                | count  | notes                                                       |
| --------------------- | ------ | ----------------------------------------------------------- |
| downloaded            | 11,372 | one PDF per protocol, on disk under `build/scrape/`         |
| no relatório uploaded | 3,415  | TSE portal returns empty for these protocols                |
| transient errors      | 89     | network/portal hiccups; queue at end of `_runlog.jsonl`     |

The "no relatório uploaded" gap is **at the source** — TSE does not
publish a relatório for every registered poll. The scraper's docstring
expects this; ~80% of registered polls have a downloadable relatório.
The 89 transient errors are recoverable by re-running.

### LLM extraction: 8,169 distinct polls in the parquet

The non-SP universe is 9,737 PDFs (11,372 total minus SP's 1,635).
The gap from 9,737 PDFs down to the parquet's polls is dominated by
image-only PDFs that the `pdftotext` gate skips
(`MIN_TEXT_CHARS = 200`):

| UF | PDFs | image-only | extractable | in parquet |
| --- | ---- | ---------- | ----------- | ---------- |
| TO  | 475  | 157        | 318         | 275        |
| SE  | 373  | 39         | 334         | (per parquet) |
| ES  | 342  | 15         | 327         | (per parquet) |
| RS  | 205  | 15         | 190         | (per parquet) |
| AL  | 148  | 5          | 143         | 130        |
| AC  | 48   | 1          | 47          | 46         |

TO image-only is the heaviest; those are scanned institute reports
that would need OCR to recover. The small remaining shortfall per UF
(e.g. AC 47→46, TO 318→275) is the schema-validation drop at parquet
assembly — those entries are in the cache but did not validate against
`PollRelatorio.v1`.

### SP is *not* in the parquet from this bundle

This parquet has 0 SP rows. SP (1,635 PDFs) was extracted earlier on a
separate host; that JSON cache lives on that host only. If you need SP,
the parquet assembled on that host has it merged in.

### The legacy pilot cache

The first 111 protocols (48 AC + 62 AL + 1 stray) were extracted with
the pre-llmkit script, before the extractor was migrated to llmkit.
Those JSON files (`{PROTOCOL}.json`, in the
old in-house format) are bundled into `poll_relatorio_cache.tar.zst`
under a separate subdirectory. The assembler reads both formats; the
`source` column tags rows accordingly (`legacy_pilot` vs. `llmkit`).

## Quality caveats

- **Spot-checked, not row-by-row validated.** A 102-protocol pilot was
  audited against source PDFs (see `docs/done.md` 2026-06-01 entry in
  the politica repo) — 9% of espontaneo/estimulado sub-scenarios
  deviate from 100% sum by more than ±5pp. Six are *all-zero*
  sub-scenarios (low text quality / unusual table layouts); the rest
  are 105–115% sums consistent with rounding in the source.
- **Aggregate rows** (`Branco/Nulo`, `Não sabe`, etc.) are present
  with descriptive labels in `candidate_name`. Filter them out if you
  need only candidate-level rows.
- **One schema-invalid entry** in the 2026-06-01 bulk cache is silently
  dropped at assembly. The cache and parquet are otherwise consistent.

## Reproducing this

Setup is documented in the politica repo's README. The end-to-end
recipe, given the per-UF registration CSVs already staged under
`$DATA_DIR/tse_polls_2024/`:

```bash
# 1. scrape PDFs (resumable; ~hours, gated by TSE rate limits)
python source/scrape/tse_relatorio.py --year 2024 --rate-seconds 1.5

# 2. extract (~5 hours wall, ~$10, 8 workers)
export OPENAI_API_KEY=sk-...
BASE_DIR=$PWD DATA_DIR="$DATA_DIR" \
  PYTHONPATH=/path/to/llmkit:$PWD/source/llm \
  python source/llm/poll_extract.py --year 2024 \
    --exclude-states SP --workers 8

# 3. assemble parquet (the runner does this automatically at the end of
#    a live pass; --validate-cached re-assembles without re-calling LLM)
python source/llm/poll_extract.py --year 2024 --validate-cached
```

## Contact

Henrik Sigstad — <h.sigstad@gmail.com>
BI Norwegian Business School, Department of Economics.
