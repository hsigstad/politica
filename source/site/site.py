# INTENT: declare the politica static site — a docs-plus-data portal — and hand
# it to sitekit's empirical archetype.
# REASONING: politica is a data-cleaning PIPELINE (no paper/talk), but it ships a
# browsable data portal: the empirical archetype reads source.summary.config
# (SOURCES + DATASETS) and the summary cache to build a source-card landing grid,
# per-source overview pages, and per-table pages (columns, grain check, example
# rows, coverage-by-year). This file only names the context docs + landing guide;
# the portal content comes from the summary config. Deploy is UNGATED — the repo
# is public (github.com/hsigstad/politica) and the cache masks individual CPFs.
# ASSUMES: source/summary/config.py + cache/*.json exist (run summary/build_all).
from __future__ import annotations

from pathlib import Path

from sitekit import SiteConfig

PROJECT_ROOT = Path(__file__).parent.parent.parent


# (rel_path, title, description, category) — context docs alongside the portal.
DOC_REGISTRY = [
    ("docs/summary.md",  "Pipeline Summary",     "What politica cleans and how the stages fit together", "Overview"),
    ("docs/data.md",     "Data (state of play)", "Sources, cleaned outputs, coverage and the politico_id person key", "Overview"),
    ("docs/reference/poll_relatorio_2024.md", "2024 Poll Relatório", "The 2024 poll relatório LLM extraction — schema and coverage", "Reference"),
    ("docs/decisions.md", "Key Decisions",       "Design decisions and their rationale",                 "Working notes"),
    ("docs/thinking.md",  "Open Questions",       "Ideas and unresolved questions",                      "Working notes"),
    ("docs/todo.md",      "Active Tasks",         "Open work items",                                      "Tasks"),
    ("docs/done.md",      "Completed Tasks",      "Finished work items",                                  "Tasks"),
]


# (rel_path, href, label, description, priority, priority_class)
GUIDE_BRIEFS = [
    ("docs/summary.md", "docs/summary.html",
     "Pipeline Summary",
     "What politica cleans (TSE open data &rarr; relational tables) and the stage-by-stage flow.",
     "Start here", "priority-start"),
    ("docs/data.md", "docs/data.html",
     "Data — state of play",
     "Cleaned outputs, campaign-finance coverage, and the <code>politico_id</code> cross-cycle person key. The data portal below has a page per table.",
     "Then this", "priority-main"),
]


config = SiteConfig(
    project_root=PROJECT_ROOT,
    project_title="politica",
    paper_title="",
    archetype="empirical",
    doc_registry=DOC_REGISTRY,
    guide_briefs=GUIDE_BRIEFS,
    # Preserve reference/ subpaths so relative doc-to-doc links resolve.
    folder_mode_subdirs=("reference",),
    folder_mode_auto_discover=False,
    # Data portal: link each table's "Source:" line to its rendered script page.
    inject_dataset_source_link=True,
    # Declared order (candidato first) rather than alphabetical.
    dataset_iteration_order="declared",
    # No paper — repurpose the hero placeholder.
    paper_placeholder_msg=(
        "No paper &mdash; this is a data-cleaning <b>pipeline</b>. "
        "Browse the source cards and per-table data pages below."
    ),
    # This pipeline has no AN pages, cite-refs, anecdotes, or hypotheses docs.
    enable_an_pages=False,
    enable_cite_refs=False,
    enable_anec_refs=False,
    enable_hyp_refs=False,
    # No paper-sense figures/tables — the data portal is the content.
    build_descriptives=False,
    build_tables=False,
    extra_nav_css=(
        ".md-body pre { white-space: pre-wrap; overflow-wrap: anywhere; }"
    ),
)
