"""SEC EDGAR 13F-HR fetcher for tracked institutional investors.

Uses only the free, unauthenticated EDGAR data APIs:
  https://data.sec.gov/submissions/CIK{cik}.json   — filing history
  https://www.sec.gov/Archives/edgar/…/primary.xml  — 13F infotable XML

One request per investor per day (called by the orchestrator).
Rate limit: max 10 requests/second per SEC fair-use policy — we are
well within that since we make ~5 requests per 24-hour run.
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from brain.copy_trading import TRACKED_INVESTORS, get_holdings_periods, upsert_13f_holdings

log = logging.getLogger(__name__)

_BASE     = "https://data.sec.gov"
_ARCHIVES = "https://www.sec.gov/Archives/edgar"


def _cfg():
    try:
        from brain.disclosure_settings import load
        return load()
    except Exception:
        from brain.disclosure_settings import DisclosureConfig
        return DisclosureConfig()


def _headers():
    return {"User-Agent": _cfg().edgar_user_agent, "Accept-Encoding": "gzip, deflate"}

# CUSIP → ticker symbol cache (populated lazily from EDGAR company facts)
_CUSIP_CACHE: dict[str, str] = {}


def _get(url: str, retries: int = 2) -> Optional[httpx.Response]:
    cfg = _cfg()
    for attempt in range(retries + 1):
        try:
            r = httpx.get(url, timeout=cfg.edgar_request_timeout_secs, headers=_headers(), follow_redirects=True)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                time.sleep(10)
            log.debug("EDGAR %s → HTTP %d", url, r.status_code)
        except Exception as exc:
            log.warning("EDGAR request error (%s): %s", url, exc)
        time.sleep(1)
    return None


def _fetch_latest_13f(cik: str) -> Optional[dict]:
    """Return metadata for the most recent 13F-HR filing, or None."""
    padded = cik.lstrip("0").zfill(10)
    url = f"{_BASE}/submissions/CIK{padded}.json"
    r = _get(url)
    if not r:
        return None
    try:
        data = r.json()
    except Exception:
        return None

    filings = data.get("filings", {}).get("recent", {})
    forms      = filings.get("form", [])
    acc_nums   = filings.get("accessionNumber", [])
    filed_ats  = filings.get("filingDate", [])
    periods    = filings.get("reportDate", [])

    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            return {
                "accession":  acc_nums[i].replace("-", ""),
                "filed_at":   filed_ats[i],
                "period":     periods[i],
                "cik_padded": padded,
            }
    return None


def _fetch_13f_xml(cik_padded: str, accession: str) -> Optional[str]:
    """Fetch the primary infotable XML for a 13F filing."""
    # Filing index lists documents
    idx_url = f"{_ARCHIVES}/full-index/{accession[:4]}/{accession[4:6]}/{accession}/"
    # Try standard path pattern
    acc_dashed = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
    xml_url = f"{_ARCHIVES}/edgar/data/{int(cik_padded)}/{accession}/{acc_dashed}-index.json"
    r = _get(xml_url)
    doc_name = None
    if r:
        try:
            idx = r.json()
            for doc in idx.get("directory", {}).get("item", []):
                name = doc.get("name", "")
                if name.endswith(".xml") and "infotable" in name.lower():
                    doc_name = name
                    break
                if name.endswith(".xml") and doc_name is None:
                    doc_name = name
        except Exception:
            pass

    if not doc_name:
        # Common fallback filenames
        for candidate in ("form13fInfoTable.xml", "infotable.xml", "primary_doc.xml"):
            test_url = f"{_ARCHIVES}/edgar/data/{int(cik_padded)}/{accession}/{candidate}"
            r2 = _get(test_url)
            if r2 and r2.status_code == 200:
                return r2.text
        return None

    xml_url = f"{_ARCHIVES}/edgar/data/{int(cik_padded)}/{accession}/{doc_name}"
    r = _get(xml_url)
    return r.text if r else None


def _parse_infotable(xml_text: str) -> list[dict]:
    """Parse 13F infotable XML → list of holding dicts."""
    holdings: list[dict] = []
    try:
        # Strip namespace for easier parsing
        xml_clean = xml_text.replace(' xmlns="', ' xmlns:ignored="')
        root = ET.fromstring(xml_clean)

        # Find all infoTable elements regardless of nesting/namespace
        for node in root.iter():
            if node.tag.lower().endswith("infotable"):
                name_el  = _find(node, "nameofissuer")
                cusip_el = _find(node, "cusip")
                value_el = _find(node, "value")
                shares_el = _find(node, "sshprnamt")

                company = (name_el.text or "").strip() if name_el is not None else ""
                cusip   = (cusip_el.text or "").strip() if cusip_el is not None else ""
                try:
                    value_usd = float(value_el.text or 0) * 1000  # reported in thousands
                except (TypeError, ValueError):
                    value_usd = 0.0
                try:
                    shares = float(shares_el.text or 0)
                except (TypeError, ValueError):
                    shares = 0.0

                if not company:
                    continue

                holdings.append({
                    "company_name": company,
                    "cusip":        cusip,
                    "symbol":       _CUSIP_CACHE.get(cusip, ""),
                    "value_usd":    value_usd,
                    "shares":       shares,
                })
    except ET.ParseError as exc:
        log.warning("13F XML parse error: %s", exc)
    return holdings


def _find(node: ET.Element, tag_suffix: str) -> Optional[ET.Element]:
    """Case-insensitive child search ignoring XML namespace."""
    for child in node:
        if child.tag.lower().endswith(tag_suffix.lower()):
            return child
    return None


def refresh_investor(investor_id: str, cik: str) -> bool:
    """Fetch latest 13F for one investor and upsert holdings. Returns True on success."""
    meta = _fetch_latest_13f(cik)
    if not meta:
        log.warning("No 13F found for investor=%s cik=%s", investor_id, cik)
        return False

    period = meta["period"]
    # Skip if we already have this period
    existing = get_holdings_periods(investor_id)
    if period in existing:
        log.debug("13F already current for %s (%s)", investor_id, period)
        return True

    xml_text = _fetch_13f_xml(meta["cik_padded"], meta["accession"])
    if not xml_text:
        log.warning("Could not fetch 13F XML for %s (%s)", investor_id, period)
        return False

    holdings = _parse_infotable(xml_text)
    if not holdings:
        log.warning("13F XML parsed 0 holdings for %s", investor_id)
        return False

    upsert_13f_holdings(investor_id, period, holdings, filed_at=meta["filed_at"])
    log.info("13F refresh done: %s — %d holdings for period %s", investor_id, len(holdings), period)
    return True


def refresh_all() -> dict[str, bool]:
    """Refresh 13F holdings for all tracked investors. Returns {investor_id: success}."""
    results: dict[str, bool] = {}
    for inv in TRACKED_INVESTORS:
        cik = inv.get("cik", "")
        if not cik:
            log.warning("No CIK for investor %s — skipping", inv["id"])
            results[inv["id"]] = False
            continue
        try:
            ok = refresh_investor(inv["id"], cik)
            results[inv["id"]] = ok
        except Exception as exc:
            log.error("13F refresh failed for %s: %s", inv["id"], exc, exc_info=True)
            results[inv["id"]] = False
        time.sleep(_cfg().edgar_rate_limit_sleep_secs)
    return results
