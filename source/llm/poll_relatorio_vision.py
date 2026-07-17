"""Vision extractor: render the estimulada page and read it with a vision LLM.

INTENT. The head-to-head (2026-07-15) showed the extraction-quality
bottleneck is PDF *format*: bar charts and multi-column tables where
`pdftotext` scrambles the numbers (a spike found both text-based arms
assigning aggregate-row values — "Não sabe", "Branco/Nulo" — to real
candidates). A vision model reading the rendered page fixes this: on the
two hardest sampled PDFs it read every candidate share exactly right.

REASONING. Same slate-primed, fill-the-slate design as
poll_relatorio_registered.py — the schema (PollRelatorioRegistered),
slate injection, and code-side reconciliation are unchanged. Only the
INPUT changes: instead of `pdftotext`, we (1) use a cheap text scan to
LOCATE the estimulada page, then (2) render just that page and send the
image to the vision model. Text-to-find + vision-to-read keeps cost near
~$0.01-0.02/poll and also handles image-only PDFs for free.

ASSUMES. `pdftoppm` (poppler) is on PATH. Vision uses json_object output
validated against PollRelatorioRegistered (retry once). Own JSON cache
keyed on image bytes + slate + prompt, separate from the text extractor's
cache. Additive: no existing file touched.

Public API:
    extract_vision(*, protocol, pdf_path, slate_json, municipality, uf,
                   client, model=MODEL, reextract=False) -> VisionResult | None
        None when no estimulada page can be located (nothing to render).
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit.cache import text_hash
from llmkit.extract import _validate

from schemas_registered import PollRelatorioRegistered

_default_dotenv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
load_dotenv(os.environ.get("DOTENV_PATH", _default_dotenv))

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"
MODEL = "gpt-4o-mini"
DPI = 200
MAX_PAGES = 2                # cap images sent per poll (cost + focus)
IMAGE_ONLY_MAX_PAGES = 5     # image-only PDFs: no text to locate the page,
                            # so render the first few pages and let vision find it
IMAGE_ONLY_TEXT_CHARS = 200  # below this total pdftotext yield → treat as scanned
CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_relatorio_vision"

SYSTEM_PROMPT = (PROMPT_DIR / "poll_relatorio_vision_system.txt").read_text(encoding="utf-8")


# ── Page location (cheap, text-based) ────────────────────────────────

def _page_text(pdf_path: Path, page: int) -> str:
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-f", str(page), "-l", str(page),
             str(pdf_path), "-"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return out.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _is_image_only(pdf_path: Path) -> bool:
    """True when pdftotext recovers almost no text from the whole PDF — a
    scanned/image-only relatório the text page-finder cannot locate a
    scenario in. Few but nonrandom; vision reads them directly off the
    rendered pages. NB: on some scanned PDFs pdftotext exits non-zero
    rather than returning empty text — that counts as image-only too, so
    we run it directly (no check=True) and treat any failure as scanned."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=60,
        )
        return len(out.stdout.strip()) < IMAGE_ONLY_TEXT_CHARS
    except (subprocess.SubprocessError, OSError):
        return True


def _n_pages(pdf_path: Path) -> int:
    try:
        out = subprocess.run(["pdfinfo", str(pdf_path)],
                             capture_output=True, text=True, timeout=30)
        for line in out.stdout.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":")[1].strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return 0


def find_estimulada_pages(pdf_path: Path, max_pages: int = MAX_PAGES) -> list[int]:
    """Rank pages by how strongly they look like the PREFEITO estimulada
    vote-intention result, using only local text. Returns the top
    `max_pages` 1-indexed page numbers (may be empty)."""
    n = _n_pages(pdf_path)
    if n == 0:
        return []
    scored: list[tuple[int, int]] = []
    for pg in range(1, n + 1):
        t = _page_text(pdf_path, pg).lower()
        if not t:
            continue
        score = 0
        if "estimulad" in t:
            score += 3
        if "prefeito" in t:
            score += 1
        if "votaria" in t:
            score += 1
        # A results page carries several "NN,N%" tokens; a pure text page
        # (methodology narrative) carries few. Reward percentage density.
        pcts = t.count("%")
        score += min(pcts, 6)
        # Penalise the rejection question and pure spontaneous pages so the
        # positive stimulated vote-intention table wins the ranking.
        if "não votaria" in t or "nao votaria" in t:
            score -= 3
        if "espont" in t and "estimulad" not in t:
            score -= 2
        # Penalise cross-tabs, runoff simulations, and validation tables:
        # they carry the estimulada/prefeito/% keywords but are NOT the
        # headline result. A vision spike misread a "CRUZAMENTO" 2nd-round
        # cross-tab column as vote intentions (percents summed to 152%).
        if "cruzamento" in t:
            score -= 5
        if "segundo turno" in t or "2º turno" in t or "2o turno" in t:
            score -= 4
        if "validação" in t or "validacao" in t:
            score -= 3
        if score > 0:
            scored.append((score, pg))
    # Higher score first; on ties prefer the EARLIER page — the headline
    # estimulada table precedes cross-tabs / regional breakdowns.
    scored.sort(key=lambda sp: (-sp[0], sp[1]))
    return [pg for _, pg in scored[:max_pages]]


