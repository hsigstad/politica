"""poll_operations extractor — mode, question structure, audit/control.
One of the three poll-methodology tasks.

Reads: DS_METODOLOGIA_PESQUISA + DS_SISTEMA_CONTROLE.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from llmkit import LLMCache, extract
from llmkit.cache import content_hash
from llmkit.extract import ExtractionResult

from schemas import PollOperations

load_dotenv()

BASE_DIR = Path(os.environ["BASE_DIR"])
HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompts"

MODEL = "gpt-4o-mini"
MIN_TEXT_CHARS = 150
MAX_TEXT_CHARS = 25_000

CANONICAL_CACHE_DIR = BASE_DIR / "build" / "llm" / "poll_operations"
CACHE = LLMCache(CANONICAL_CACHE_DIR)


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("poll_operations_system.txt")
USER_TEMPLATE = _load_prompt("poll_operations_user.txt")
SYSTEM_PROMPT_HASH = content_hash(SYSTEM_PROMPT)


def truncate(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    return text[:max_chars] if len(text) > max_chars else text


def extract_poll_operations(
    *,
    protocol: str,
    ds_metodologia: str,
    ds_sistema_controle: str,
    uf: str,
    institute: str,
    client,
    model: str = MODEL,
    cache: LLMCache | None = None,
    reextract: bool = False,
) -> Optional[ExtractionResult]:
    """Returns None when both inputs are empty / too short."""
    c = CACHE if cache is None else cache
    ds_metodologia = truncate(str(ds_metodologia or ""))
    ds_sistema_controle = truncate(str(ds_sistema_controle or ""))
    combined = ds_metodologia + "\n\n" + ds_sistema_controle
    if len(combined.strip()) < MIN_TEXT_CHARS:
        return None

    user_prompt = USER_TEMPLATE.format(
        protocol=protocol,
        uf=uf,
        institute=institute or "",
        ds_metodologia=ds_metodologia,
        ds_sistema_controle=ds_sistema_controle,
    )
    return extract(
        doc_id=str(protocol),
        text=combined,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PollOperations,
        model=model,
        cache=c,
        client=client,
        reextract=reextract,
        use_structured_outputs=True,
        schema_in_cache_key=True,
    )
