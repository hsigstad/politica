"""Scrape TSE PesqEle divulgação relatórios for registered polls.

For each TSE poll registration in `pesquisa_eleitoral_{YEAR}.csv`, navigates the
divulgação portal (https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml),
submits the form fetch that downloads the "Relatório completo com o resultado de
pesquisa" PDF, and saves it under build/scrape/tse_relatorio/{YEAR}/{PROTOCOLO}.pdf.

Idempotent: skips protocols whose PDF is already on disk. Writes a JSONL run log
to build/scrape/tse_relatorio/{YEAR}/_runlog.jsonl with per-protocol outcomes
(downloaded / no_relatorio / error). The portal requires:
  1. opening listar.xhtml (state)
  2. selecting the election dropdown by visible-label click (not _input post)
  3. filling the protocol filter, clicking search
  4. clicking the row's `detalhar` link to navigate to detalhar.xhtml
  5. POSTing the detail form with `j_id_11:arquivoResultado` to get the PDF

Approximately 2020-era polls do NOT have uploaded relatórios (see
docs/notes/poll_data_expansion.md). 2024 expected yield ~80% of registered polls.

Usage:
    python source/scrape/tse_relatorio.py --year 2024 --limit 100
    python source/scrape/tse_relatorio.py --year 2024 --rate-seconds 1.5
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
from playwright.async_api import async_playwright

import path

LISTAR_URL = "https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml"

# TSE election dropdown labels (verified empirically against the portal)
ELEICAO_LABEL = {
    2020: "Eleições Municipais 2020",
    2024: "Eleições Municipais 2024",
}


@dataclass
class ScrapeOutcome:
    """One protocol's scrape result, for the run log."""
    protocol: str
    status: str  # "downloaded" | "already_present" | "no_relatorio" | "error"
    bytes: int = 0
    content_type: str = ""
    error: str = ""
    seconds: float = 0.0


def cli_to_display(prot: str) -> str:
    """AC094012020 → AC-09401/2020."""
    return f"{prot[:2]}-{prot[2:7]}/{prot[7:]}"


def load_mayoral_protocols(year: int) -> pd.DataFrame:
    """Load TSE poll registration CSVs for the given year, filter to mayoral polls.

    Reads per-UF CSVs from path.tse_polls_2024_dir (currently
    build/scrape/tse_polls_2024/, see path.py for migration plan).
    The user is expected to have unpacked `pesquisa_eleitoral_{year}.zip`
    from dadosabertos.tse.jus.br into that directory.
    """
    if year == 2024:
        src_dir = path.tse_polls_2024_dir
    else:
        src_dir = path.data_dir / f"tse_polls_{year}"
    csvs = sorted(src_dir.glob(f"pesquisa_eleitoral_{year}_*.csv"))
    # Drop the all-Brazil aggregated file
    csvs = [c for c in csvs if c.stem not in {f"pesquisa_eleitoral_{year}_BRASIL", f"pesquisa_eleitoral_{year}_BR"}]
    if not csvs:
        sys.exit(f"No CSVs found in {src_dir}. Download and unpack pesquisa_eleitoral_{year}.zip first.")
    dfs = []
    for c in csvs:
        dfs.append(pd.read_csv(c, sep=";", encoding="latin-1", low_memory=False))
    df = pd.concat(dfs, ignore_index=True)
    mayor = df[df["DS_CARGO"].str.contains("Prefeito", na=False, case=False)].copy()
    return mayor


