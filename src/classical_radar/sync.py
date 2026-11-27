"""Manual, rate-limited sync of the registered sources into the local store (v0.1).

Runs only when a person invokes ``classical-radar sync``; there is no scheduler. Everything lands as ``needs_review``
(the review queue in the UI is the only way to publish). Policy for all sources is still ``unknown``. tpo is deferred by the user
(ADR-0001). tmso was enabled by the user on 2026-11-04: as for every source, only facts are kept (no description text, biographies or
images) and nothing is republished.

Each source function is independent: a failure in one is reported and does not touch another source's data.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from . import pageobs, reminders, season_pdf, yomikyo_poster
from .detail import parse_detail
from .ingest import _event, ingest_source, ingest_ticket_phases
from .linking import link_nhk_subscription, link_presenter_claims, parse_nhk_single_ticket_batches
from .network import FetchError, Reader
from .parsers import JST, ParseError, canonical, parse_list, parse_nhk, parse_presenter_detail, parse_yomikyo_calendar
from .sources import DEFERRED, SOURCES

NHK_JSON_INDEX = "https://www.nhkso.or.jp/concert/json/list_archive_concert.json"
NHK_HALLS = "https://www.nhkso.or.jp/concert/hall/json/hall_all.json"
NHK_NEWS_INDEX = "https://www.nhkso.or.jp/news/json/news_all.json"
# the next-season announcement: "〈速報〉2027-28シーズン定期公演 プログラム発表（2027年9月～2028年6月）" (earlier years also "日程・指揮者決定", "出演者・曲目発表")
NHK_SEASON_NEWS = re.compile(r"(\d{4})-(\d{2})シーズン定期公演.*?(?:日程・指揮者決定|プログラム発表|出演者・曲目発表)")
# The season ticket announcement is a news article, not discoverable from a list; it is season-specific and must be
# updated by hand each season (the sync reports when it cannot be parsed instead of guessing).
NHK_TICKET_NEWS = ["https://www.nhkso.or.jp/news/20260701.html"]
PAGED = {  # source -> (first page, page template, regex yielding page numbers in hrefs)
    "tmso": ("https://www.tmso.or.jp/j/concert/", "https://www.tmso.or.jp/j/concert/?tab=1&page={n}", r"tab=1&page=(\d+)"),
    "tso": ("https://tokyosymphony.jp/concert/", "https://tokyosymphony.jp/concert/page/{n}/", r"/concert/page/(\d+)/"),
    "njp": ("https://www.njp.or.jp/concerts/", "https://www.njp.or.jp/concerts/page/{n}/", r"/concerts/page/(\d+)/"),
    "jpo": ("https://japanphil.or.jp/concert/?p_type=performance&p_status=", "https://japanphil.or.jp/concert/?p_type=performance&p_status&p_page={n}", r"p_page=(\d+)"),
    "kanagawa_geikyo": ("https://kanagawa-geikyo.com/concert/", "https://kanagawa-geikyo.com/concert/page/{n}/", r"/concert/page/(\d+)/"),
}
SUPPORTED = ("japanarts", "kajimoto", "yomikyo", "nhkso", "tmso", "tso", "njp", "jpo", "kanagawa_geikyo")
DETAIL_SOURCES = ('tmso', 'tso', 'njp', 'jpo', 'kanagawa_geikyo')
MAX_PAGES = 20  # hard stop against a malformed pager; 新日本フィル already needs 9 pages and a new season lengthens every list
NHK_YEAR_FILES = 2  # the newest yearly data files read per run (see _nhk)


def _host(url: str) -> str:
    return urlsplit(url).hostname


def _get(reader: Reader, url: str):
    try:
        return reader.get(url, _host(url))
    except FetchError as exc:
        if "transport error" in str(exc):  # one retry for a transient reset; never for 401/403/429 (those stop the source)
            return reader.get(url, _host(url))
        raise


def _today(now: datetime) -> str:
    return now.astimezone(JST).date().isoformat()


def _presenter(conn, reader, source_id, now, log):
    list_url = SOURCES[source_id].url
    body, _ = _get(reader, list_url)
    cards, _ = parse_list(source_id, body, list_url)
    urls = sorted({c["source_url"] for c in cards})
    cands, phases, errors = [], [], []
    for i, url in enumerate(urls, 1):
        try:
            html, meta = _get(reader, url)
            if meta["status"] != 200:
                errors.append(f"{url}: HTTP {meta['status']}")
                continue
            d = parse_presenter_detail(source_id, html, url, now.isoformat())
            pageobs.record_page(conn, source_id, url, html, now)  # the page's own publication/modified stamps, for the monitoring report
            cands += d["performances"]
            if source_id in ("kajimoto", "japanarts"):
                phases.append((url, link_presenter_claims(d, now)["linked"]))
        except ParseError as exc:
            errors.append(f"{url}: {exc}")
        log(f"{source_id} {i}/{len(urls)}")
    cands = [c for c in cands if c["local_date"] and c["local_date"] >= _today(now)]  # past dates are not tracked
    result = ingest_source(conn, source_id, cands, now, complete=True, doc_kind="detail")
    ph = {"new": 0, "changed": 0, "unchanged": 0, "skipped_unknown_performance": 0}
    for url, linked in phases:
        if linked:
            for k, v in ingest_ticket_phases(conn, source_id, linked, url, now).items():
                ph[k] += v
    return {**result, "items_listed": len(urls), "items_failed": len(errors), "errors": errors[:10], "ticket_phases": ph}


def _yomikyo(conn, reader, source_id, now, log):
    body, _ = _get(reader, "https://yomikyo.or.jp/cal.php")
    cal, _ = parse_yomikyo_calendar(body, "https://yomikyo.or.jp/cal.php", now.isoformat())
    today = _today(now)
    future = [c for c in cal if c["local_date"] >= today]
    cands, errors = [], []
    for i, c in enumerate(future, 1):
        try:
            html, meta = _get(reader, c["source_url"])
            detail = parse_presenter_detail("yomikyo", html, c["source_url"], now.isoformat())["performances"][0] if meta["status"] == 200 else None
            # the calendar and the detail page must agree on date/time, otherwise keep the calendar record without venue
            cands.append(detail if detail and (detail["local_date"], detail["local_time"]) == (c["local_date"], c["local_time"]) else c)
            if detail is None or cands[-1] is c:
                errors.append(f"{c['source_url']}: detail unavailable or disagrees with calendar")
        except ParseError as exc:
            cands.append(c)
            errors.append(f"{c['source_url']}: {exc}")
        log(f"yomikyo {i}/{len(future)}")
    poster, poster_info, warnings = _yomikyo_poster(conn, reader, source_id, cands, now)
    result = ingest_source(conn, source_id, cands + poster, now, complete=True, doc_kind="detail")
    out = {**result, "items_listed": len(future), "items_failed": len(errors), "errors": errors[:10]}
    if poster_info:
        out["poster"] = poster_info
    if warnings:
        out["warnings"] = warnings
    return out


POSTER_ADOPTED = "poster programme moved onto its official page"  # the note of the change_event that remembers a move (ADR-0021)


def _yomikyo_poster(conn, reader, source_id: str, official: list[dict], now: datetime):
    """The next season's programmes from the committed transcription of the preliminary PDF (ADR-0021): (candidates to ingest, summary, warnings).
    A programme the official feed already carries is left out and its stored concert moves onto the official page in place (the same idea as
    ``_adopt_season_concerts``, matched by series and number, ``yomikyo_poster.match_official``). Never raises: whatever goes wrong here is a
    warning, and the official calendar is ingested regardless."""
    try:
        poster = yomikyo_poster.load()
        source = poster["source"]
        items = yomikyo_poster.candidates(poster["concerts"], source["pdf"], now.isoformat())
        matched, ambiguous = yomikyo_poster.match_official(items, official)
        by_tag = {it["poster"]["tag"]: it for it in items}
        warnings = [f"读响乐季海报里的 {tag}：{why}，没有判断是哪一场，没有合并（请看是不是重复）" for tag, why in sorted(ambiguous.items())]
        adopted = 0
        for tag, off in sorted(matched.items()):
            row = conn.execute("SELECT id FROM concert WHERE identity_key=?", (f"{source_id}|{canonical(by_tag[tag]['source_url'])}",)).fetchone()
            if row is None:
                continue
            target = f"{source_id}|{canonical(off['source_url'])}"
            if conn.execute("SELECT 1 FROM concert WHERE identity_key=? AND id<>?", (target, row["id"])).fetchone():
                warnings.append(f"海报里的 {tag} 要迁到 {target.split('|', 1)[1]}，但那个地址已经是另一张卡片，没有合并（请看是不是重复）"[:240])
                continue
            conn.execute("UPDATE concert SET identity_key=? WHERE id=?", (target, row["id"]))
            _event(conn, "concert", row["id"], "identity_key", f"{source_id}|{canonical(by_tag[tag]['source_url'])}", target, None, now, POSTER_ADOPTED)  # remembered: see `moved`
            adopted += 1
        known = {f"{source_id}|{canonical(it['source_url'])}" for it in items}
        for (key,) in conn.execute("SELECT identity_key FROM concert WHERE organization_id=? AND identity_key LIKE ?", (source_id, f"{source_id}|%?program=%")).fetchall():
            if key not in known:
                warnings.append(f"库里有一张读响海报卡片 {key.split('|', 1)[1]}，转录文件里已经没有它了（改过系列或编号？它不会自己消失）"[:240])
        pdf, pdf_warning = _poster_pdf_state(reader, source)
        if pdf_warning:
            warnings.append(pdf_warning)
        # A programme that was moved onto its official page has no `?program=` row any more: if the official entry is missing from the calendar
        # one day (cancelled, page renamed or retitled, only some months returned), it must not be stored again as a second card. Two memories:
        # the moves themselves (a change_event, whatever the official title says today), and the numbered official concerts of this season.
        moved = {json.loads(b) for (b,) in conn.execute("SELECT before_json FROM change_event WHERE entity_type='concert' AND field_path='identity_key' AND note=?", (POSTER_ADOPTED,))}
        stored_official = {sn for (title,) in conn.execute(
            "SELECT c.title_ja FROM concert c WHERE c.organization_id=? AND c.identity_key NOT LIKE ? AND EXISTS (SELECT 1 FROM performance p WHERE p.concert_id=c.id AND p.local_date>=?)",
            (source_id, f"{source_id}|%?program=%", yomikyo_poster.SEASON_START.isoformat())) if (sn := yomikyo_poster.series_and_number(title))}
        covered = {it["poster"]["tag"] for it in items if f"{source_id}|{canonical(it['source_url'])}" in moved or (it["poster"]["series"], it["poster"]["no"]) in stored_official}
        fresh = [it for it in items if it["poster"]["tag"] not in matched and it["poster"]["tag"] not in covered and it["local_date"] >= _today(now)]
        info = {"season": source["season"], "edition": source["edition"], "pdf": source["pdf"], "pdf_state": pdf, "programmes": len(items), "already_official": len(matched), "adopted": adopted, "already_stored": len(covered - set(matched)), "ingested": len(fresh)}
        return fresh, info, warnings
    except Exception as exc:  # noqa: BLE001 - "never raises" must hold for a bad data file too: the official calendar is already safe to ingest
        return [], None, [f"读响乐季海报的转录文件没处理好（官网日历不受影响）：{type(exc).__name__}: {exc}"[:240]]


def _poster_pdf_state(reader, source: dict) -> tuple[str, str | None]:
    """Is the PDF still the one that was transcribed? (state, warning). A replaced or removed file is a warning (the stored programme may be out
    of date, and a revised edition usually has a new address); a fetch that merely failed is only a note: a flaky network must not turn the run red."""
    try:
        _, meta = _get_bytes(reader, source["pdf"])
    except FetchError as exc:
        if str(exc).startswith("file larger"):
            return "changed", f"读响的乐季 PDF 变了（现在的文件超过大小上限），请对照新版重新核对转录文件：{source['pdf']}"
        return f"not checked ({exc})"[:80], None
    if meta["status"] == 404:
        return "gone", f"读响的乐季 PDF 打不开了（404），可能换了新版，请去官网看一下：{source['pdf']}"
    if meta["status"] != 200:
        return f"not checked (HTTP {meta['status']})", None
    if meta["sha256"] != source["sha256"]:
        return "changed", f"读响的乐季 PDF 被换过了（文件内容变了），请对照新版重新核对转录文件：{source['pdf']}"
    return "unchanged", None


def _nhk(conn, reader, source_id, now, log):
    idx, _ = _get(reader, NHK_JSON_INDEX)
    # A season's concerts straddle two yearly files: the "2026" file runs 2026-06-22 .. 2027-07-04, and "2027" appears while 2026's last
    # concerts are still ahead. Reading only the newest would stop refreshing those (a reschedule, a cancellation, a soloist swap).
    paths = sorted(json.loads(idx)["year_list"])[-NHK_YEAR_FILES:]
    halls = json.loads(_get(reader, NHK_HALLS)[0])
    by_id: dict[str, dict] = {}
    digests: list[str] = []
    warnings: list[str] = []
    for path in reversed(paths):  # newest first: it is the source, so its failure fails the run; a concert in both files keeps the newer record
        data_url = "https://www.nhkso.or.jp" + path
        try:
            data_txt, meta = _get(reader, data_url)
            if meta["status"] != 200:
                raise FetchError(f"HTTP {meta['status']}")
            got = parse_nhk(json.loads(data_txt), halls, data_url, now.isoformat())
        except (FetchError, ParseError, ValueError, KeyError) as exc:
            if path == paths[-1]:
                raise
            warnings.append(f"年度文件没读到（本季较早的演出这次不会刷新）：{data_url}：{type(exc).__name__}: {exc}"[:240])
            continue
        digests.append(meta["sha256"])
        for p in got:
            by_id.setdefault(p["performance_id"], p)
    data_perfs = [p for p in by_id.values() if p["local_date"] and p["local_date"] >= _today(now)]
    # The next season is announced months before the yearly file lists it (a one-page poster, ADR-0009). Its programmes join this run's feed
    # unless the yearly file already has them; a failure here is a warning and never touches the yearly data.
    groups = _season_groups(data_perfs)
    season, season_info, season_warnings, identities = _nhk_season(reader, now, groups)
    adopted, rekeyed, move_warnings = _adopt_season_concerts(conn, source_id, groups, identities)  # independent of the poster: it runs even when the poster could not be read
    warnings += season_warnings + move_warnings
    perfs = data_perfs + season
    # complete=True only judges concerts present in this feed (ingest.py flags a missing *performance of a listed concert*); a concert absent
    # from both files is neither deleted nor flagged, so a skipped older file leaves its concerts as they were. Keep it that way.
    digest = digests[0] if len(digests) == 1 else hashlib.sha256("|".join(digests).encode()).hexdigest()
    result = ingest_source(conn, source_id, perfs, now, complete=True, doc_kind="detail", content_hash=digest)
    ph = {"new": 0, "changed": 0, "unchanged": 0, "skipped_unknown_performance": 0}
    errors = []
    for news in NHK_TICKET_NEWS:
        try:
            html, _ = _get(reader, news)
            batches = parse_nhk_single_ticket_batches(html, news)
            linked = link_nhk_subscription(data_perfs, batches, now)["linked"]
            for k, v in ingest_ticket_phases(conn, source_id, linked, news, now).items():
                ph[k] += v
        except (ValueError, FetchError) as exc:
            errors.append(f"{news}: {exc}")
    return {**result, "items_listed": len(perfs), "items_failed": len(errors), "errors": errors, "warnings": warnings, "year_files": len(digests), "ticket_phases": ph,
            "season_announcement": season_info, "season_adopted": adopted, "season_rekeyed": rekeyed}


def _get_bytes(reader: Reader, url: str):
    try:
        return reader.get_bytes(url, _host(url))
    except FetchError as exc:
        if "transport error" in str(exc):  # one retry for a transient reset, never for 401/403/429
            return reader.get_bytes(url, _host(url))
        raise


def _newest_season_announcement(news: list[dict], today: date):
    """(first year of the season, news item) of the newest 〈速報〉-style announcement of a season that is not over; None when there is none."""
    for item in sorted(news, key=lambda n: n.get("date", ""), reverse=True):
        title = unicodedata.normalize("NFKC", re.sub(r"<[^>]+>", "", item.get("title", "")))
        m = NHK_SEASON_NEWS.search(title)
        if m and (int(m.group(1)) + 1) % 100 == int(m.group(2)) and date(int(m.group(1)) + 1, 8, 31) >= today:
            return int(m.group(1)), item
    return None


def _season_groups(data_perfs: list[dict]) -> dict[str, dict]:
    """The yearly file's concerts by official page: the dates each page lists and whether it is a subscription concert."""
    groups: dict[str, dict] = {}
    for p in data_perfs:
        g = groups.setdefault(canonical(p["source_url"]), {"dates": set(), "subscription": False})
        g["dates"].add(p["local_date"])
        g["subscription"] = g["subscription"] or (p.get("nhk") or {}).get("category") == "subscription"
    return groups


