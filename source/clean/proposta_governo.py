"""Clean: candidate government-plan (proposta de governo) text, 2020-.

INTENT. One typed table with the full text of every mayoral candidate's
`proposta de governo` (the legally-mandated government plan / manifesto
filed with the candidacy registration), keyed so it joins straight to
`candidato.csv` on `SQ_CANDIDATO`. This is the reusable manifesto-text
primitive: downstream analyses can attach what a candidate *promised* to
who they were and what they did.

REASONING. Only majoritarian candidates file a proposta, and among
municipal offices that is prefeito only (Lei 9.504/1997 art. 11 sec.1 IX),
so this table is implicitly mayor-only -- we do not filter on office, the
source already does. TSE ships one zip per (year, UF) of raw PDFs named
`{YEAR}{UF}{SQ_CANDIDATO}.pdf`; the filename *is* the join key, so we do
not parse anything out of the PDF to link a plan to a candidate. Text is
extracted with PyMuPDF (`fitz`) from the in-zip bytes -- no unpack to
disk, native page count. Plans filed as scanned images carry ~no embedded
text; those we OCR in-process (render page -> tesseract `por`). OCR is the
one expensive step, and a plan's PDF never changes once filed, so OCR text
is cached to disk keyed by the (stable) filename -- a re-run reuses the
cache and only OCRs plans it has not seen. `text_source` records where
each row's final text came from.

ASSUMES.
  - Raw zips staged at data/proposta_governo/proposta_governo_{YEAR}_{UF}.zip
    (gitignored; move to $DATA_DIR later -- override the dir with
    PROPOSTA_GOVERNO_RAW). Each zip holds `{UF}/{YEAR}{UF}{SQ}.pdf` plus a
    `LEIAME.pdf` readme we skip. 26 UFs per year (no DF -- Brasília has no
    prefeitura).
  - `SQ_CANDIDATO` from the filename matches `candidato.csv` `SQ_CANDIDATO`
    for the same year. Note candidato.csv stores it as float (e.g.
    `10000854328.0`); this table keeps it as nullable Int64, so cast one
    side before merging: candidato['SQ_CANDIDATO'].astype('Int64').
  - Portuguese OCR needs `por.traineddata`. Staged at data/tessdata/
    (gitignored; override the dir with TESSDATA_PREFIX). If absent and a
    plan needs OCR, the row keeps whatever sparse embedded text it had and
    text_source='error'.
  - OCR cache at data/proposta_governo_ocr_cache/{basename}.txt (gitignored;
    override with PROPOSTA_GOVERNO_OCR_CACHE). Safe to delete -- it only
    forces re-OCR. `--refresh-ocr` rewrites it.
"""
import argparse
import io
import os
import re
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd

import path

# Malformed PDFs (common in scan-layer files) make MuPDF spew recoverable
# "syntax error" lines to stderr; fitz still extracts. Silence the noise.
fitz.TOOLS.mupdf_display_errors(False)

RAW_DIR = Path(os.environ.get(
    "PROPOSTA_GOVERNO_RAW",
    path.build_clean_dir.parents[1] / "data" / "proposta_governo"))

# OCR cache lives beside the raw data, not under build/: it is expensive to
# recompute and independent of the clean logic, so it should survive a
# `build/` wipe.
OCR_CACHE_DIR = Path(os.environ.get(
    "PROPOSTA_GOVERNO_OCR_CACHE",
    path.build_clean_dir.parents[1] / "data" / "proposta_governo_ocr_cache"))

# Point tesseract at the locally-staged por.traineddata unless the caller
# already set TESSDATA_PREFIX. Forked workers inherit this env.
_LOCAL_TESSDATA = path.build_clean_dir.parents[1] / "data" / "tessdata"
if "TESSDATA_PREFIX" not in os.environ and _LOCAL_TESSDATA.exists():
    os.environ["TESSDATA_PREFIX"] = str(_LOCAL_TESSDATA)

# A page with fewer than this many embedded chars is treated as image-only
# and sent to OCR.
MIN_CHARS_PER_PAGE = 100
OCR_DPI = 300

