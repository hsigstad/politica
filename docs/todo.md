# TODOs

- [ ] **Upload 2024 poll relatório README to external-mirror** *(non-sandbox Claude /
  manual)*
  - source: `pipelines/politica/docs/poll_relatorio_2024_README.md`
  - destination: `EXTERNAL_MIRROR`
    (rename to plain `README.md` at the destination — it sits alongside
    `poll_relatorio_2024.parquet` and `poll_relatorio_cache.tar.zst`).
  - command (when a Claude session with rclone external-mirror write rights is
    available):
    ```bash
    rclone copyto \
      pipelines/politica/docs/poll_relatorio_2024_README.md \
      EXTERNAL_MIRROR
    ```
  - sandbox Claude does not have external-mirror write rights, so this has to
    happen from a host session (the laptop Claude with `rclone`
    configured) or be done manually.
  - while there: verify that `poll_relatorio_2024.parquet` and
    `poll_relatorio_cache.tar.zst` at the same destination are
    up-to-date against `pipelines/politica/build/llm/`. If they are
    stale, refresh them too (parquet copy is direct, cache needs the
    `tar --use-compress-program='zstd -19 -T0' -cf … poll_relatorio/`
    pack first).
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
  - todo (now that the bulk run is done — see `done.md` 2026-06-01):
    write a small audit pass over `poll_relatorio_2024.parquet`:
    flag protocols whose primary estimulado sub-scenario sums to <50%
    or >120%; sample 20 of these against their PDFs (via a separate host);
    if a systematic prompt fix surfaces, revise
    `prompts/poll_relatorio_system.txt` and re-extract *only* the
    flagged protocols via `--reextract` against a protocol list, not
    the full corpus.
  - non-blocking — flagged entries are a small fraction and can be
    re-extracted incrementally.
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

- [ ] **Retire LEGACY_TRE_DIARIOS `tse_processos.py` once paper is post-acceptance**
  - notes: politica's `processo.py` now covers the same TSE bulk processo
    data the LEGACY_TRE_DIARIOS script cleans, but the two outputs are not
    drop-in-equivalent (classe transform, assunto1..4 split, dedup). See
    `docs/decisions.md` 2026-05-26 entry for the schema diff and the
    migration recipe. Live consumer:
    `projects/REDACTED-PROJECT/source/query/proc__tse.py`.
  - created: 2026-05-26

- [ ] **Token stopword filter on the candmatch ladder** *(small
      follow-up to the 2026-06-14 matcher pass; see done.md)*
  - context: after the three-fix matcher pass, the top score-1
    `match_method` rows in `poll_2024.parquet` are
    `tokens_full=DE` (338), `tokens_full=DA` (179),
    `tokens_urna=DR` (119), `=DE` (79), `=DO` (69) — Portuguese
    articles, plus `DR` (an honorific that survives on the registry
    side because we only strip from the poll side). They're already
    downstream-filtered (`match_score >= 2`), but they bloat
    `n_match_candidates` and the score-1 layer of the parquet. Add
    a small stopword set (`{DE, DA, DO, DOS, DAS, E, DR, DRA,
    PROF, PROFA}`) to `_score_name`'s token-overlap computation so
    these tokens don't contribute to `shared`. Non-blocking.
  - created: 2026-06-14
