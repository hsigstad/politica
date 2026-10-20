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

import html as _html
from pathlib import Path

from sitekit import SiteConfig

PROJECT_ROOT = Path(__file__).parent.parent.parent


# --- Project-local hook: render source/llm/prompts/*.txt as browsable pages ---
# REASONING: sitekit's per-line source renderer only covers .py/.R/.sh/.sql, so
# the LLM extraction prompts (plain .txt) never reach the site even though the
# extractor code + schemas do. Coauthors reviewing an extraction want to read the
# exact prompt text. We keep this scoped to politica rather than widening the
# shared _PERLINE_EXTS, which would sweep every .txt in the workspace.
# ASSUMES: the bundled doc.html template exposes INJECT_TITLE / INJECT_CONTENT and
# nav.inject_nav rewrites INJECT_NAV (the same contract the perline renderer uses).

_PROMPTS_REL = Path("source/llm/prompts")

_PROMPT_LISTING_CSS = """
<style>
.prompt-listing{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:.82rem;line-height:1.55;overflow-x:auto;border:1px solid var(--border,#d0d7de);
  border-radius:6px;padding:.6rem .2rem;background:var(--code-bg,#f6f8fa)}
.prompt-line{display:block;white-space:pre-wrap;overflow-wrap:anywhere}
.prompt-ln{display:inline-block;width:3em;text-align:right;margin-right:.8em;
  color:#9aa0a6;text-decoration:none;-webkit-user-select:none;user-select:none}
@media (prefers-color-scheme:dark){.prompt-listing{background:#161b22}}
</style>
"""


def _render_prompt_pages(ctx):
    """Render each source/llm/prompts/*.txt as its own line-numbered page plus
    a small "LLM prompts" index page. Returns an extra_docs_info entry so the
    index links into an "LLM prompts" category group."""
    from sitekit.nav import inject_nav
    from sitekit.templates import read_template

    prompts_dir = ctx.project_root / _PROMPTS_REL
    if not prompts_dir.is_dir():
        return {}

    template = read_template(ctx.config, "doc.html")
    out_dir = ctx.site_dir / _PROMPTS_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    # Depth source/llm/prompts/<x>.html -> 3 dirs back to site root.
    prefix = "../" * len(_PROMPTS_REL.parts)

    txts = sorted(prompts_dir.glob("*.txt"))

    def _page(title, content):
        page = template.replace("<!-- INJECT_TITLE -->", title)
        page = page.replace("<!-- INJECT_CONTENT -->", content)
        return inject_nav(page, ctx, prefix=prefix, active="")

    # Per-prompt pages.
    for path in txts:
        rel = path.relative_to(ctx.project_root)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        n_width = max(2, len(str(len(lines))))
        listing = '<pre class="prompt-listing">' + "".join(
            f'<span class="prompt-line" id="L{i}">'
            f'<a class="prompt-ln" href="#L{i}">{i:>{n_width}}</a>'
            f'{_html.escape(line) or " "}'
            f'</span>'
            for i, line in enumerate(lines, start=1)
        ) + "</pre>"
        content = (
            f'<p>Prompt: <code>{rel}</code> '
            f'(<a href="index.html">back to prompt index</a>)</p>'
            f'{_PROMPT_LISTING_CSS}{listing}'
        )
        (out_dir / f"{path.stem}.html").write_text(
            _page(str(rel), content), encoding="utf-8")

    # Index page: group by base task, pairing system/user prompts.
    groups: dict[str, dict[str, str]] = {}
    for path in txts:
        stem = path.stem
        if stem.endswith("_system"):
            base, role = stem[:-len("_system")], "system"
        elif stem.endswith("_user"):
            base, role = stem[:-len("_user")], "user"
        else:
            base, role = stem, "prompt"
        groups.setdefault(base, {})[role] = f"{stem}.html"

    rows = []
    for base in sorted(groups):
        roles = groups[base]
        links = " · ".join(
            f'<a href="{roles[r]}">{r}</a>'
            for r in ("system", "user", "prompt") if r in roles
        )
        rows.append(f'<li><code>{base}</code> &mdash; {links}</li>')
    index_content = (
        "<p>Plain-text prompts sent to the LLM extractors under "
        "<code>source/llm/</code>. Each extractor's code and output schema are "
        'on their own source pages (see the <a href="' + prefix +
        'index.html">data portal</a>); these pages show the exact prompt text, '
        "system and user, that produced the extracted fields.</p>"
        f'<ul class="link-list">{"".join(rows)}</ul>'
    )
    (out_dir / "index.html").write_text(
        _page("LLM extraction prompts", index_content), encoding="utf-8")

    print(f"  source/llm/prompts/ ({len(txts)} prompts + index)")
    return {
        "extra_docs_info": [{
            "category": "LLM prompts",
            "title": "LLM extraction prompts",
            "stem": "llm-prompts-index",
            "href": "source/llm/prompts/index.html",
        }]
    }


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
    # Render the LLM extraction prompts (plain .txt) as browsable pages.
    hooks=[_render_prompt_pages],
)
