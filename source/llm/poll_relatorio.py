"""Poll relatório extraction — wires llmkit to politica config.

Public API:
    extract_poll_relatorio(*, protocol, pdf_path, client,
                           model=MODEL, cache=CACHE, reextract=False)
        → ExtractionResult | None
        Returns None when the PDF has too little text (image-only) — there
        is nothing for the LLM to do; callers should treat this as a
        skipped record, not an error.

Cache lookup order:
    1. New llmkit composite key (doc_id=protocol, text_hash, model).
    2. Legacy in-house cache: {PROTOCOL}.json with top-level
       {status, model, pdf_chars, extraction:{...}} written by the
       pre-llmkit poll_extract.py. Read from the canonical cache dir
       AND from an earlier pilot location (the 111-protocol pilot was
       cached under a separate directory before the extractor moved
       into this pipeline).
    3. Fresh LLM call via llmkit.extract.

Legacy entries are wrapped in an ExtractionResult so callers don't have
to special-case them. They're flagged stale (legacy=True via
ExtractionResult.stale; the schema hasn't changed so values are
trustworthy, but they have no _cache_meta audit trail).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit import LLMCache, extract
from llmkit.cache import content_hash, text_hash
from llmkit.extract import ExtractionResult, _validate

from schemas import PollRelatorio

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"

MODEL = "gpt-4o-mini"
MIN_TEXT_CHARS = 200       # below this the PDF is treated as image-only
MAX_TEXT_CHARS = 120_000   # cap (~30k tokens)

# Canonical cache for new extractions.
CANONICAL_CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_relatorio"
CACHE = LLMCache(CANONICAL_CACHE_DIR)

# Legacy {PROTOCOL}.json caches written by the pre-llmkit script (e.g. an
# earlier 111-protocol 2024 pilot cached before this extractor existed).
# Looked up by raw protocol filename. An optional extra directory can be
# supplied via LEGACY_PILOT_CACHE_DIR.
LEGACY_CACHE_DIRS: list[Path] = [CANONICAL_CACHE_DIR]
_legacy_pilot = os.environ.get("LEGACY_PILOT_CACHE_DIR")
if _legacy_pilot:
    LEGACY_CACHE_DIRS.append(Path(_legacy_pilot))


# ── Helpers ──────────────────────────────────────────────────────────

def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("poll_relatorio_system.txt")
USER_TEMPLATE = _load_prompt("poll_relatorio_user.txt")
SYSTEM_PROMPT_HASH = content_hash(SYSTEM_PROMPT)


def pdf_to_text(pdf_path: Path) -> str:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def protocol_display(protocol: str) -> str:
    """AC094012020 → AC-09401/2020 (format echoed by the LLM)."""
    return f"{protocol[:2]}-{protocol[2:7]}/{protocol[7:]}"


def truncate_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    """Cap text before sending — and hash the post-truncation text so
    the cache key on long PDFs is stable across re-runs."""
    return text[:max_chars] if len(text) > max_chars else text


# ── Legacy reader ────────────────────────────────────────────────────

def _read_legacy_pilot(protocol: str) -> Optional[dict]:
    """Locate a pre-llmkit {PROTOCOL}.json cache entry and return its
    inner extraction dict. Returns None if no file, or if the cache
    entry recorded a non-ok status (text_unreadable / error / model_refused).
    """
    for legacy_dir in LEGACY_CACHE_DIRS:
        p = legacy_dir / f"{protocol}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # Skip new-format envelopes (these were written by llmkit and
        # would have been picked up by cache.get(key) already).
        if "_cache_meta" in data:
            continue
        if data.get("status") != "ok":
            return None
        extraction = data.get("extraction")
        if isinstance(extraction, dict):
            return extraction
    return None


# ── Public API ───────────────────────────────────────────────────────

def extract_poll_relatorio(
    *,
    protocol: str,
    pdf_path: Path,
    client,
    model: str = MODEL,
    cache: LLMCache | None = None,
    reextract: bool = False,
) -> Optional[ExtractionResult]:
    """Extract vote intentions for one TSE poll relatório.

    Returns None if the PDF has too little text (image-only). Callers
    should treat that as a skip, not an error — OCR fallback is a
    future-work item, not a soft failure.
    """
    # NB: explicit None check — LLMCache.__len__ is defined, so an
    # empty cache instance is *falsy* under `cache or CACHE`, silently
    # falling back to the module-level CACHE. Use `is None` to disambiguate.
    c = CACHE if cache is None else cache
    text = pdf_to_text(pdf_path)
    if len(text) < MIN_TEXT_CHARS:
        return None

    text = truncate_text(text)
    t_hash = text_hash(text)
    key = c.key(protocol, t_hash, model)

    # 1. New composite key
    hit = c.get(key)
    if hit is not None and not (reextract
                                and hit.is_stale(current_prompt_hash=SYSTEM_PROMPT_HASH)):
        parsed, valid, errors = _validate(hit.extraction, PollRelatorio)
        return ExtractionResult(
            doc_id=protocol,
            raw=hit.extraction,
            parsed=parsed,
            valid=valid,
            validation_errors=errors,
            cached=True,
            stale=hit.is_stale(current_prompt_hash=SYSTEM_PROMPT_HASH),
            usage=hit.meta.get("usage", {}),
        )

    # 2. Legacy pilot cache fallback ({PROTOCOL}.json in old in-house format)
    if not reextract:
        legacy_extraction = _read_legacy_pilot(protocol)
        if legacy_extraction is not None:
            parsed, valid, errors = _validate(legacy_extraction, PollRelatorio)
            return ExtractionResult(
                doc_id=protocol,
                raw=legacy_extraction,
                parsed=parsed,
                valid=valid,
                validation_errors=errors,
                cached=True,
                stale=True,   # legacy entries have no _cache_meta audit trail
                usage={},
            )

    # 3. Fresh LLM call — Structured Outputs enforces the PollRelatorio
    # schema server-side via constrained decoding, so the LLM can't drift
    # on field names. schema_in_cache_key is intentionally left False:
    # the bulk extraction wrote ~10k entries under the historical
    # (doc_id, text_hash, model) key and turning the flag on now would
    # orphan them. Flip it (and run a one-time rename across the cache)
    # if/when politica adds a second extraction task that would collide.
    user_prompt = USER_TEMPLATE.format(
        tse_protocol_display=protocol_display(protocol),
        pdf_text=text,
    )
    return extract(
        doc_id=protocol,
        text=text,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PollRelatorio,
        model=model,
        cache=c,
        client=client,
        reextract=reextract,
        use_structured_outputs=True,
    )


def validate_cached_only(
    protocol: str,
    cache: LLMCache | None = None,
    model: str = MODEL,
) -> Optional[ExtractionResult]:
    """PDF-free path: pull a cached entry (new format or legacy
    {PROTOCOL}.json), validate against the current schema, return.
    Used by the migration smoke test to re-validate pilot caches
    without touching PDFs."""
    c = CACHE if cache is None else cache
    # 1. Search the new composite-key cache for any entry whose
    #    metadata records this protocol. We don't know t_hash up
    #    front (no PDF), so scan iter_entries() for the protocol.
    for entry in c.iter_entries():
        if entry.meta.get("doc_id") == protocol or entry.key == protocol:
            parsed, valid, errors = _validate(entry.extraction, PollRelatorio)
            return ExtractionResult(
                doc_id=protocol,
                raw=entry.extraction,
                parsed=parsed,
                valid=valid,
                validation_errors=errors,
                cached=True,
                stale=False,
                usage=entry.meta.get("usage", {}),
            )

    # 2. Legacy {PROTOCOL}.json fallback
    legacy_extraction = _read_legacy_pilot(protocol)
    if legacy_extraction is not None:
        parsed, valid, errors = _validate(legacy_extraction, PollRelatorio)
        return ExtractionResult(
            doc_id=protocol,
            raw=legacy_extraction,
            parsed=parsed,
            valid=valid,
            validation_errors=errors,
            cached=True,
            stale=True,
            usage={},
        )
    return None