# `{YEAR}{UF}{SQ_CANDIDATO}.pdf` (2020) or with a document-sequence suffix
# `{YEAR}{UF}{SQ}_{NN}.pdf` (2024, e.g. 2024AC10001885334_01.pdf). A few
# candidates split their plan across parts _01, _02, ...; we reassemble.
NAME_RE = re.compile(
    r"^(?P<year>\d{4})(?P<uf>[A-Z]{2})(?P<sq>\d+)(?:_(?P<seq>\d+))?\.pdf$")


def parse_member_name(member: str) -> dict | None:
    """Pull (year, uf, sq, doc_seq) out of a zip member path, or None."""
    m = NAME_RE.match(Path(member).name)
    if not m:
        return None
    return {
        "year": int(m.group("year")),
        "estado": m.group("uf"),
        "SQ_CANDIDATO": int(m.group("sq")),
        # Sort key for reassembling multi-part plans; single-doc -> "00".
        "doc_seq": m.group("seq") or "00",
    }


def _ocr_pdf(data: bytes) -> str:
    """OCR every page of a PDF (bytes) with tesseract `por`."""
    import pytesseract
    from PIL import Image
    parts = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for pg in doc:
            pix = pg.get_pixmap(dpi=OCR_DPI)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            parts.append(pytesseract.image_to_string(img, lang="por"))
    return "\n".join(parts)