async def scrape_one(page, context, protocol: str, year: int, out_dir: Path) -> ScrapeOutcome:
    """Search a protocol on the portal, navigate to its detail, fetch the PDF."""
    pdf_path = out_dir / f"{protocol}.pdf"
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        return ScrapeOutcome(protocol, "already_present", bytes=pdf_path.stat().st_size)

    t0 = time.monotonic()
    prot_display = cli_to_display(protocol)

    try:
        await page.goto(LISTAR_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector('input[placeholder^="Informe o n"]', timeout=30_000)

        # Select election via visible-label click (form submits via JSF AJAX otherwise won't filter)
        target_label = ELEICAO_LABEL[year]
        await page.click("#formPesquisa\\:eleicoes")
        await page.wait_for_timeout(400)
        items = await page.query_selector_all("#formPesquisa\\:eleicoes_items li")
        clicked = False
        for it in items:
            if (await it.inner_text()).strip() == target_label:
                await it.click()
                clicked = True
                break
        if not clicked:
            return ScrapeOutcome(protocol, "error", error=f"election label not found: {target_label}")
        await page.wait_for_timeout(1500)

        # Search by protocol
        await page.fill('input[placeholder^="Informe o n"]', prot_display)
        await page.click("a#formPesquisa\\:idBtnPesquisar")
        try:
            await page.wait_for_selector("a#formPesquisa\\:tabelaPesquisas\\:0\\:detalhar", timeout=15_000)
        except Exception:
            return ScrapeOutcome(protocol, "error", error="search returned no rows")

        # Navigate to detail page
        try:
            async with page.expect_navigation(url=lambda u: "detalhar.xhtml" in u, timeout=30_000):
                await page.click("a#formPesquisa\\:tabelaPesquisas\\:0\\:detalhar")
        except Exception as e:
            return ScrapeOutcome(protocol, "error", error=f"navigation to detail failed: {e!r}")
        await page.wait_for_timeout(1500)

        # Submit the arquivoResultado form via in-page fetch — captures the response body
        if not await page.query_selector("button#j_id_11\\:arquivoResultado"):
            return ScrapeOutcome(protocol, "error", error="no arquivoResultado button on detail page")

        result = await page.evaluate(
            """async () => {
                const form = document.querySelector('form[action*="/app/pesquisa/detalhar.xhtml"]');
                if (!form) return {error: 'no form'};
                const fd = new FormData(form);
                fd.set('j_id_11:arquivoResultado', 'j_id_11:arquivoResultado');
                const r = await fetch(form.action, {method: 'POST', body: fd, credentials: 'include'});
                const ct = r.headers.get('content-type') || '';
                const buf = await r.arrayBuffer();
                const u8 = new Uint8Array(buf);
                let bin = '';
                for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
                return {status: r.status, contentType: ct, length: buf.byteLength, body_b64: btoa(bin)};
            }"""
        )
        if result.get("error"):
            return ScrapeOutcome(protocol, "error", error=f"fetch error: {result}")

        body = base64.b64decode(result["body_b64"])
        ct = result["contentType"]
        is_pdf = body[:4] == b"%PDF" or "pdf" in ct.lower()
        if is_pdf:
            pdf_path.write_bytes(body)
            return ScrapeOutcome(protocol, "downloaded", bytes=len(body), content_type=ct,
                                 seconds=time.monotonic() - t0)
        else:
            # No relatório uploaded — server returned the detail page HTML again.
            return ScrapeOutcome(protocol, "no_relatorio", bytes=len(body), content_type=ct,
                                 seconds=time.monotonic() - t0)
    except Exception as e:
        return ScrapeOutcome(protocol, "error", error=repr(e),
                             seconds=time.monotonic() - t0)


def load_resume_state(runlog_path: Path, recheck_no_relatorio: bool
                       ) -> tuple[set[str], set[str]]:
    """Build resume state from the runlog. Returns (skip_set, defer_set).

    skip_set:  protocols to drop from the queue entirely (no_relatorio).
    defer_set: protocols to move to the END of the queue (previously errored)
               — fresh protocols are attempted first, errors retried after,
               so a TSE rate-limit hitting on retries doesn't block new work.

    Already-downloaded PDFs are not enumerated here — `scrape_one` checks
    file-on-disk inline and returns 'already_present' instantly.

    With --recheck-no-relatorio, no_relatorio entries are NOT skipped (retried).
    """
    skip: set[str] = set()
    defer: set[str] = set()
    if not runlog_path.exists():
        return skip, defer
    last_status: dict[str, str] = {}
    with open(runlog_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_status[d["protocol"]] = d["status"]
    for p, s in last_status.items():
        if s == "no_relatorio" and not recheck_no_relatorio:
            skip.add(p)
        elif s == "error":
            defer.add(p)
    return skip, defer


async def main_async(args):
    year = args.year
    mayor = load_mayoral_protocols(year)
    protocols = mayor["NR_PROTOCOLO_REGISTRO"].astype(str).unique().tolist()
    if args.limit:
        protocols = protocols[: args.limit]
    out_dir = path.build_scrape_dir / "tse_relatorio" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    runlog_path = out_dir / "_runlog.jsonl"
    skip_set, defer_set = load_resume_state(runlog_path, args.recheck_no_relatorio)
    fresh = [p for p in protocols if p not in skip_set and p not in defer_set]
    deferred = [p for p in protocols if p in defer_set]
    if skip_set:
        print(f"resume: skipping {len(skip_set):,} protocols previously marked "
              f"no_relatorio (use --recheck-no-relatorio to retry them)")
    if defer_set:
        print(f"resume: deferring {len(defer_set):,} previously-errored protocols "
              f"to the end of the queue (will retry after all fresh ones)")
    if args.priority_uf:
        pri = args.priority_uf.upper()
        fresh_pri = [p for p in fresh if p.startswith(pri)]
        fresh_rest = [p for p in fresh if not p.startswith(pri)]
        deferred_pri = [p for p in deferred if p.startswith(pri)]
        deferred_rest = [p for p in deferred if not p.startswith(pri)]
        fresh = fresh_pri + fresh_rest
        deferred = deferred_pri + deferred_rest
        print(f"priority: putting {len(fresh_pri):,} fresh + {len(deferred_pri):,} "
              f"deferred {pri} protocols first")
    protocols = fresh + deferred  # fresh first, errors retried at end
    print(f"target year: {year}, protocols to attempt: {len(protocols):,}, output: {out_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True, locale="pt-BR",
                                            viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        counts = {"downloaded": 0, "already_present": 0, "no_relatorio": 0, "error": 0}
        with open(runlog_path, "a", encoding="utf-8") as logf:
            for i, prot in enumerate(protocols, 1):
                outcome = await scrape_one(page, context, prot, year, out_dir)
                counts[outcome.status] += 1
                logf.write(json.dumps({
                    "protocol": outcome.protocol,
                    "status": outcome.status,
                    "bytes": outcome.bytes,
                    "content_type": outcome.content_type,
                    "error": outcome.error,
                    "seconds": round(outcome.seconds, 2),
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }, ensure_ascii=False) + "\n")
                logf.flush()
                if i % 10 == 0 or i == len(protocols):
                    print(f"  [{i}/{len(protocols)}] {prot} {outcome.status} ({outcome.bytes} B, {outcome.seconds:.1f}s)"
                          f" | totals: {counts}")
                # Politeness rate-limit (skip if previous was a fast cache-hit)
                if outcome.status != "already_present":
                    await asyncio.sleep(args.rate_seconds)

        await browser.close()
    print(f"\nDONE. Totals: {counts}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=[2020, 2024], required=True)
    ap.add_argument("--limit", type=int, default=None, help="cap protocols (debug)")
    ap.add_argument("--rate-seconds", type=float, default=1.5, help="polite delay between requests")
    ap.add_argument("--recheck-no-relatorio", action="store_true",
                    help="retry protocols previously marked no_relatorio "
                         "(useful if institutes might have uploaded files since)")
    ap.add_argument("--priority-uf", default=None,
                    help="UF prefix to bump to the front of the queue (e.g. SP). "
                         "Reorders fresh and deferred buckets independently.")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