def _official_match(program_key: str, dates: set, groups: dict[str, dict]) -> str | None:
    """The official page that already lists a poster programme, or None. The one rule for both leaving the programme out of the feed and moving
    its stored concert onto that page. By program key first: the official page is /concert/<key>.html (true of all 21 programmes of 2026-27);
    failing that, a subscription concert with exactly the same dates."""
    for url in groups:
        if Path(urlsplit(url).path).stem == program_key:
            return url
    for url, g in groups.items():
        if g["subscription"] and g["dates"] == dates:
            return url
    return None


def _nhk_season(reader, now: datetime, groups: dict[str, dict]):
    """The next season's programmes from the announcement poster: (candidates, summary, warnings, identity of each programme). Never raises:
    whatever goes wrong here is a warning, and the yearly data is ingested regardless."""
    try:
        news = json.loads(_get(reader, NHK_NEWS_INDEX)[0])["news"]
        hit = _newest_season_announcement(news, now.astimezone(JST).date())
        if hit is None:
            return [], None, [], {}
        start_year, item = hit
        page_url = urljoin(NHK_NEWS_INDEX, item["url"])
        html, meta = _get(reader, page_url)
        if meta["status"] != 200:
            raise FetchError(f"HTTP {meta['status']}")
        links = [urljoin(page_url, a["href"]) for a in BeautifulSoup(html, "html.parser").select(".newsText a[href]") if a["href"].split("?")[0].lower().endswith(".pdf")]
        if not links:
            raise ParseError("the announcement page has no PDF")
        failure = None
        for pdf_url in dict.fromkeys(links):
            try:
                events, halls = season_pdf.parse_season_pdf(_get_bytes(reader, pdf_url)[0], start_year)
                break
            except (FetchError, ParseError) as exc:
                failure = exc
        else:
            raise failure
        # Identity and link are the announcement page itself (a real page), one query value per programme. The official concert page does not
        # exist yet; when the yearly file lists the programme, _adopt_season_concerts moves the concert onto that page in place.
        path = urlsplit(page_url).path
        for e in events:
            e["details_url"] = f"{path}?program={e['program_key']}"
        identities = {e["program_key"]: f"nhkso|{canonical(urljoin(page_url, e['details_url']))}" for e in events}
        listed = {e["program_key"] for e in events if _official_match(e["program_key"], {d["date"] for d in e["details"]}, groups)}
        fresh = [e for e in events if e["program_key"] not in listed]
        cands = [c for c in parse_nhk({"concerts": fresh}, halls, pdf_url, now.isoformat()) if c["local_date"] and c["local_date"] >= _today(now)]
        for c in cands:
            c["evidence"]["announcement_url"] = page_url
        info = {"season": f"{start_year}-{(start_year + 1) % 100:02d}", "announcement": page_url, "pdf": pdf_url, "programmes": len(events), "already_in_yearly_file": len(listed), "performances": len(cands)}
        return cands, info, [], identities
    except Exception as exc:  # noqa: BLE001 - "never raises" must hold for a parser bug or an odd news item too: the yearly data is already safe to ingest
        return [], None, [f"下个乐季的速报没读到（年度文件不受影响）：{type(exc).__name__}: {exc}"[:240]], {}


