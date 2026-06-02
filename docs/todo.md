# TODOs

- [ ] **Bulk poll-relatório LLM extraction (all UFs except SP)**
  - context: SP already extracted on a separate host; remaining ~25 UFs are
    queued (9,737 PDFs). Migration to llmkit done (see `done.md`).
    Smoke test on 5 RR PDFs: $0.005 / 17s / 0 validation failures →
    extrapolated **~$9.74, ~60 min at 8 workers** for non-SP.
  - PDFs are accessible both on a separate host and on the laptop sandbox
    (the runner discovers them at
    `projects/REDACTED-PROJECT/build/scrape/tse_relatorio/2024/`
    as a fallback for the canonical politica location).
  - command (run inside `pipelines/politica/`; sources the OPENAI key
    from one of the project .env files):
    ```bash
    source ../../DOWNSTREAM_PROJECT && export OPENAI_API_KEY
    BASE_DIR=$PWD DATA_DIR=$PWD \
      PYTHONPATH=$PWD/source/llm \
      python source/llm/poll_extract.py \
        --year 2024 --exclude-states SP \
        --workers 8
    ```
  - output:
    - cache: `build/llm/poll_relatorio/{KEY}.json` (new-format llmkit
      entries with `_cache_meta`)
    - parquet: `build/llm/poll_relatorio_2024.parquet` (long, one row
      per candidate-scenario; assembled from cache after the live
      pass, merges in the SP a separate host cache + the 102-protocol legacy-pilot
      pilot via legacy fallback automatically).
  - after the run: run `source/clean/poll_2024.py` to join LLM
    extractions with TSE registry, then `source/clean/poll_sponsor_2024.py`
    (already laptop-DONE for sponsor side) joins downstream.
  - created: 2026-06-01

- [ ] **Rebuild `candidato.csv` to populate `nome_urna`** *(load-bearing
  for the 2024 poll → candidate matcher)*. Code is patched
  (2026-06-01) — `candidato_politico.py:get_candidate_column_mapping()`
  now maps `NM_URNA_CANDIDATO → nome_urna` and `main()` includes it in
  the candidato output cols; `poll_2024__candmatch.py:best_match()`
  scores `nome_urna` matches at 4 (above substring on legal name) and
  degrades gracefully when the column is missing. Remaining step is
  to re-run `candidato_politico.py` end-to-end. **Cannot run from the
  a separate host sandbox** — DATA_DIR (`$DATA_DIR`) raw
  TSE `consulta_cand_*.csv` files aren't reachable here. Run on the
  machine where DATA_DIR resolves, then rerun
  `source/clean/poll_2024__candmatch.py` to lift the polled-candidate
  identifier rate (currently 62% on politico_id; expected ~90% once
  `nome_urna` carries the aliases like "Fabinho Investigador",
  "Largatixa", "Vitinho do Deraldo").
  - created: 2026-05-28; code patched: 2026-06-01

- [ ] **Poll-extraction quality audit — flag zero-only and over-100% sub-scenarios**
  - context: surfaced by the migration smoke test against the
    102-protocol pilot. 9% of espontaneo/estimulado sub-scenarios
    (grouped by `protocol×scenario_type×scenario_label`) deviate from
    100% by more than ±5pp. ~6 of those are *all-zero* sub-scenarios
    (`AL013622024`, `AL022112024`, `AL039272024`, `AL043902024`,
    `AL047572024`) where the LLM returned candidates with 0% — likely
    PDFs with low text extraction quality or unusual table layouts.
    The rest are 105-115% sums consistent with rounding artifacts in
    the source poll reports.
  - todo: after the bulk run, write a small audit pass over
    `poll_relatorio_2024.parquet`: flag protocols whose primary
    estimulado sub-scenario sums to <50% or >120%; sample 20 of these
    against their PDFs (via a separate host); if a systematic prompt fix
    surfaces, revise `prompts/poll_relatorio_system.txt` and re-extract
    *only* the flagged protocols via `--reextract` against a protocol
    list, not the full corpus.
  - non-blocking for the bulk run — flagged entries are a small
    fraction and can be re-extracted incrementally.
  - created: 2026-06-01

- [ ] **Extend `candidato.csv` clean step to cover 2024**
  - context: `pipelines/politica/build/clean/candidato.csv` and the
    `data/tse/candidato.csv` snapshot both cover 1998–2022 only (see
    `data/tse/README.md`). The 2024 cycle has been needed by at least
    one downstream task — the `DOWNSTREAM_PROJECT` CPF→candidate
    join is blocked on laptop because of this (see that idea's
    "laptop findings" section). a separate host has the 2024 cand file as a
    one-off zip; promote it into the politica pipeline so the
    workspace-wide candidato table includes 2024.
  - blocker: the 2024 candidato raw needs to be staged under
    `$DATA_DIR/consulta_cand_2024/` (per-UF zips).
  - created: 2026-06-01

- [ ] **Stage a TSE partidos-CNPJ table for DOWNSTREAM_PROJECT Route C**
  - context: `poll_sponsor_2024_join.py` implements Route A (sponsor CPF
    → candidato.cpf, ~14 candidate matches) and Route B (committee-CNPJ
    name parse, ~1,372 PREFEITO matches). Route C — sponsor CNPJ that
    belongs to a *party* directorate → that party's PREFEITO candidate
    in this muni (1:1 by the electoral-law constraint we lean on for
    identification) — is the missing third route. The
    `DOWNSTREAM_PROJECT/a separate host_next_steps.md` playbook estimated
    ~728 protocols would match via this route, which would meaningfully
    grow the headline within-candidate overlap (currently 350).
  - scope: TSE dadosabertos distributes `vw_orgao_partidario_*.csv`
    or similar party-directorate tables alongside the candidate
    registry, keyed by (party, muni, year) with the CNPJ of the local
    diretório. Pull, normalize, write
    `build/clean/partidos_directorio_cnpj_2024.parquet` keyed by
    `(cnpj, year, uf, muni_id, party)`. Then extend
    `source/clean/poll_sponsor_2024_join.py` to add Route C: left-join
    sponsor CNPJ → directorate → party → match to candidato 2024
    PREFEITO row in same muni with that party.
  - blocker: the partidos-directorate raw needs to be staged
    (laptop sandbox has no access; EXTERNAL_MIRROR or a separate host network).
  - created: 2026-06-01

- [ ] **Retire LEGACY_TRE_DIARIOS `tse_processos.py` once paper is post-acceptance**
  - notes: politica's `processo.py` now covers the same TSE bulk processo
    data the LEGACY_TRE_DIARIOS script cleans, but the two outputs are not
    drop-in-equivalent (classe transform, assunto1..4 split, dedup). See
    `docs/decisions.md` 2026-05-26 entry for the schema diff and the
    migration recipe. Live consumer:
    `projects/REDACTED-PROJECT/source/query/proc__tse.py`.
  - created: 2026-05-26
