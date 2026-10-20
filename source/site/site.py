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
import json as _json
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


# --- Project-local hook: LLM extraction worked-example page -----------------
# REASONING: documents politica's extractors end-to-end for any consumer — one
# real run (protocol SP076792024, Ilhabela) showing, per extractor, the verbatim
# v2 system+user prompts, the JSON schema sent, the example input document, and
# the REAL v2 output. Prompts are read LIVE from source/llm/prompts/ (auto-current
# as they evolve); the schema + input doc + output are run-pinned in the committed
# source/site/worked_example/*.json (they are a matched set from one extraction run,
# refreshed only by re-running source/../run_worked_example.py).
# ASSUMES: source/site/worked_example/<task>.json exist (committed site assets).

_WORKED_DIR = Path("source/site/worked_example")
_WORKED_ORDER = ["questionario", "sampling", "weighting", "bairro_detail"]

_WORKED_CSS = """
<style>
.we-meta{color:var(--muted,#57606a);font-size:.9rem;margin:.2rem 0 1rem}
.we-block{border:1px solid var(--border,#d0d7de);border-radius:6px;
  padding:.5rem .7rem;margin:.4rem 0 1.2rem;overflow-x:auto;
  background:var(--code-bg,#f6f8fa);white-space:pre-wrap;overflow-wrap:anywhere;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem;line-height:1.5}
.we-sec{margin-top:1.6rem;padding-top:.6rem;border-top:2px solid var(--border,#d0d7de)}
@media (prefers-color-scheme:dark){.we-block{background:#161b22}}
</style>
"""


def _render_worked_example(ctx):
    """Render one worked-example page (all extractors, one real run)."""
    from sitekit.nav import inject_nav
    from sitekit.templates import read_template

    data_dir = ctx.project_root / _WORKED_DIR
    prompts_dir = ctx.project_root / _PROMPTS_REL
    if not data_dir.is_dir():
        return {}
    tasks = [t for t in _WORKED_ORDER if (data_dir / f"{t}.json").is_file()]
    if not tasks:
        return {}

    def esc(s):
        return _html.escape(str(s))

    def block(s):
        return f'<pre class="we-block">{esc(s)}</pre>'

    first = _json.loads((data_dir / f"{tasks[0]}.json").read_text())
    proto = first.get("protocol", "")
    parts = [
        _WORKED_CSS,
        f"<p>One real extraction run on TSE poll <code>{esc(proto)}</code> "
        "(Ilhabela, SP — Instituto Paraná), showing exactly what each politica "
        "LLM extractor sends and gets back. For every extractor: the verbatim "
        "<b>system</b> and <b>user</b> messages, the <b>JSON schema</b> sent to "
        "the model, the <b>example input document</b>, and the <b>real output</b>. "
        "Model: <code>gpt-4o-mini</code> with Structured Outputs. Prompts are read "
        "live from <code>source/llm/prompts/</code>; the schema, input and output "
        "are pinned to this run.</p>",
        '<ul class="link-list">' + "".join(
            f'<li><a href="#{t}">{esc(_json.loads((data_dir/f"{t}.json").read_text()).get("title", t))}</a></li>'
            for t in tasks) + "</ul>",
    ]
    for t in tasks:
        d = _json.loads((data_dir / f"{t}.json").read_text())
        stem = d.get("prompt_stem", "")
        sys_txt = (prompts_dir / f"{stem}_system.txt").read_text(encoding="utf-8").rstrip("\n")
        user_txt = (prompts_dir / f"{stem}_user.txt").read_text(encoding="utf-8").rstrip("\n")
        usage = d.get("usage") or {}
        comp = usage.get("completion_tokens", "?")
        out_json = _json.dumps(d.get("output"), ensure_ascii=False, indent=2)
        parts.append(
            f'<div class="we-sec" id="{t}"><h2>{esc(d.get("title", t))}</h2>'
            f'<p class="we-meta">Source: <code>{esc(d.get("input_source",""))}</code> '
            f'&middot; schema <code>{esc(d.get("schema_class",""))}</code> '
            f'(<a href="../../source/llm/schemas.html">schemas.py</a>) '
            f'&middot; prompts: '
            f'<a href="../../source/llm/prompts/{stem}_system.html">system</a> / '
            f'<a href="../../source/llm/prompts/{stem}_user.html">user</a> '
            f'&middot; output <b>{"valid" if d.get("valid") else "INVALID"}</b> '
            f'&middot; completion_tokens {esc(comp)}</p>'
            f'<h3>1 &middot; System message (verbatim)</h3>{block(sys_txt)}'
            f'<h3>2 &middot; User message template (verbatim)</h3>'
            f'<p class="we-meta">The <code>{{...}}</code> placeholders are filled per poll; '
            f'the document placeholder is filled with the example input below.</p>{block(user_txt)}'
            f'<h3>3 &middot; JSON schema sent to the API</h3>{block(d.get("schema_json",""))}'
            f'<h3>4 &middot; Example input document</h3>{block(d.get("input_doc",""))}'
            f'<h3>5 &middot; Real v2 output</h3>{block(out_json)}'
            f'</div>'
        )

    template = read_template(ctx.config, "doc.html")
    # Lives two levels deep (source/llm/worked-example.html) so the "LLM prompts"
    # group links and the prompt/schema cross-links share one prefix.
    out_dir = ctx.site_dir / "source" / "llm"
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = "../../"
    page = template.replace("<!-- INJECT_TITLE -->", "LLM extraction — worked example")
    page = page.replace("<!-- INJECT_CONTENT -->", "".join(parts))
    page = inject_nav(page, ctx, prefix=prefix, active="")
    (out_dir / "worked-example.html").write_text(page, encoding="utf-8")
    print(f"  source/llm/worked-example.html ({len(tasks)} extractors)")
    return {
        "extra_docs_info": [{
            "category": "LLM prompts",
            "title": "LLM extraction — worked example",
            "stem": "llm-worked-example",
            "href": "source/llm/worked-example.html",
        }]
    }


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
    # Render the LLM extraction prompts (plain .txt) as browsable pages, and a
    # worked-example page (one real run: prompts + schema + input + output).
    hooks=[_render_prompt_pages, _render_worked_example],
)