def _cache_read(cache_path: Path) -> str | None:
    try:
        return cache_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _cache_write(cache_path: Path, text: str) -> None:
    """Atomic write so a crashed run never leaves a half-OCR'd cache file."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache_path)


def extract_one(task: tuple) -> dict:
    """Extract text + stats for one PDF member of one zip.

    Runs in a worker process: it re-opens the zip and reads only its own
    member, so no large payloads cross the process boundary. Uses embedded
    text when present; falls back to OCR (cached) for image-only scans.
    """
    zip_path, member, ocr_enabled, cache_dir, refresh_ocr = task
    rec = parse_member_name(member)  # listing guarantees this is non-None
    rec["source_file"] = member
    rec["text"] = ""
    rec["n_pages"] = 0
    rec["text_source"] = "error"
    rec["extract_error"] = ""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            data = zf.read(member)
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.is_encrypted and not doc.authenticate(""):
                raise RuntimeError("encrypted")
            embedded = "\n".join(pg.get_text("text") for pg in doc)
            rec["n_pages"] = doc.page_count

        needs_ocr = len(embedded) < MIN_CHARS_PER_PAGE * max(1, rec["n_pages"])
        if not needs_ocr:
            rec["text"] = embedded
            rec["text_source"] = "embedded"
        elif ocr_enabled:
            cache_path = Path(cache_dir) / (Path(member).stem + ".txt")
            cached = None if refresh_ocr else _cache_read(cache_path)
            if cached is not None:
                rec["text"] = cached
                rec["text_source"] = "ocr_cache"
            else:
                ocr = _ocr_pdf(data)
                # Keep whichever is richer; OCR normally wins on a scan.
                rec["text"] = ocr if len(ocr) >= len(embedded) else embedded
                rec["text_source"] = "ocr"
                _cache_write(cache_path, rec["text"])
        else:
            # OCR disabled: keep the sparse embedded text, flag it.
            rec["text"] = embedded
            rec["text_source"] = "embedded_sparse"
    except Exception as exc:  # corrupt / truncated / encrypted / OCR failure
        rec["extract_error"] = f"{type(exc).__name__}: {exc}"[:200]
    rec["n_chars"] = len(rec["text"])
    return rec


def list_members(zip_path: Path, task_cfg: tuple) -> list[tuple]:
    """Build a worker task for every candidate PDF in the zip.

    Skips non-candidate entries -- each TSE zip ships a `LEIAME.pdf`
    readme whose name does not match the `{YEAR}{UF}{SQ}.pdf` pattern.
    """
    with zipfile.ZipFile(zip_path) as zf:
        return [(str(zip_path), n, *task_cfg) for n in zf.namelist()
                if n.lower().endswith(".pdf") and parse_member_name(n)]


def find_zips(uf: str | None, year: str | None) -> list[Path]:
    pat = f"proposta_governo_{year or '*'}_{(uf or '*').upper()}.zip"
    return sorted(RAW_DIR.glob(pat))


def build(uf=None, year=None, workers=8, limit=None, ocr=True,
          refresh_ocr=False) -> pd.DataFrame:
    zips = find_zips(uf, year)
    if not zips:
        raise SystemExit(f"No proposta_governo zips found under {RAW_DIR} "
                         f"(uf={uf}, year={year})")
    task_cfg = (ocr, str(OCR_CACHE_DIR), refresh_ocr)
    tasks = []
    for z in zips:
        tasks.extend(list_members(z, task_cfg))
    if limit:
        tasks = tasks[:limit]
    print(f"Found {len(zips)} zip(s), {len(tasks):,} PDF(s); "
          f"{workers} worker(s); ocr={'on' if ocr else 'off'}"
          f"{' (refresh)' if refresh_ocr else ''}")

    records = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, rec in enumerate(pool.map(extract_one, tasks, chunksize=4), 1):
            records.append(rec)
            if i % 500 == 0:
                print(f"  {i:,}/{len(tasks):,}")

    df = pd.DataFrame.from_records(records)
    return aggregate_to_candidate(df)


def aggregate_to_candidate(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse per-PDF rows to one row per (year, estado, SQ_CANDIDATO).

    A handful of 2024 candidates split their plan across parts _01, _02,
    ...; we concatenate their text in sequence order so the output grain is
    one plan per mayoral candidate, ready to join candidato.csv. Single-doc
    candidates (all of 2020) pass through unchanged.
    """
    df = df.sort_values(["year", "estado", "SQ_CANDIDATO", "doc_seq",
                         "source_file"])

    def combine(g: pd.DataFrame) -> pd.Series:
        srcs = sorted(s for s in g["text_source"].unique() if s)
        errs = [e for e in g["extract_error"] if e]
        return pd.Series({
            "n_docs": len(g),
            "n_pages": int(g["n_pages"].sum()),
            "text_source": "+".join(srcs) if srcs else "error",
            "extract_error": " | ".join(errs),
            "source_file": ";".join(g["source_file"]),
            "text": "\n\n".join(t for t in g["text"] if t),
        })

    out = (df.groupby(["year", "estado", "SQ_CANDIDATO"], sort=True)
             .apply(combine, include_groups=False)
             .reset_index())
    out["n_chars"] = out["text"].str.len()
    out["SQ_CANDIDATO"] = out["SQ_CANDIDATO"].astype("Int64")
    out["year"] = out["year"].astype("Int64")
    return out[[
        "year", "estado", "SQ_CANDIDATO", "n_docs", "n_pages", "n_chars",
        "text_source", "extract_error", "source_file", "text",
    ]].reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uf", help="restrict to one UF (e.g. AC)")
    ap.add_argument("--year", help="restrict to one year (e.g. 2020)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, help="cap #PDFs (smoke test)")
    ap.add_argument("--no-ocr", dest="ocr", action="store_false",
                    help="skip OCR; keep only embedded text (fast pass)")
    ap.add_argument("--refresh-ocr", action="store_true",
                    help="re-OCR and overwrite the cache")
    ap.add_argument("--out", type=Path,
                    default=path.build_clean_dir / "proposta_governo.parquet")
    args = ap.parse_args()

    df = build(uf=args.uf, year=args.year, workers=args.workers,
               limit=args.limit, ocr=args.ocr, refresh_ocr=args.refresh_ocr)

    n = len(df)
    src = df["text_source"].value_counts().to_dict()
    errs = int((df["extract_error"] != "").sum())
    print(f"\n{n:,} propostas | text_source={src} | {errs:,} errors")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, engine="pyarrow", index=False, compression="zstd")
    print(f"Wrote {n:,} rows to {args.out}")
