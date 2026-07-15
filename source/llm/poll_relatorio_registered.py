"""Registered-slate estimulado extraction — wires llmkit to politica.

INTENT. Extract the ONE stimulated vote-intention scenario whose candidate
set matches a poll's official TSE slate, passed into the prompt. Companion
to poll_relatorio.py (which extracts every printed scenario and leaves the
name-join to poll_response_2024.py); this wrapper removes both the fuzzy
name-join and the scenario-choice step for post-deadline polls. Spec:
projects/poll-sponsor-bias/docs/notes/extraction-registered-slate-redesign.md.

REASONING. Additive by design — a NEW cache dir (build/llm/
poll_relatorio_registered/), a NEW schema (PollRelatorioRegistered), and
schema_in_cache_key=True so this task can never collide with the existing
poll_relatorio cache even if the dirs were ever shared. The existing
extractor, schema, and clean-join scripts are untouched.

ASSUMES. The slate JSON is deterministic per protocol (built from
build/clean/candidato.csv by extract_registered.py). It is folded into the
cache-hashed `text` so that a change to the slate — not just the PDF —
invalidates the cache entry. The driver, not the model, enforces the
exact-slate-match acceptance criterion.

Public API:
    extract_registered(*, protocol, pdf_path, slate_json, municipality,
                       uf, client, model=MODEL, cache=CACHE,
                       reextract=False) -> ExtractionResult | None
        Returns None when the PDF has too little text (image-only) — a
        skip, not an error, matching poll_relatorio.extract_poll_relatorio.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit import LLMCache, extract
from llmkit.cache import content_hash, text_hash  # noqa: F401 (parity w/ poll_relatorio)

from poll_relatorio import (
    MAX_TEXT_CHARS,
    MIN_TEXT_CHARS,
    pdf_to_text,
    protocol_display,
    truncate_text,
)
from schemas_registered import PollRelatorioRegistered

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"

MODEL = "gpt-4o-mini"

CANONICAL_CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_relatorio_registered"
CACHE = LLMCache(CANONICAL_CACHE_DIR)


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("poll_relatorio_registered_system.txt")
USER_TEMPLATE = _load_prompt("poll_relatorio_registered_user.txt")


def _cache_text(slate_json: str, pdf_text: str) -> str:
    """Content whose hash keys the cache. Includes the slate so that a
    change in the registered slate (not only the PDF) re-extracts. The PDF
    text is truncated FIRST so the hash is stable across re-runs, matching
    poll_relatorio.truncate_text; the slate is small and never truncated.
    """
    return f"SLATE:\n{slate_json}\n---PDF---\n{truncate_text(pdf_text, MAX_TEXT_CHARS)}"


def extract_registered(
    *,
    protocol: str,
    pdf_path: Path,
    slate_json: str,
    municipality: str,
    uf: str,
    client,
    model: str = MODEL,
    cache: LLMCache | None = None,
    reextract: bool = False,
) -> Optional["object"]:
    """Extract the slate-matched estimulado scenario for one poll.

    Returns None if the PDF has too little text (image-only) — treat as a
    skip. The returned ExtractionResult.parsed is a PollRelatorioRegistered;
    callers must still validate the returned número set against the slate
    (all_registered_present is the model's claim, not proof).
    """
    # Explicit None check: LLMCache defines __len__, so an empty instance is
    # falsy under `cache or CACHE` and would silently fall back to the
    # module CACHE. Disambiguate with `is None` (same trap as poll_relatorio).
    c = CACHE if cache is None else cache

    pdf_text = pdf_to_text(pdf_path)
    if len(pdf_text) < MIN_TEXT_CHARS:
        return None

    text = _cache_text(slate_json, pdf_text)
    user_prompt = USER_TEMPLATE.format(
        tse_protocol_display=protocol_display(protocol),
        municipality=municipality,
        uf=uf,
        slate_json=slate_json,
        pdf_text=truncate_text(pdf_text, MAX_TEXT_CHARS),
    )
    return extract(
        doc_id=protocol,
        text=text,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PollRelatorioRegistered,
        model=model,
        cache=c,
        client=client,
        reextract=reextract,
        use_structured_outputs=True,
        schema_in_cache_key=True,
    )