def _adopt_season_concerts(conn, source_id: str, groups: dict[str, dict], identities: dict[str, str]) -> tuple[int, int, list[str]]:
    """Moves the stored poster concerts to where they now belong, keeping each concert row (favourites and reminders hang on its id) so the next
    ingest updates it in place instead of adding a second card: (moved onto an official page, moved to a newer announcement page, warnings).
    - the yearly file lists the programme (``_official_match``): the concert moves onto the official page;
    - otherwise a newer announcement page for the same season gives the programme a new address: the concert follows it.
    A programme that is left out of the feed because an official page lists it, but cannot be moved there (another concert already holds that
    address), is a warning, never a silent orphan."""
    rows = conn.execute("SELECT id, identity_key FROM concert WHERE organization_id=? AND identity_key LIKE ?", (source_id, f"{source_id}|%/news/%?program=%")).fetchall()
    adopted = rekeyed = 0
    warnings: list[str] = []
    for row in rows:
        key = row["identity_key"].rsplit("?program=", 1)[1]
        dates = {r[0] for r in conn.execute("SELECT local_date FROM performance WHERE concert_id=?", (row["id"],))}
        official = _official_match(key, dates, groups)
        target = f"{source_id}|{official}" if official else identities.get(key)
        if not target or target == row["identity_key"]:
            continue
        if conn.execute("SELECT 1 FROM concert WHERE identity_key=? AND id<>?", (target, row["id"])).fetchone():
            warnings.append(f"海报里的 {key} 要迁到 {target.split('|', 1)[1]}，但那个地址已经是另一张卡片，没有合并（请看是不是重复）"[:240])
            continue
        conn.execute("UPDATE concert SET identity_key=? WHERE id=?", (target, row["id"]))
        adopted, rekeyed = adopted + bool(official), rekeyed + (not official)
    return adopted, rekeyed, warnings


