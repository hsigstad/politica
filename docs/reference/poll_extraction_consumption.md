# Poll extraction — consumption rules

How to consume the `poll_*` LLM extractions correctly. These encode the
residual, faithful-but-recoverable quirks the dev-set QC (2026-10-20)
confirmed. Each is a downstream derivation — the extractions deliberately
stay raw (extract-what-is-there; derive the rest), see `decisions.md`.

## 1. `poll_questionario` — a "real" estimulada requires a roster
Some pollsters label non-vote-intention blocks "(ESTIMULADA)" (vote-certainty,
"who will win?", even demographics). The extractor faithfully records the
block's `question_type` and verbatim `question_text`, but a block with no
candidate list has `candidates_listed == []`. So:

> **Count a block as an estimulada vote-intention scenario only when
> `question_type == "estimulada"` AND `candidates_listed` is non-empty.**

Derive `first_estimulada_position`, the headline label, and the
vote-intention count from blocks that pass that filter. The name-order /
priming lever keys on estimulada blocks *with* a roster anyway.

## 2. `poll_sampling` — quota distributions: counts vs percentages
A quota dimension is reported either as interview COUNTS or PERCENTAGES:
- `bin_percentages` populated → shares (sum ~100).
- `bin_counts` populated, `bin_percentages == []` → the source gave counts
  (sum ~n); convert to shares with `bin_counts / sum(bin_counts)` if you need
  percentages.
Also: ~12% of non-income (age/education) distributions come from sex×age
cross-tabs and may not sum to ~100. **Flag any quota distribution whose
`bin_percentages` sum is far from 100 before using it** (income is ~99% clean).
`quota_variables` is the full set of quota dimensions used — it is a superset
of the variables in `quota_distributions` (a dimension named without printed
bins appears only here).

## 3. `poll_bairro_detail` — dedup units by setor_code
Most PDFs are clean, but a few LLM outputs repeat a `setor_code` within the
`units` list (small one-row-per-setor tables). **Dedup `units` by `setor_code`
when consuming** (sum `n_entrevistas` across duplicates). Per-interview
setor-microdata PDFs are parsed deterministically at build
(`validation_status == "deterministic_microdata"` in the cache meta) — those
are already deduped and exact. `units_truncated == true` means the PDF had
more than 80 distinct units and the smallest were dropped. Name-tabular PDFs
with >80 bairros are complete (not truncated); the 80 cap binds only setores.

## Versions (post dev-set QC, 2026-10-20)
`poll_sampling` v3 · `poll_questionario` v4 · `poll_bairro_detail` v5 ·
`poll_weighting` v2 · `poll_operations` (control-measures escape hatch) ·
`poll_coverage` v1 (frozen) · `poll_relatorio` v1 (frozen). The batch build's
cache skip is version-aware (schema_version + prompt_hash), so re-running
after a change re-extracts only the changed tasks.
