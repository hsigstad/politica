"""Poll-lawsuit extraction — wires llmkit to politica config.

Public API:
    extract_poll_lawsuit(*, proc_id, decision_text, proc_number, tribunal,
                         filingyear, client,
                         model=MODEL, cache=CACHE, reextract=False)
        → ExtractionResult

Input is the full decision text of an electoral-justice (TRE / juízo
eleitoral) ruling, obtained by joining the case's sentença movement id
to the parsed diário movement text.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit import LLMCache, extract
from llmkit.cache import content_hash, text_hash
from llmkit.extract import ExtractionResult

from schemas import PollLawsuit

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"

MODEL = "gpt-4o-mini"
MIN_TEXT_CHARS = 400        # below this the decision is too thin to extract
MAX_TEXT_CHARS = 60_000     # cap (~15k tokens) — long decisions truncated

CANONICAL_CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_lawsuit"
CACHE = LLMCache(CANONICAL_CACHE_DIR)


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("poll_lawsuit_system.txt")
USER_TEMPLATE = _load_prompt("poll_lawsuit_user.txt")
SYSTEM_PROMPT_HASH = content_hash(SYSTEM_PROMPT)


def truncate_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    return text[:max_chars] if len(text) > max_chars else text


def extract_poll_lawsuit(
    *,
    proc_id: str,
    decision_text: str,
    proc_number: str,
    tribunal: str,
    filingyear: int | str,
    client,
    model: str = MODEL,
    cache: LLMCache | None = None,
    reextract: bool = False,
) -> Optional[ExtractionResult]:
    """Extract alleged-bias dimensions + outcome for one PESQUISA case.

    Returns None when the decision text is too short to be informative
    (treat as a skip, not an error).
    """
    c = CACHE if cache is None else cache
    text = decision_text or ""
    if len(text) < MIN_TEXT_CHARS:
        return None

    text = truncate_text(text)

    user_prompt = USER_TEMPLATE.format(
        proc_number=proc_number,
        tribunal=tribunal,
        filingyear=filingyear,
        decision_text=text,
    )
    return extract(
        doc_id=str(proc_id),
        text=text,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PollLawsuit,
        model=model,
        cache=c,
        client=client,
        reextract=reextract,
        use_structured_outputs=True,
        schema_in_cache_key=True,
    )