def _paged(conn, reader, source_id, now, log, details=True):
    first, tpl, rx = PAGED[source_id]
    body, _ = _get(reader, first)
    shown = max([int(m.group(1)) for a in BeautifulSoup(body, "html.parser").select("a[href]") if (m := re.search(rx, a["href"]))] or [1])
    last = min(MAX_PAGES, shown)
    cands, errors = {}, []
    # A new season makes the list longer. Past the cap the pages already read are still stored, but the run must say it did not read them all.
    warnings = [f"分页器显示 {shown} 页，只读了前 {MAX_PAGES} 页，后面的演出没读到（请调高 MAX_PAGES）"] if shown > MAX_PAGES else []
    for n in range(1, last + 1):
        url = first if n == 1 else tpl.format(n=n)
        try:
            html = body if n == 1 else _get(reader, url)[0]
            recs, _ = parse_list(source_id, html, url, now.isoformat())
            for r in recs:
                cands[r["performance_id"]] = r
        except ParseError as exc:
            errors.append(f"{url}: {exc}")
        log(f"{source_id} page {n}/{last}")
    claims_by_url: dict[str, tuple[dict, list]] = {}
    detailed = 0
    if details and source_id in DETAIL_SOURCES:
        by_url: dict[str, list] = {}
        for c in cands.values():
            if c["category"] != "excluded_domestic_orchestra" and c["local_date"] and c["local_date"] >= _today(now):
                by_url.setdefault(c["source_url"], []).append(c)
        host = _host(first)
        for i, (url, group) in enumerate(sorted(by_url.items()), 1):
            if _host(url) not in (host, host.removeprefix("www."), "www." + host.removeprefix("www.")):
                continue  # concerts run by another presenter link to its site: keep the list-level facts, do not follow
            try:
                html, meta = _get(reader, url)
                if meta["status"] != 200:
                    errors.append(f"{url}: HTTP {meta['status']}")
                    continue
                days = [c["local_date"] for c in group if c["local_date"]]
                d = parse_detail(source_id, html, url, date.fromisoformat(min(days)) if days else None)
                if source_id != "tmso":  # 都响: facts only, nothing extra is kept (ADR-0001)
                    pageobs.record_page(conn, source_id, url, html, now)
            except (ParseError, FetchError) as exc:  # one bad page is reported; an access stop pauses the host inside Reader
                errors.append(f"{url}: {exc}")
                continue
            for c in group:
                c["programme_items"], c["artists_items"] = d["programme_items"], d["artists"]
            detailed += 1
            if d["ticket_claims"]:
                claims_by_url[url] = (group, d["ticket_claims"])
            log(f"{source_id} detail {i}/{len(by_url)}")
    result = ingest_source(conn, source_id, list(cands.values()), now, complete=False, doc_kind="list")
    ph = {"new": 0, "changed": 0, "unchanged": 0, "skipped_unknown_performance": 0}
    for url, (group, claims) in claims_by_url.items():
        linked = link_presenter_claims({"performances": group, "ticket_claims": claims}, now, channel="official")["linked"]
        if linked:
            for k, v in ingest_ticket_phases(conn, source_id, linked, url, now).items():
                ph[k] += v
    return {**result, "items_listed": len(cands), "pages": last, "details_parsed": detailed, "items_failed": len(errors), "errors": errors[:10], "warnings": warnings, "ticket_phases": ph}


