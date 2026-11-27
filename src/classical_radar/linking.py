"""Evidence-based linking of a centralised ticket announcement to concrete performances (NHK POC).

The NHK season announcement (https://www.nhkso.or.jp/news/20260701.html) publishes single-ticket sale dates per
*group of months* ("9・10・11月公演"). A performance may only inherit a batch when
  1. it is a subscription (定期) concert in the NHK season JSON, and
  2. its sale month is known: the performance month, or the month named by the concert's own
     ``change_information`` ("12月定期公演Aプログラムとして開催") when it is held in another month.
Anything else stays unlinked with a reason. Output is not a notification trigger (``reminder_eligible`` is False).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from .parsers import clean, parse_date

_BATCH = re.compile(r"(\d{1,2}(?:・\d{1,2})*)月公演\s*一般[:：]\s*(\d{4}年\d{1,2}月\d{1,2}日[^\s]*\s*\d{1,2}:\d{2}\s*[ap]m)\s*定期会員先行[:：]\s*(\d{4}年\d{1,2}月\d{1,2}日[^\s]*\s*\d{1,2}:\d{2}\s*[ap]m)", re.I)
_MOVED = re.compile(r"(\d{1,2})月定期公演([ABCＡＢＣ])プログラムとして開催")


def parse_nhk_single_ticket_batches(html: str, url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    flat = clean(soup.get_text(" ", strip=True))
    batches = []
    for m in _BATCH.finditer(flat):
        months = [int(x) for x in m.group(1).split("・")]
        general, member = parse_date(m.group(2)), parse_date(m.group(3))
        if general["starts_at"] is None or member["starts_at"] is None:
            continue
        batches.append({"months": months, "general": general, "member": member, "source_url": url, "label_raw": m.group(0)[:200]})
    if not batches:
        raise ValueError("NHK announcement: no single-ticket batches found; page may have changed")
    seen = [mo for b in batches for mo in b["months"]]
    if len(seen) != len(set(seen)):
        raise ValueError("NHK announcement: month appears in two batches")
    return batches


def link_nhk_subscription(performances: list[dict], batches: list[dict], as_of: datetime) -> dict:
    """Returns {"linked": [...ticket claims...], "unlinked": [{performance_id, reason}]}."""
    by_month = {mo: b for b in batches for mo in b["months"]}
    linked, unlinked = [], []
    for p in performances:
        nhk = p.get("nhk") or {}
        if nhk.get("category") != "subscription":
            unlinked.append({"performance_id": p["performance_id"], "reason": "announcement covers subscription series only; no evidence for this concert"})
            continue
        if not p.get("local_date"):
            unlinked.append({"performance_id": p["performance_id"], "reason": "performance has no day-level date"})
            continue
        month, basis = int(p["local_date"][5:7]), "performance_month"
        info = nhk.get("change_information") or ""
        if info:
            moved = _MOVED.search(info)
            if not moved:
                unlinked.append({"performance_id": p["performance_id"], "reason": f"unparsed change_information: {info[:80]}"})
                continue
            month, basis = int(moved.group(1)), "declared_series_month"
        batch = by_month.get(month)
        if batch is None:
            unlinked.append({"performance_id": p["performance_id"], "reason": f"no sale batch for month {month}"})
            continue
        for phase_type, eligibility, key in (("member_presale", "定期会員先行", "member"), ("general_sale", "一般", "general")):
            d = batch[key]
            start = datetime.fromisoformat(d["starts_at"])
            linked.append({
                "performance_id": p["performance_id"], "phase_type": phase_type, "channel": "official", "eligibility": eligibility,
                "starts_at": d["starts_at"], "start_precision": "exact_time", "end_precision": "unknown", "ends_at": None,
                # A start in the past proves nothing about the sale being open now (no end/sold-out info) -> unknown.
                "current_status": "announced" if start > as_of.astimezone(timezone.utc) else "unknown",
                "scope": "single_ticket", "link_basis": basis, "sale_month_used": month,
                "source_url": batch["source_url"], "label_raw": batch["label_raw"],
                "linkage_status": "linked_by_rule", "reminder_eligible": False,
            })
    return {"linked": linked, "unlinked": unlinked}


def link_presenter_claims(detail: dict, as_of: datetime, channel: str = "official_presenter") -> dict:
    """KAJIMOTO-style detail page: sale paragraphs carry no per-performance label.

    The only evidence-backed link is "the page has exactly one own performance"; with two or more performances the
    claims stay unlinked (3.1: a notice may not be applied to every performance without evidence). Channels/seat classes
    are not modelled: the raw label is kept as ``eligibility``.
    """
    perfs, claims = detail["performances"], detail["ticket_claims"]
    if not claims:
        return {"linked": [], "unlinked": [{"performance_id": p["performance_id"], "reason": "page states no sale dates"} for p in perfs]}
    if len(perfs) != 1:
        return {"linked": [], "unlinked": [{"performance_id": p["performance_id"], "reason": f"{len(perfs)} performances share unlabeled sale paragraphs"} for p in perfs]}
    seen: dict[tuple, int] = {}
    for c in claims:
        seen[(c["phase_type"], c["label_raw"])] = seen.get((c["phase_type"], c["label_raw"]), 0) + 1
    if any(n > 1 for n in seen.values()):  # e.g. several sets of dates on one page: which set belongs to this performance is not stated
        return {"linked": [], "unlinked": [{"performance_id": perfs[0]["performance_id"], "reason": "the page states several sale lines with the same label: cannot tell which one belongs to this performance"}]}
    linked = []
    for c in claims:
        precise = c["starts_at"] is not None
        linked.append({
            "performance_id": perfs[0]["performance_id"], "phase_type": c["phase_type"], "channel": channel,
            "eligibility": c["label_raw"], "starts_at": c["starts_at"], "start_precision": "exact_time" if precise else "date_only",
            "ends_at": None, "end_precision": "unknown",
            "current_status": "announced" if precise and datetime.fromisoformat(c["starts_at"]) > as_of.astimezone(timezone.utc) else "unknown",
            "scope": "page_level_sole_performance", "link_basis": "sole_performance_on_page", "source_url": c["source_url"],
            "label_raw": c["label_raw"], "linkage_status": "linked_by_rule", "reminder_eligible": False,
        })
    return {"linked": linked, "unlinked": []}


_DETAIL_SALE = re.compile(r"1回券発売開始日.{0,40}?定期会員先行発売日\s*[:：]\s*(\d{4}年\d{1,2}月\d{1,2}日[^\s]*\s*\d{1,2}:\d{2}\s*[ap]m).{0,40}?一般発売日\s*[:：]\s*(\d{4}年\d{1,2}月\d{1,2}日[^\s]*\s*\d{1,2}:\d{2}\s*[ap]m)", re.I)


def parse_nhk_detail_single_ticket(html: str) -> dict | None:
    """The concert's own page states its single-ticket dates; used to cross-check announcement-based links."""
    flat = clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    m = _DETAIL_SALE.search(flat)
    if not m:
        return None
    member, general = parse_date(m.group(1)), parse_date(m.group(2))
    if member["starts_at"] is None or general["starts_at"] is None:
        return None
    return {"member_presale": member["starts_at"], "general_sale": general["starts_at"]}
