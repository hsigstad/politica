# TODOs

- [ ] **Publish the 2024 poll relatório README alongside the mirrored artifacts**
  - source: `docs/poll_relatorio_2024_README.md`
  - action: copy it to the external mirror next to
    `poll_relatorio_2024.parquet` and `poll_relatorio_cache.tar.zst`
    (rename to plain `README.md` at the destination).
  - while there: verify the mirrored `poll_relatorio_2024.parquet` and
    `poll_relatorio_cache.tar.zst` are up-to-date against
    `build/llm/`. If stale, refresh them (parquet copy is direct; the
    cache needs a `tar --use-compress-program='zstd -19 -T0' -cf …
    poll_relatorio/` pack first).
  - created: 2026-06-12

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
  - todo: write a small audit pass over `poll_relatorio_2024.parquet`:
    flag protocols whose primary estimulado sub-scenario sums to <50%
    or >120%; sample 20 of these against their PDFs; if a systematic
    prompt fix surfaces, revise `prompts/poll_relatorio_system.txt` and
    re-extract *only* the flagged protocols via `--reextract` against a
    protocol list, not the full corpus.
  - non-blocking — flagged entries are a small fraction and can be
    re-extracted incrementally.
  - created: 2026-06-01

- [ ] **Extend `candidato.csv` clean step to cover 2024**
  - context: `build/clean/candidato.csv` covers 1998–2022 in the base
    build. The 2024 cycle is needed by downstream candidate-join tasks.
    Promote the 2024 candidate files into the pipeline so the candidato
    table includes 2024.
  - blocker: the 2024 candidato raw needs to be staged under
    `$DATA_DIR/consulta_cand_2024/` (per-UF zips).
  - created: 2026-06-01

- [ ] **Retire the legacy TRE-diários processo cleaning path once its consumer is repointable**
  - notes: this pipeline's `processo.py` now covers the same TSE bulk
    processo data the legacy script cleans, but the two outputs are not
    drop-in-equivalent (classe transform, assunto1..4 split, dedup). See
    `docs/decisions.md` 2026-05-26 entry for the schema diff and the
    migration recipe.
  - created: 2026-05-26