def sync_source(conn: sqlite3.Connection, reader: Reader, source_id: str, now: datetime | None = None, log: Callable[[str], None] = lambda s: None, details: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    if source_id in DEFERRED:
        return {"source_id": source_id, "status": "skipped", "reason": "deferred by the user (ADR-0001)"}
    if source_id not in SUPPORTED:
        return {"source_id": source_id, "status": "skipped", "reason": "no adapter"}
    try:
        if source_id in ("japanarts", "kajimoto"):
            out = _presenter(conn, reader, source_id, now, log)
        elif source_id == "yomikyo":
            out = _yomikyo(conn, reader, source_id, now, log)
        elif source_id == "nhkso":
            out = _nhk(conn, reader, source_id, now, log)
        else:
            out = _paged(conn, reader, source_id, now, log, details)
    except (FetchError, ParseError, ValueError, KeyError) as exc:  # source-level failure: recorded, other sources unaffected
        conn.execute("INSERT INTO ingestion_run (id,source_id,started_at,ended_at,status,error_summary) VALUES (lower(hex(randomblob(16))),?,?,?, 'failed', ?)",
                     (source_id, now.isoformat(), datetime.now(timezone.utc).isoformat(), f"{type(exc).__name__}: {exc}"[:300]))
        conn.commit()
        reminders.reconcile_all(conn, now)
        return {"source_id": source_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    # Not in a ``finally``: reconcile commits, and an UNcaught error must still leave that source's half-written ingest uncommitted (T11).
    reminders.reconcile_all(conn, now)  # a performance that became cancelled/postponed must not keep a scheduled delivery
    return {"source_id": source_id, **out}
