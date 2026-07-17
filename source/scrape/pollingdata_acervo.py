"""Scrape the pollingdata.com.br per-election poll archive.

INTENT
    Collect individual poll results (per candidate vote intention) for Brazilian
    elections from pollingdata.com.br, so downstream analyses have a clean
    vote-intention time series for state/federal races (president, governor,
    senate) — cycles TSE's own registry only exposes as methodology + PDF
    relatórios. One tidy parquet per election under
    build/scrape/pollingdata_acervo/.

REASONING
    - The site is a static site (S3): the apex host serves per-election data
      widgets as self-contained HTML. Each election page (e.g.
      /2022/presidente/br/t1/) embeds an <iframe> to a widget HTML whose
      reactable payload carries every poll as a JSON row: institute, TSE
      protocol number, date, mode, sample size, scenario, and a column per
      candidate. We parse that JSON directly — no browser / JS execution needed.
    - The master index /acervo_app/acervo_all.html is itself a reactable listing
      every archived election with its canonical URL; we read the election list
      from it rather than guessing URL slugs (which vary by cycle).
    - Idempotent + resumable: one parquet per election, skipped if present, so a
      large multi-cycle pull can be interrupted and resumed. Only the parsed rows
      are kept (the ~15 MB widget HTML is discarded), so disk stays small.
    - Rate-limited and UA-identified; a JSONL run log records per-election
      outcome.

ASSUMES
    - Network egress to https://pollingdata.com.br (apex host).
    - pandas for parquet output.

Usage:
    python source/scrape/pollingdata_acervo.py --offices presidente,governador \
        --years 2018,2022 [--rate-seconds 1.5] [--limit N]
    python source/scrape/pollingdata_acervo.py --index-only   # just refresh index
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

import path

APEX = "https://pollingdata.com.br"
INDEX_URL = f"{APEX}/acervo_app/acervo_all.html"
OUT_DIR = path.pollingdata_acervo_dir
RUNLOG = OUT_DIR / "_runlog.jsonl"
INDEX_CSV = OUT_DIR / "_index.csv"


def fetch(url: str, timeout: int = 90) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "polling-research-scraper/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _json_blocks(html: str):
    for b in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            yield json.loads(b)
        except Exception:
            continue


def _strip(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s))).strip()


def parse_index(html: str) -> pd.DataFrame:
    """Election list from acervo_all.html (reactable). One row per archived
    election with year, office, location and canonical URL."""
    for j in _json_blocks(html):
        x = j.get("x") if isinstance(j, dict) else None
        tag = x.get("tag") if isinstance(x, dict) else None
        data = tag.get("attribs", {}).get("data") if isinstance(tag, dict) else None
        # the index reactable maps real fields onto demo accessors:
        #   Playoffs=year, texto.busca=office(+location), Team=uf, SoS_rating=turno, url
        if isinstance(data, dict) and {"Playoffs", "texto.busca", "url"} <= set(data):
            n = len(data["Playoffs"])
            rows = []
            for i in range(n):
                cargo = _strip(data["texto.busca"][i])
                office = re.match(r"[A-Za-zç]+", cargo)
                url = re.search(r"https?://[^\"' >]+", str(data["url"][i]))
                rows.append({
                    "year": str(data["Playoffs"][i]),
                    "office": (office.group(0).lower() if office else ""),
                    "cargo_raw": cargo,
                    "uf": _strip(data.get("Team", [""] * n)[i]),
                    "turno": _strip(data.get("SoS_rating", [""] * n)[i]).split()[0] if data.get("SoS_rating") else "",
                    "url": url.group(0) if url else None,
                })
            return pd.DataFrame(rows).dropna(subset=["url"]).drop_duplicates("url")
    raise SystemExit("could not parse election index from acervo_all.html")


def parse_widget(html: str) -> list[dict]:
    """Extract the per-poll table from an election widget: the largest reactable
    whose columns include Entrevistas (sample size) and Modo (mode)."""
    best = None
    for j in _json_blocks(html):
        x = j.get("x") if isinstance(j, dict) else None
        tag = x.get("tag") if isinstance(x, dict) else None
        data = tag.get("attribs", {}).get("data") if isinstance(tag, dict) else None
        if isinstance(data, dict) and "Entrevistas" in data and "Modo" in data and "id" in data:
            nr = len(data["id"])
            if best is None or nr > best[1]:
                best = (data, nr)
    if not best:
        return []
    data, n = best
    cand_cols = [c for c in data if re.search(r"<br>\(\w+\)$", c) or _strip(c) == "Não Válido"]
    rows = []
    for i in range(n):
        idtxt = _strip(data["id"][i])
        date = re.search(r"\d{4}-\d{2}-\d{2}", idtxt)
        prot = re.search(r"[A-Za-z]{2}-\d+/\d{4}", idtxt)
        institute = idtxt[: idtxt.index(prot.group(0))].strip(" |") if prot else None
        base = {
            "protocolo": prot.group(0) if prot else None,
            "poll_date": date.group(0) if date else None,
            "institute_raw": institute,
            "mode": data["Modo"][i],
            "sample_size": data["Entrevistas"][i],
            "cenario": data.get("cenario", [None] * n)[i],
        }
        for c in cand_cols:
            m = re.match(r"(.*?)<br>\((\w+)\)$", c)
            cand = _strip(m.group(1)) if m else _strip(c)
            party = m.group(2) if m else None
            rows.append({**base, "candidate": cand, "party": party, "pct": data[c][i]})
    return rows


def slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", url.split("pollingdata.com.br/")[-1].lower()).strip("_")


def scrape_election(url: str) -> list[dict]:
    # apex path; urllib follows the 302 → trailing-slash wrapper automatically
    wrapper = fetch(APEX + "/" + url.split("pollingdata.com.br/")[-1])
    m = re.search(r'<iframe[^>]*src="([^"]+\.html)"', wrapper)
    if not m:
        return []
    src = m.group(1)
    widget_url = APEX + src if src.startswith("/") else APEX + "/" + src
    return parse_widget(fetch(widget_url))


def log(rec: dict) -> None:
    with open(RUNLOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offices", default="presidente,governador",
                    help="comma list; e.g. presidente,governador,senador")
    ap.add_argument("--years", default="2018,2022", help="comma list of election years")
    ap.add_argument("--rate-seconds", type=float, default=1.5)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--index-only", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    idx = parse_index(fetch(INDEX_URL))
    idx.to_csv(INDEX_CSV, index=False)
    print(f"index: {len(idx):,} archived elections → {INDEX_CSV.relative_to(path.PROJECT_ROOT)}")
    if args.index_only:
        return 0

    offices = {o.strip().lower() for o in args.offices.split(",")}
    years = {y.strip() for y in args.years.split(",")}
    sel = idx[idx["office"].isin(offices) & idx["year"].isin(years)].reset_index(drop=True)
    if args.limit:
        sel = sel.head(args.limit)
    print(f"selected {len(sel):,} elections ({sorted(offices)} × {sorted(years)})")

    ok = skip = err = 0
    for _, e in sel.iterrows():
        out = OUT_DIR / f"{slug(e['url'])}.parquet"
        if out.exists():
            skip += 1
            continue
        try:
            rows = scrape_election(e["url"])
            if not rows:
                log({"url": e["url"], "status": "no_rows"})
                err += 1
                continue
            df = pd.DataFrame(rows)
            # pct / sample_size are numeric ('NA' = candidate absent in scenario)
            df["pct"] = pd.to_numeric(df["pct"], errors="coerce")
            df["sample_size"] = pd.to_numeric(df["sample_size"], errors="coerce")
            # canonical UF lives in the URL path (/year/office/uf/slug); the
            # index "Team" field is the country code (BRA), not the state.
            parts = e["url"].split("pollingdata.com.br/")[-1].split("/")
            df["uf"] = parts[2].upper() if len(parts) >= 3 else ""
            for k in ("year", "office", "turno", "cargo_raw", "url"):
                df[k] = e[k]
            df.to_parquet(out, index=False)
            ok += 1
            log({"url": e["url"], "status": "ok", "polls": int(df["protocolo"].nunique()), "rows": len(df)})
            print(f"  ok  {e['year']} {e['office']} {e['uf']}  {df['protocolo'].nunique()} polls")
        except Exception as exc:  # pragma: no cover - network variance
            log({"url": e["url"], "status": "error", "error": repr(exc)})
            err += 1
            print(f"  ERR {e['url']}: {exc}", file=sys.stderr)
        time.sleep(args.rate_seconds)

    print(f"\ndone: {ok} scraped, {skip} skipped (already present), {err} errors → "
          f"{OUT_DIR.relative_to(path.PROJECT_ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
