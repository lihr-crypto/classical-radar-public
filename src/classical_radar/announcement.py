"""Does a page show when the organisation FIRST ANNOUNCED the concert? (P0.3 measurement, ADR-0004)

03_CONTRACTS keeps three times apart: when the organiser published, when we first saw it, when something material changed. Only an
explicit publication date may fill ``official_announcement_date``; everything else must stay "首次收录". So this module is strict:

* ``published``   JSON-LD ``datePublished`` / ``article:published_time`` / ``itemprop=datePublished`` / a label such as 公開日, 掲載日, 発表日,
                  投稿日, 配信日 next to a date. Still only counts after ``classify`` checks it (see below).
* ``update_only`` 更新日, 最終更新, dateModified, ``article:modified_time``: a revision time is NOT a first announcement.
* ``ambiguous``   a bare ``<time datetime>``, a bare date inside an element whose class says "date"/"published", or ``dateCreated``: it may be
                  a news posting date, the performance date (kanagawa-geikyo's ``span.published``) or a template stamp.

``classify`` accepts ``published`` only when the date is strictly before the earliest performance date; ``source_level`` further
downgrades machine-readable stamps (JSON-LD / meta) that are identical on every page of a source, because CMS templates often stamp
every page with one value. Nothing here fetches anything.
"""
from __future__ import annotations

import json
import re
from bs4 import BeautifulSoup

_DATE = r"(\d{4})\s*[./年\-]\s*(\d{1,2})\s*[./月\-]\s*(\d{1,2})"
_PUBLISHED_LABEL = r"(?:情報公開日|公開日|掲載日|発表日|投稿日|配信日|解禁日|Published(?: on)?|Posted(?: on)?)"
_UPDATED_LABEL = r"(?:最終更新日?|更新日|Last updated|Updated|Modified)"
SNIPPET_MAX = 200
MACHINE_KINDS = ("json_ld_published", "meta_published", "itemprop_published")

_DATE_CLASS = re.compile(r"(^|[\s_-])(date|posted|published|pubdate|entry-date|news-date|post-date)([\s_-]|$)", re.I)
_META_PUBLISHED = ("article:published_time", "og:article:published_time", "datepublished", "dc.date.issued", "dc.date.created", "date", "pubdate")
_META_MODIFIED = ("article:modified_time", "og:updated_time", "datemodified", "last-modified", "dc.date.modified")


def _iso(y: str, m: str, d: str) -> str | None:
    y, m, d = int(y), int(m), int(d)
    return f"{y:04d}-{m:02d}-{d:02d}" if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31 else None


def _s(text: str) -> str:
    return re.sub(r"[\s\u3000]+", " ", text).strip()


def _norm(value: str) -> str | None:
    m = re.search(_DATE, value or "")
    return _iso(*m.groups()) if m else None


def _walk(node, key: str):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                yield v
            yield from _walk(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)


def signals(html: str) -> list[dict]:
    """Every date-like signal on the page that could be a publication/update time, each with a class and a short snippet (<= 200 chars)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []

    def add(kind: str, cls: str, raw: str, snippet: str) -> None:
        date = _norm(raw)
        if date and not any(s["kind"] == kind and s["date"] == date for s in out):
            out.append({"kind": kind, "class": cls, "date": date, "value": (raw or "").strip()[:40], "snippet": re.sub(r"\s+", " ", snippet).strip()[:SNIPPET_MAX]})

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        for key, kind, cls in (("datePublished", "json_ld_published", "published"), ("dateModified", "json_ld_modified", "update_only"), ("dateCreated", "json_ld_created", "ambiguous")):
            for value in _walk(data, key):
                add(kind, cls, value, f'JSON-LD {key}: {value}')
    for tag in soup.find_all("meta"):
        name = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        content = tag.get("content") or ""
        if name in _META_PUBLISHED:
            add("itemprop_published" if tag.get("itemprop") else "meta_published", "published", content, f'meta {name}: {content}')
        elif name in _META_MODIFIED:
            add("meta_modified", "update_only", content, f'meta {name}: {content}')
    for tag in soup.find_all(attrs={"itemprop": re.compile(r"^(datePublished|dateModified)$", re.I)}):
        if tag.name == "meta":
            continue
        raw = tag.get("datetime") or tag.get_text(" ")
        published = tag.get("itemprop", "").lower() == "datepublished"
        add("itemprop_published" if published else "meta_modified", "published" if published else "update_only", raw, tag.get_text(" ") or raw)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"[ \t　]+", " ", soup.get_text("\n"))
    for m in re.finditer(rf"({_PUBLISHED_LABEL})\s*[:：]?\s*{_DATE}", text, re.I):
        add("labelled_published", "published", f"{m.group(2)}-{m.group(3)}-{m.group(4)}", m.group(0))
    for m in re.finditer(rf"({_UPDATED_LABEL})\s*[:：]?\s*{_DATE}", text, re.I):
        add("labelled_updated", "update_only", f"{m.group(2)}-{m.group(3)}-{m.group(4)}", m.group(0))
    for tag in soup.find_all("time"):
        if tag.get("datetime"):
            add("time_tag", "ambiguous", tag["datetime"], tag.get_text(" ") or tag["datetime"])
    for tag in soup.find_all(class_=_DATE_CLASS):  # a bare, unlabelled date in a "date"-like element: news posting date OR performance date (kanagawa-geikyo), so never "published"
        own = _s(tag.get_text(" "))
        if re.fullmatch(rf"{_DATE}日?(?:\s*[(（][^)）]{{0,4}}[)）])?", own):
            add("class_date", "ambiguous", own, f'<{tag.name} class="{" ".join(tag.get("class", []))[:40]}">{own}')
    return out


def classify(page_signals: list[dict], performance_dates: list[str]) -> str:
    """published | update_only | ambiguous | none for one page. A "published" signal counts only if it is strictly before the earliest
    performance date; without a known performance date it cannot be told from a performance date, so it is ambiguous."""
    published = [s for s in page_signals if s["class"] == "published"]
    if published:
        if performance_dates and any(s["date"] < min(performance_dates) for s in published):
            return "published"
        return "ambiguous"
    if any(s["class"] == "update_only" for s in page_signals):
        return "update_only"
    return "ambiguous" if any(s["class"] == "ambiguous" for s in page_signals) else "none"


def source_level(pages: list[dict]) -> list[str]:
    """Final per-page verdicts for one source. ``pages`` = [{"signals": [...], "performance_dates": [...]}].

    Machine-readable stamps (JSON-LD / meta) are trusted only when the source's pages carry at least two different values; one
    repeated value is a template stamp, and a single page cannot show that it varies. Labelled text is explicit and keeps its verdict.
    """
    verdicts = [classify(p["signals"], p["performance_dates"]) for p in pages]
    machine_values = {s["date"] for p in pages for s in p["signals"] if s["kind"] in MACHINE_KINDS and s["class"] == "published"}
    for i, p in enumerate(pages):
        if verdicts[i] != "published":
            continue
        labelled = any(s["kind"] == "labelled_published" and p["performance_dates"] and s["date"] < min(p["performance_dates"]) for s in p["signals"])
        if not labelled and len(machine_values) < 2:
            verdicts[i] = "ambiguous"
    return verdicts
