# INTENT: deterministically parse the per-interview setor-microdata bairro PDFs
# (one row per questionnaire, each carrying a 12-15 digit IBGE setor code) into
# the PollBairroDetail `units` shape, WITHOUT the LLM.
# REASONING: gpt-4o-mini will not reliably collapse 500-600 per-interview rows to
# distinct setores — it emits one unit per row, ignores the 80-cap, and clips at
# the 16k output ceiling (dev run: 3/174 clipped, +7 dup-setor, +23 over-80). For
# this format a regex count-per-setor is exact, dup-free, clip-free, and more
# faithful than the model. The sitekit/batch build routes microdata PDFs here and
# skips the LLM (mirrors the deterministic coverage short-circuit).
# ASSUMES: input is pdftotext of the bairro/município PDF; setor codes are the
# only 12-15 digit tokens that recur per interview row.
from __future__ import annotations

import re
from collections import Counter, defaultdict

# IBGE setor censitário codes are exactly 15 digits. Match a 15-digit run not
# bounded by other digits — so a trailing type letter ("...001P") or leading
# column text doesn't block it, and 14-digit CNPJs are NOT matched.
_SETOR_RE = re.compile(r"(?<!\d)\d{15}(?!\d)")
# Route to the deterministic occurrence-counter ONLY for true per-interview
# microdata — the same setor repeated across many interview rows, so total
# occurrences greatly exceed the distinct count. A one-row-per-setor table
# (occurrences ~= distinct, interview counts in a separate column) is left to
# the LLM, which reads that count column; occurrence-counting would wrongly
# give every setor n=1 there.
MICRODATA_MIN_CODE_OCCURRENCES = 120


def looks_like_setor_microdata(text: str) -> bool:
    """True only for per-interview setor microdata: many code occurrences AND
    occurrences >= 2x distinct codes (heavy repetition). These are the PDFs the
    LLM clips on and where occurrence-count == interviews-per-setor is correct."""
    codes = _SETOR_RE.findall(text or "")
    n, d = len(codes), len(set(codes))
    return n >= MICRODATA_MIN_CODE_OCCURRENCES and n >= 2 * d


_UNITS_CAP = 80


def _distrito_for_line(line: str, code: str) -> str | None:
    """Best-effort distrito: alpha text on the row once the leading interview
    number and the setor code are removed. None when nothing alphabetic remains."""
    rest = line.replace(code, " ")
    rest = re.sub(r"\d+", " ", rest)          # drop other numbers (interview no., etc.)
    rest = re.sub(r"[|;,/]+", " ", rest).strip()
    return rest if any(c.isalpha() for c in rest) else None


def parse_setor_microdata(text: str) -> dict:
    """Collapse per-interview rows to one unit per DISTINCT setor with its count.
    Returns a PollBairroDetail-v5-shaped dict."""
    counts: Counter[str] = Counter()
    distritos: dict[str, Counter] = defaultdict(Counter)
    for line in (text or "").splitlines():
        codes = _SETOR_RE.findall(line)
        if not codes:
            continue
        # one interview row carries one setor; if several codes on a line, count each
        for code in codes:
            counts[code] += 1
            d = _distrito_for_line(line, code)
            if d:
                distritos[code][d] += 1

    distinct = counts.most_common()                 # by interview count, desc
    truncated = len(distinct) > _UNITS_CAP
    kept = distinct[:_UNITS_CAP]
    units = []
    for code, n in kept:
        dist = distritos[code].most_common(1)[0][0] if distritos.get(code) else None
        units.append({
            "bairro_name": None,
            "setor_code": code,
            "distrito": dist,
            "n_entrevistas": n,
        })
    return {
        "pesquisa_realized": True,
        "units": units,
        "units_truncated": truncated,
        "extraction_notes": (
            f"deterministic setor-microdata parse: {len(distinct)} distinct "
            f"setores from {sum(counts.values())} interview rows"
            + (f"; capped to {_UNITS_CAP}" if truncated else "")
        ),
    }