def render_page_png(pdf_path: Path, page: int, dpi: int = DPI) -> bytes:
    """Render one PDF page to PNG bytes via pdftoppm."""
    with tempfile.TemporaryDirectory() as td:
        stem = Path(td) / "pg"
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
             str(pdf_path), str(stem)],
            capture_output=True, check=True, timeout=120,
        )
        pngs = sorted(Path(td).glob("pg*.png"))
        if not pngs:
            raise RuntimeError(f"pdftoppm produced no image for {pdf_path} p{page}")
        return pngs[0].read_bytes()


# ── Result shim (mirrors the fields the driver reads off ExtractionResult) ──

@dataclass
class VisionResult:
    parsed: Optional[PollRelatorioRegistered]
    valid: bool
    validation_errors: list = field(default_factory=list)
    cached: bool = False
    usage: dict = field(default_factory=dict)
    pages: list = field(default_factory=list)


# ── Extractor ────────────────────────────────────────────────────────

def _cache_path(protocol: str, key: str) -> Path:
    return CACHE_DIR / f"{protocol}.{key[:16]}.json"


def _user_content(slate_json: str, municipality: str, uf: str,
                  protocol: str, images_b64: list[str]) -> list[dict]:
    text = (
        f"TSE protocol: {protocol}\n"
        f"Município: {municipality} ({uf})\n\n"
        f"Registered candidate slate (número de urna, nome de urna, party):\n"
        f"{slate_json}\n\n"
        "The image(s) show one or two pages of the poll relatório. Find the "
        "PREFEITO 'intenção de voto estimulada' result (a table OR a bar "
        "chart — bar values are printed above/beside each bar) and fill in "
        "each registered candidate's percentage. Match tickets on the "
        "prefeito (lead) name; ignore vice names and aggregate rows "
        "(Branco/Nulo, Não sabe, Ninguém). Return ONLY the JSON object with "
        "keys: tse_protocol, scenario_found, scenario_label, estimates "
        "(list of {numero_cand, nome_urna, percent}), extra_candidates "
        "(list of strings), extraction_notes."
    )
    content: list[dict] = [{"type": "text", "text": text}]
    for b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
        })
    return content


def extract_vision(
    *,
    protocol: str,
    pdf_path: Path,
    slate_json: str,
    municipality: str,
    uf: str,
    client,
    model: str = MODEL,
    reextract: bool = False,
) -> Optional[VisionResult]:
    pages = find_estimulada_pages(pdf_path)
    if not pages and _is_image_only(pdf_path):
        # Scanned/image-only PDF: no text to locate the scenario, so render
        # the first few pages and let vision find the estimulada result.
        n = _n_pages(pdf_path)
        pages = list(range(1, min(n, IMAGE_ONLY_MAX_PAGES) + 1))
    if not pages:
        return None
    try:
        images = [render_page_png(pdf_path, pg) for pg in pages]
    except (subprocess.SubprocessError, OSError, RuntimeError):
        return None
    images_b64 = [base64.b64encode(im).decode() for im in images]

    key = text_hash("".join(images_b64) + slate_json + SYSTEM_PROMPT + model)
    cpath = _cache_path(protocol, key)
    if cpath.exists() and not reextract:
        raw = json.loads(cpath.read_text(encoding="utf-8"))["extraction"]
        parsed, valid, errors = _validate(raw, PollRelatorioRegistered)
        return VisionResult(parsed, valid, errors, cached=True, pages=pages)

    def _call() -> dict:
        r = client.chat.completions.create(
            model=model, temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _user_content(
                    slate_json, municipality, uf, protocol, images_b64)},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(r.choices[0].message.content), r.usage

    raw, usage = _call()
    parsed, valid, errors = _validate(raw, PollRelatorioRegistered)
    if not valid:                     # one retry — vision JSON occasionally drifts
        raw, usage = _call()
        parsed, valid, errors = _validate(raw, PollRelatorioRegistered)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps({
        "extraction": raw, "model": model, "pages": pages,
    }, ensure_ascii=False), encoding="utf-8")
    usage_d = {"prompt_tokens": getattr(usage, "prompt_tokens", 0),
               "completion_tokens": getattr(usage, "completion_tokens", 0)}
    return VisionResult(parsed, valid, errors, cached=False, usage=usage_d, pages=pages)
