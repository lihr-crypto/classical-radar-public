"""Detail-page parsers for the list-level sources (tso, jpo, njp, kanagawa_geikyo): programme, performers and explicit sale dates.

Pure functions over HTML. Each returns ``{"programme_items": [...], "artists": [...], "ticket_claims": [...]}``; an empty list means the page
stated nothing parseable (it is never a reason to erase stored data - see ``ingest``). Selectors are scoped to the page's own content so the
"related concerts" blocks that every site appends cannot leak in (the Japan Arts bug of 2026-11-04). Sale dates are extracted only where the
page states a day and a clock time; the year is the written one or, for TSO and Kanagawa lines that omit it, the one the weekday in brackets
fixes against the first performance (``saleparse``, ADR-0005). Date-only lines (TSO "12/16(火)", Yomikyo "7月20日(月・祝)") are not parsed.
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from datetime import date

from .parsers import ParseError, clean, parse_date
from .saleparse import kanagawa_sale_claims, tso_sale_claims
from .works import _OTHER_ROLE, build_artists, parse_artist, parse_programme


def _lines(node) -> list[str]:
    return [clean(x) for x in node.get_text("\n", strip=True).splitlines() if clean(x)] if node is not None else []


def _heading_sibling(soup, tag: str, label: str, cls: str | None = None):
    for h in soup.find_all(tag, class_=cls) if cls else soup.find_all(tag):
        if clean(h.get_text()) == label:
            return h.find_next_sibling()
    return None


def _artists(lines: list[str]) -> list[dict]:
    return build_artists([a for a in (parse_artist(x) for x in lines) if a])


def _claim(phase_type: str, eligibility: str, label: str, raw_when: str, url: str, extra_note: str | None = None) -> dict | None:
    d = parse_date(raw_when)
    if d["starts_at"] is None:  # no explicit clock time -> not a minute-level claim
        return None
    return {"phase_type": phase_type, "audience_eligibility": eligibility, "local_date": d["local_date"], "local_time": d["local_time"], "starts_at": d["starts_at"],
            "date_precision": d["date_precision"], "ends_at": None, "source_url": url, "label_raw": label, "linkage_status": "needs_review", "performance_ids": []}


def parse_tso_detail(html: str, url: str, reference: date | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".concertsdetails__contents")
    if root is None:
        raise ParseError("tso: concert details container not found")
    return {"programme_items": parse_programme(_lines(root.select_one(".wp-block-concert-block-program-list"))),
            "artists": _artists(_lines(root.select_one(".wp-block-concert-block-performers"))),
            "ticket_claims": tso_sale_claims(root.get_text("\n", strip=True), url, reference)}


def parse_jpo_detail(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".singleConcert__main")
    if root is None:
        raise ParseError("jpo: singleConcert container not found")
    return {"programme_items": parse_programme(_lines(_heading_sibling(root, "h2", "曲目", "ttlBar"))),
            "artists": _artists(_lines(_heading_sibling(root, "h2", "出演者", "ttlBar"))), "ticket_claims": []}


_NJP_TIME = re.compile(r"いずれも\s*(\d{1,2}:\d{2})\s*発売")
_NJP_TIER = [("一般発売", "general_sale", "一般"), ("定期会員", "member_presale", "定期会員・パトロネージュ会員"), ("マイプラン会員", "member_presale", "マイプラン会員")]


def parse_njp_detail(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".con__detail")
    if root is None:
        raise ParseError("njp: detail container not found")
    prog = soup.select_one("ul.program__list")
    performers = soup.select_one("div.performer__wrap")
    claims: list[dict] = []
    text = soup.get_text("\n", strip=True)
    # one-ticket (一回券) sale dates by audience; the page states "（いずれも10:00発売）" once for the block
    block = re.search(r"発売日(.*?)連続券／チケット・マイプラン", text, re.S)
    if block:
        t = _NJP_TIME.search(block.group(0))
        if t:
            current = None
            for ln in (clean(x) for x in block.group(1).splitlines() if clean(x)):
                if ln.startswith(("⚫", "●", "•")) or "（一般発売）" in ln or "(一般発売)" in ln:
                    current = next(((pt, el) for key, pt, el in _NJP_TIER if key in ln or (key == "一般発売" and "上記以外" in ln)), current)
                m = re.search(r"[\[［]一回券[\]］]\s*(\d{4}年\d{1,2}月\d{1,2}日)", ln)
                if m and current:
                    c = _claim(current[0], current[1], ln, f"{m.group(1)} {t.group(1)}", url)
                    if c:
                        claims.append(c)
    for m in re.finditer(r"【(\d{4}/\d{1,2}/\d{1,2})（.）(\d{1,2}:\d{2})】より[^。]*?追加販売", text):  # 追加販売 notice with explicit time
        y, mo, d = m.group(1).split("/")
        c = _claim("additional_sale", "一般", m.group(0), f"{y}年{mo}月{d}日 {m.group(2)}", url)
        if c:
            claims.append(c)
    parsed = []
    for h4 in (performers.select("h4") if performers is not None else []):
        text = clean(h4.get_text(" ", strip=True))
        a = parse_artist(text)
        if a is None and text:  # a guest listed by name only (no "指揮：/ピアノ：" label): keep the person, role unknown
            a = {"name_display": text, "role_label": "", "kind": "other"}
        if a:
            parsed.append(a)
    return {"programme_items": parse_programme(_lines(prog)), "artists": build_artists(parsed), "ticket_claims": claims}


def parse_kanagawa_detail(html: str, url: str, reference: date | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.concert")
    if article is None:
        raise ParseError("kanagawa_geikyo: concert article not found")  # scoped: the 'おすすめのコンサート' list lives outside this article
    artists: list[str] = []
    for tr in article.select("table.concert-table tr"):
        th = tr.find("th")
        if th and clean(th.get_text()) == "出演者":
            artists = _lines(tr.find("td"))
    claims = kanagawa_sale_claims(article.get_text("\n", strip=True), url, reference)  # 一回券 / セット券 / 一般発売, with or without the year
    return {"programme_items": parse_programme(_lines(article.select_one(".concert-program"))), "artists": _artists(artists), "ticket_claims": claims}


_TMSO_SALE = re.compile(r"((?:都響)?会員先行(?:発売)?|一般発売)[:：]\s*(\d{4}年\d{1,2}月\d{1,2}日)[^\d\n]{0,8}(\d{1,2}:\d{2})")


def _split_names(text: str) -> list[str]:
    """Split on 、/, but never inside parentheses ("白井圭(名フィル、コンサートマスター)" is one entry)."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")" and depth > 0
        if ch in "、,，" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def parse_tmso_detail(html: str, url: str) -> dict:
    """TMSO detail: performers as ``役割／名前、名前`` (role line may wrap), programme as ``作曲家：作品``.

    The biographies (modal 'プロフィール一覧'), section headings and the programme-notes link are removed first. Sale dates are written
    without year or time ("一般発売：7/8（水）"), so normally no claim is produced; one is produced only for an explicit year + time.
    """
    soup = BeautifulSoup(html, "html.parser")
    prof, prog = soup.select_one("section.entry-profile .section-content"), soup.select_one("section.entry-program")
    if prof is None and prog is None:
        raise ParseError("tmso: entry-profile / entry-program sections not found")
    for node in (prof, prog):
        if node is not None:
            for t in node.select(".modal-section, .profile-thumb, .section-head, a"):
                t.decompose()
    parsed, role = [], None
    merged: list[str] = []
    for ln in (unicodedata.normalize("NFKC", x) for x in _lines(prof)):
        if merged and merged[-1].count("(") > merged[-1].count(")"):
            merged[-1] += " " + ln  # a bracket opened on the previous line continues here
        else:
            merged.append(ln)
    for ln in merged:
        if ln in ("*", "プロフィール一覧"):
            continue
        depth, cut = 0, -1
        for i, ch in enumerate(ln):  # the role separator is the first "/" outside brackets
            depth += (ch == "(") - (ch == ")" and depth > 0)
            if ch == "/" and depth == 0:
                cut = i
                break
        if cut >= 0:
            role, ln = ln[:cut].strip(), ln[cut + 1:].strip()
        for name in (x.strip(" *") for x in _split_names(ln)):
            if not (name and role):
                continue
            m = re.match(r"^(.+?)\s*\(([^()]+)\)$", name)
            bracket_role = re.split(r"[/、,]", m.group(2))[0].strip() if m else ""
            probe = parse_artist(f"{bracket_role}:x") if bracket_role else None
            if probe and (probe["kind"] != "other" or _OTHER_ROLE.search(bracket_role)):
                a = parse_artist(f"{bracket_role}:{m.group(1)}")  # "葵トリオ(ピアノ三重奏)", "森岡聡(コンサートマスター/…)": the bracket names the role
            else:
                bare = re.sub(r"\s*\([^()]*\)$", "", name)  # "(名フィル音楽監督)" is an affiliation
                a = parse_artist(f"{role}:{bare}")
            if a:
                parsed.append(a)
    claims = []
    for m in _TMSO_SALE.finditer(soup.get_text("\n", strip=True)):
        c = _claim("general_sale" if m.group(1) == "一般発売" else "member_presale", "一般" if m.group(1) == "一般発売" else "都響会員", m.group(0), f"{m.group(2)} {m.group(3)}", url)
        if c:
            claims.append(c)
    return {"programme_items": parse_programme(_lines(prog)), "artists": build_artists(parsed), "ticket_claims": claims}


DETAIL_PARSERS = {"tmso": parse_tmso_detail, "tso": parse_tso_detail, "jpo": parse_jpo_detail, "njp": parse_njp_detail, "kanagawa_geikyo": parse_kanagawa_detail}


def parse_detail(source_id: str, html: str, url: str, reference: date | None = None) -> dict:
    """``reference`` = the page's first performance date (TSO and Kanagawa use it to fix a year the page leaves out); None skips year-less lines."""
    if source_id not in DETAIL_PARSERS:
        raise ParseError(f"no detail parser for {source_id}")
    if source_id in ("tso", "kanagawa_geikyo"):
        return DETAIL_PARSERS[source_id](html, url, reference)
    return DETAIL_PARSERS[source_id](html, url)
