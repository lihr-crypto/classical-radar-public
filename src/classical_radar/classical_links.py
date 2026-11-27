"""Apple Music Classical page ids for the browse pages (ADR-0013).

The browse pages (composer, piece, conductor, soloist) get a button that opens the matching page in Apple's Classical app. Apple's pages are
``/jp/artist/<digits>`` and ``/jp/work/<slug>``; those ids are Apple's, so a reviewed table (``web/classical-links.js``) holds them. This module
builds that table. It runs by hand (``scripts/resolve_classical_links.py``), never in CI and never in the daily refresh.

What it may request (anything else raises ``Refused``):
  * ``https://itunes.apple.com/search?...entity=musicArtist``: Apple's documented public lookup API, to find candidate artist ids for a name;
  * ``https://classical.music.apple.com/jp/artist/<digits>``: the artist page, to check that the candidate really is that person (the page
    title is the Japanese name, the subtitle the role) and, for a composer, to read its "有名な作品" shelf (title, opus, work slug);
  * ``https://classical.music.apple.com/sitemaps_classical_*work*``: the work sitemaps that robots.txt itself lists (slugs only, no titles), once;
  * ``https://classical.music.apple.com/jp/work/<slug>``: a work page, to READ its title and its composer (ADR-0015). Together with the sitemap this
    gives a composer's complete work list, which the artist page does not (it holds only the 15 works of its shelf).
Apple's robots.txt (classical.music.apple.com) disallows ``*/search?*``, ``/query/*``, ``/api/*``, ``/v1/*`` and ``*?i=*``: the Classical SEARCH
page is never fetched. Requests are slow (>= 2.2 s per page, >= 3.2 s per API call), cached on disk, capped, and stop at the first 403 / 429.

Nothing here guesses: a name that does not match exactly, or matches two Apple pages, gets no link (the button is simply not shown).
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import re
import time
import unicodedata
import urllib.parse
from pathlib import Path

import httpx

from .works import _ALIAS, _DISPLAY, n, work_key

BASE = "https://classical.music.apple.com/jp/"
UA = "ClassicalRadarPOC/0.1 (+https://github.com/lihr-crypto/classical-radar-public; low-volume source evaluation)"
PAGE_INTERVAL, API_INTERVAL = 2.2, 3.2
RETRY_WAITS = (10, 30, 60)  # seconds before the 2nd, 3rd and 4th try of one request that timed out or lost its connection

_PAGE_URL = re.compile(r"^https://classical\.music\.apple\.com/jp/artist/\d{1,12}$")
_WORK_URL = re.compile(r"^https://classical\.music\.apple\.com/jp/work/[a-z0-9-]{3,100}$")
_SITEMAP_URL = re.compile(r"^https://classical\.music\.apple\.com/sitemaps_classical_(?:index_work_\d{1,3}\.xml|work_\d{1,3}_\d{1,3}\.xml\.gz)$")
SITEMAP_INDEX = "https://classical.music.apple.com/sitemaps_classical_index_work_1.xml"
_API_URL = re.compile(r"^https://itunes\.apple\.com/search\?[^#]*\bentity=musicArtist\b")
_ROBOTS_DISALLOWED = re.compile(r"/search\?|/query/|/api/|/v1/|/WebObjects/|/includes/|[?&]i=")  # robots.txt of the Classical host
_DATA = re.compile(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', re.S)
SLUG = re.compile(r"^[a-z0-9-]{3,100}$")
_ARRANGED = re.compile(r"編(?!成)|版|arr\.|アレンジ|transcr|orch\.|管弦楽用|for ", re.I)  # an arrangement is not the piece itself
_MARKS = "*★☆◆◇♥♡※●○■□▲△♪♫"  # the marks a scraped line carries; the same glyphs as MARKS in web/app.js
_BRACKETS = "《》「」『』〈〉⟨⟩“”‘’\"'()（）[]【】"
_ROLE_PREFIX = re.compile(r"^(?:指揮|独奏|演奏|ピアノ|ヴァイオリン|チェロ|歌)\s*[:：]\s*")  # Apple writes a few names as "指揮:アンドレイ・ボレイコ"


class Refused(Exception):
    """A URL this tool must never request."""


class Stopped(Exception):
    """The server said 403 / 429, or the request cap was reached: stop, do not retry."""


class CapReached(Stopped):
    """Only the request cap: what was fetched stays cached and a later run resumes; not a sign the server objects."""


def bfold(text: str) -> str:
    """The same folding as ``bfold`` in web/app.js (width, case, accents, whitespace and punctuation, a dash written for ー)."""
    t = unicodedata.normalize("NFKC", str(text or "")).lower()
    t = re.sub(r"[―—]", "ー", t)
    t = unicodedata.normalize("NFD", t)
    t = re.sub(r"[̀-ͯ]", "", t)
    t = re.sub(r"[\s.・·=＝|\-‐‑–]", "", t)
    return unicodedata.normalize("NFC", t)


def name_fold(text: str) -> str:
    """The same folding as ``nameFold`` in web/app.js: ``bfold`` minus the marks a scraped line carries ("カミラ・ニールンド◇")."""
    return bfold(re.sub(f"[{re.escape(_MARKS)}]", "", unicodedata.normalize("NFKC", str(text or ""))))


def apple_name(title: str) -> str:
    """An Apple artist title as a bare name (a leading role such as "指揮:" removed)."""
    return _ROLE_PREFIX.sub("", title or "").strip()


def clean_name(text: str) -> str:
    """A name of ours as it is looked up: marks removed, spaces squeezed."""
    return re.sub(r"\s+", " ", re.sub(f"[{re.escape(_MARKS)}]", "", unicodedata.normalize("NFKC", str(text or "")))).strip()


def assert_allowed(url: str) -> None:
    p = urllib.parse.urlsplit(url)
    if p.scheme == "https" and p.netloc == "classical.music.apple.com":
        if (_PAGE_URL.match(url) or _WORK_URL.match(url) or _SITEMAP_URL.match(url)) and not _ROBOTS_DISALLOWED.search(url):
            return
    elif p.scheme == "https" and p.netloc == "itunes.apple.com" and p.path == "/search" and _API_URL.match(url):
        return
    raise Refused(url)


class Fetcher:
    """Cached, throttled, capped GETs. ``get`` returns (status, body); a cached answer costs nothing."""

    def __init__(self, cache_dir: str | Path, *, cap: int = 2500, client=None, sleep=time.sleep, clock=time.monotonic):
        self.dir, self.cap, self.sleep, self.clock = Path(cache_dir), cap, sleep, clock
        self.dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(headers={"User-Agent": UA}, timeout=25, follow_redirects=False)
        self.sent, self.last = 0, {}

    def _send(self, url: str):
        """One real request: cap, spacing by host, and the stop at 403 / 429. Only ``get`` / ``get_parsed`` / ``get_bytes`` call it, after the guard."""
        if self.sent >= self.cap:
            raise CapReached(f"request cap {self.cap} reached")
        host = urllib.parse.urlsplit(url).netloc
        wait = (API_INTERVAL if host == "itunes.apple.com" else PAGE_INTERVAL) - (self.clock() - self.last.get(host, -1e9))
        if wait > 0:
            self.sleep(wait)
        for attempt in range(len(RETRY_WAITS) + 1):
            try:
                r = self.client.get(url)
                break
            except httpx.TransportError as e:  # a timeout or a dropped connection (the Mac slept, the Wi-Fi blinked): a long crawl must not die on one of them
                self.last[host] = self.clock()
                self.sent += 1  # every try counts against the cap
                if attempt == len(RETRY_WAITS):
                    raise Stopped(f"{host} could not be reached after {attempt + 1} tries: {type(e).__name__}") from e
                self.sleep(RETRY_WAITS[attempt])
        self.last[host] = self.clock()
        self.sent += 1
        if r.status_code in (403, 429):
            raise Stopped(f"{host} answered {r.status_code}")
        return r

    def _file(self, url: str, prefix: str, ext: str) -> Path:
        return self.dir / (prefix + hashlib.sha256(url.encode()).hexdigest() + ext)

    def get(self, url: str) -> tuple[int, str]:
        assert_allowed(url)
        f = self._file(url, "", ".json")
        if f.exists():
            c = json.loads(f.read_text("utf8"))
            return c["status"], c["body"]
        r = self._send(url)
        body = r.text if r.status_code == 200 else ""
        f.write_text(json.dumps({"url": url, "status": r.status_code, "body": body}, ensure_ascii=False), "utf8")
        return r.status_code, body

    def get_parsed(self, url: str, parse) -> tuple[int, object]:
        """Like ``get`` but only ``parse(body)`` is kept on disk: a work page is 230 KB and a full run reads thousands of them."""
        assert_allowed(url)
        f = self._file(url, "p-", ".json")
        if f.exists():
            c = json.loads(f.read_text("utf8"))
            return c["status"], c["parsed"]
        r = self._send(url)
        parsed = parse(r.text) if r.status_code == 200 else None
        f.write_text(json.dumps({"url": url, "status": r.status_code, "parsed": parsed}, ensure_ascii=False), "utf8")
        return r.status_code, parsed

    def get_bytes(self, url: str) -> bytes | None:
        """A binary answer (a gzipped sitemap), or None for anything but 200. Cached like the rest."""
        assert_allowed(url)
        f = self._file(url, "b-", ".bin")
        if f.exists():
            return f.read_bytes() or None
        r = self._send(url)
        content = r.content if r.status_code == 200 else b""
        f.write_bytes(content)
        return content or None


def parse_artist_page(html: str) -> dict | None:
    """{id, title, role, start, end, works: [{title, subtitle, slug}], shelves} from an artist page, or None when it is not one."""
    m = _DATA.search(html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))["data"][0]["data"]
        hdr = data["header"]
        if hdr.get("type") != "artist" or not str(hdr.get("id", "")).isdigit() or not hdr.get("title"):
            return None
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
    works = []
    for sec in data.get("sections") or []:
        if sec.get("itemKind") != "shelfListItem":
            continue
        for it in sec.get("items") or []:
            url = it.get("url") or ""
            if url.startswith("/jp/work/") and SLUG.match(url[len("/jp/work/"):]):
                works.append({"title": it.get("title") or "", "subtitle": it.get("subtitle") or "", "slug": url[len("/jp/work/"):]})
    return {"id": int(hdr["id"]), "title": hdr["title"], "role": hdr.get("subtitle") or "", "start": hdr.get("startYear"), "end": hdr.get("endYear"),
            "works": works, "shelves": len(data.get("sections") or [])}


def artist_page(fetcher: Fetcher, artist_id: int) -> dict | None:
    status, body = fetcher.get(f"{BASE}artist/{int(artist_id)}")
    page = parse_artist_page(body) if status == 200 else None
    return page if page and page["id"] == int(artist_id) else None


_WORK_LOC = re.compile(r"<loc>https://classical\.music\.apple\.com/[a-z]{2}/work/([a-z0-9-]+)-pp(\d+)</loc>")
_WORK_HOME = "https://classical.music.apple.com/jp/work/"


def parse_work_page(html: str) -> dict | None:
    """{slug, title, subtitle, composer_id} from a work page, or None. The slug is the page's own canonical one: a page that is not the work it
    was asked for (or has no composer id) is not trusted."""
    m = _DATA.search(html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))["data"][0]["data"]
        hdr, canon = data["header"], data["canonicalURL"]
        cid = hdr["composerAction"]["destination"]["id"]
        if hdr.get("type") != "work" or not hdr.get("title") or not str(cid).isdigit() or not str(canon).startswith(_WORK_HOME):
            return None
        slug = canon[len(_WORK_HOME):]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
    if not SLUG.match(slug):
        return None
    return {"slug": slug, "title": hdr["title"], "subtitle": hdr.get("subtitle") or "", "composer_id": int(cid)}


def parse_sitemap(blob: bytes) -> set[tuple[str, int]]:
    """{(composer slug, number)} from one gzipped work sitemap. Only the ``<loc>`` of each entry counts (the xhtml alternates repeat it per locale)."""
    return {(m.group(1), int(m.group(2))) for m in _WORK_LOC.finditer(gzip.decompress(blob).decode("utf8"))}


def load_work_slugs(fetcher: Fetcher) -> dict[str, list[int]]:
    """{composer slug: sorted work numbers} from Apple's published work sitemaps (robots.txt lists them). Built once from the ~100 files and kept in
    ``work_slugs.json`` next to the cache; a run that stops half-way (cap) writes nothing."""
    f = fetcher.dir / "work_slugs.json"
    if f.exists():
        return json.loads(f.read_text("utf8"))
    status, index = fetcher.get(SITEMAP_INDEX)
    files = re.findall(r"<loc>(https://classical\.music\.apple\.com/sitemaps_classical_work_\d{1,3}_\d{1,3}\.xml\.gz)</loc>", index) if status == 200 else []
    if not files:
        raise Stopped("the work sitemap index could not be read")
    found: dict[str, set[int]] = collections.defaultdict(set)
    for u in files:
        blob = fetcher.get_bytes(u)
        if blob is None:
            raise Stopped(f"a work sitemap could not be read: {u}")
        for prefix, num in parse_sitemap(blob):
            found[prefix].add(num)
    out = {k: sorted(v) for k, v in found.items()}
    f.write_text(json.dumps(out, separators=(",", ":")), "utf8")
    return out


def composer_slug(page: dict) -> str | None:
    """The slug prefix Apple files this composer's works under: the commonest one on the page's shelf (a shelf can carry a foreign work or two)."""
    count = collections.Counter(m.group(1) for w in page["works"] if (m := re.match(r"^(.*)-pp\d+$", w["slug"])))
    return count.most_common(1)[0][0] if count else None


def complete_works(fetcher: Fetcher, page: dict, slugs: dict[str, list[int]]) -> list[dict] | None:
    """Every work filed under this composer's own slug prefix (not "every work he ever wrote": a piece filed under another prefix is not here):
    [{title, subtitle, slug}] in the shape of ``page["works"]``. One work page per slug, cached. A page whose composer id is not this composer's
    is dropped (prefixes can mix). None when the list could not be completed (a work page failed with something other than 404): a partial list
    could make a title look unique, so the caller then keeps the 15-work shelf. ``CapReached`` / ``Stopped`` propagate."""
    prefix = composer_slug(page)
    if not prefix or prefix not in slugs:
        return None
    out = []
    for num in slugs[prefix]:
        slug = f"{prefix}-pp{num}"
        status, w = fetcher.get_parsed(f"{BASE}work/{slug}", parse_work_page)
        if status == 404:
            continue
        if status != 200:
            return None
        if w and w["slug"] == slug and w["composer_id"] == page["id"]:
            out.append({"title": w["title"], "subtitle": w["subtitle"], "slug": slug})
    return out


def candidate_ids(fetcher: Fetcher, term: str, *, limit: int = 5) -> list[int]:
    """Artist ids the lookup API offers for a name, best first, classical-looking genres only (a 404 on the Classical host rules out the rest)."""
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": term, "country": "jp", "entity": "musicArtist", "limit": limit})
    status, body = fetcher.get(url)
    if status != 200:
        return []
    try:
        rows = json.loads(body).get("results") or []
    except ValueError:
        return []
    ok = {"クラシック", "classical", "オペラ", "opera"}
    seen, out = set(), []
    for r in rows:
        i = r.get("artistId")
        if isinstance(i, int) and i not in seen and str(r.get("primaryGenreName") or "").lower() in ok:
            seen.add(i)
            out.append(i)
    return out


def composer_forms(key: str) -> set[str]:
    """Every spelling the alias table knows for a composer key, in comparison form."""
    return {a for a, k in _ALIAS.items() if k == key}


def classify_composer(key: str, page: dict) -> str | None:
    """'exact' when the page's Japanese title is one of the key's own spellings, 'contains' when a spelling is only part of it (ベルク in
    シェーンベルク), None when the page is not a composer at all."""
    if "作曲" not in page["role"]:
        return None
    t, forms = n(page["title"]), composer_forms(key)
    if t in forms:
        return "exact"
    return "contains" if any(f and f in t for f in forms) else None


def resolve_composer(fetcher: Fetcher, key: str, reviewed: dict[str, int] | None = None) -> dict:
    """{key, verdict, id, page, seen}: verdict is accepted / reviewed / ambiguous / review / none. Only an unambiguous exact match is accepted on its
    own; a 'contains' match (a surname only) is listed for a person to look at and used only once it is in ``reviewed``."""
    reviewed = reviewed or {}
    seen = []
    if key in reviewed:
        page = artist_page(fetcher, reviewed[key])
        return {"key": key, "verdict": "reviewed" if page and "作曲" in page["role"] else "none", "id": reviewed[key], "page": page, "seen": seen}
    for cid in candidate_ids(fetcher, _DISPLAY[key])[:3]:
        page = artist_page(fetcher, cid)
        if page and (kind := classify_composer(key, page)):
            seen.append((kind, page))
    exact = [p for k, p in seen if k == "exact"]
    if len(exact) == 1:
        return {"key": key, "verdict": "accepted", "id": exact[0]["id"], "page": exact[0], "seen": seen}
    return {"key": key, "verdict": "ambiguous" if len(exact) > 1 else "review" if seen else "none", "id": None, "page": None, "seen": seen}


def works_detail(key: str, page: dict, texts: dict[str, set[str]] | None = None, pins: dict[str, str] | None = None) -> dict[str, tuple[str, str, str]]:
    """work_key -> (slug, Apple title, Apple subtitle). The key is made by the same function that keys our programmes, so a piece is linked only
    when both sides name it the same generic way. An arrangement (編曲 / 版) is never a candidate. ``page["works"]`` is the 15-work shelf, plus the
    rest of the composer's list when it was read completely (those entries carry ``extra``).

    A key that two different Apple works would get is settled only by OUR texts for that key (``texts``: work_key -> programme texts): a work whose
    key signature or catalogue number clashes with any of them is no candidate any more, and the key is linked when exactly one work is left
    (Beethoven's "ヴァイオリン協奏曲 ニ長調" is the Op. 61, not the fragment in C, WoO 5). A key none of our texts carries is judged on the shelf
    alone, as before: a work found only in the long list is never linked blind, because nothing audits it.

    ``pins`` (work_key -> slug) are a person's decisions for a tie our texts cannot settle (Dvořák's seventh: Apple's page with Op. 70 next to a
    same-titled long-list page with only a B number). A pin counts only while that slug still carries that very key on the page, so a stale pin
    does nothing; the audit afterwards still checks it against our texts like any other link."""
    found: dict[str, dict[str, tuple[str, str, bool]]] = {}
    for w in page["works"]:
        if _ARRANGED.search(w["title"] + " " + w["subtitle"]):
            continue
        k = work_key(key, w["title"])
        if k:
            found.setdefault(k, {})[w["slug"]] = (w["title"], w["subtitle"], bool(w.get("extra")))
    out: dict[str, tuple[str, str, str]] = {}
    for k, d in found.items():
        ours = (texts or {}).get(k)
        if not ours:
            cand = {s: v for s, v in d.items() if not v[2]}
        elif len(d) == 1:
            cand = d
        else:
            cand = {s: v for s, v in d.items() if not any(clash(x, v[0], v[1]) for x in ours)}
        if len(cand) == 1:
            slug, (title, sub, _) = next(iter(cand.items()))
            out[k] = (slug, title, sub)
    for k, slug in (pins or {}).items():
        if slug in found.get(k, {}):
            title, sub, _ = found[k][slug]
            out[k] = (slug, title, sub)
    return out


def works_of(key: str, page: dict) -> dict[str, str]:
    return {k: v[0] for k, v in works_detail(key, page).items()}


_TONE = re.compile(r"([嬰変]?[ハニホヘトイロ])\s*(長調|短調)")
_CATALOGUE = re.compile(r"(?<![a-z])(op|kv|k|bwv|d|hob|rv|hwv|sz|fwv|wab|woo|av|jw|th|fp|cd|h|s|m|b|l|p|ms|sw|trv|bb|jb|wq|j)\.?\s*(\d+[a-z]?)")


def _numbers(text: str) -> dict[str, set[str]]:
    """prefix -> numbers for the opus and catalogue numbers a text carries (作品 counts as op)."""
    t = re.sub(r"作品\s*(?=\d)", "op", unicodedata.normalize("NFKC", text or "").lower())
    out: dict[str, set[str]] = {}
    for prefix, num in _CATALOGUE.findall(t):
        out.setdefault(prefix, set()).add(num)
    return out


def clash(ours: str, title: str, subtitle: str = "") -> str | None:
    """Why one of our programme texts cannot be the piece Apple's title names, else None: a different key signature, or the same catalogue
    (op / K / BWV / D / Hob / ...) with a different number. Numbering is not enough: Schubert's "第8番" is the Unfinished (ロ短調) at Apple
    but the Great (ハ長調, D944) in many Japanese programmes."""
    a, b = unicodedata.normalize("NFKC", f"{title} {subtitle}"), unicodedata.normalize("NFKC", ours)
    ta, tb = set(_TONE.findall(a)), set(_TONE.findall(b))
    if ta and tb and ta != tb:
        return f"key {sorted(tb)} vs {sorted(ta)}"
    na, nb = _numbers(a), _numbers(b)
    for prefix in sorted(set(na) & set(nb)):
        if na[prefix] != nb[prefix]:
            return f"{prefix} {sorted(nb[prefix])} vs {sorted(na[prefix])}"
    return None


def audit_works(detail: dict[str, tuple[str, str, str]], texts: dict[str, set[str]], skip=()) -> tuple[dict[str, str], dict[str, str]]:
    """(kept work_key -> slug, dropped work_key -> reason). A key is dropped when a person listed it in ``skip``, or when any of OUR programme
    texts under that key clashes with Apple's title for it."""
    kept, dropped = {}, {}
    for k, (slug, title, sub) in detail.items():
        why = "skipped by a person" if k in set(skip) else next((f"{x!r}: {c}" for x in sorted(texts.get(k, ())) if (c := clash(x, title, sub))), None)
        if why:
            dropped[k] = why
        else:
            kept[k] = slug
    return kept, dropped


def resolve_person(fetcher: Fetcher, name: str) -> dict:
    """A conductor or soloist: accepted only when exactly one candidate's page title is this very name (marks and a leading role removed,
    folded) and it has a role."""
    want, hits = name_fold(name), []
    for cid in candidate_ids(fetcher, clean_name(name))[:3]:
        page = artist_page(fetcher, cid)
        if page and page["role"] and name_fold(apple_name(page["title"])) == want:
            hits.append(page)
    if len(hits) == 1:
        return {"name": name, "verdict": "accepted", "id": hits[0]["id"], "page": hits[0]}
    return {"name": name, "verdict": "ambiguous" if hits else "none", "id": None, "page": None, "hits": hits}


def resolve_composer_by_name(fetcher: Fetcher, name: str, reviewed: dict[str, int] | None = None) -> dict:
    """A composer that has no composer_key (so the table cannot be keyed by one): the page title must be exactly this name to be accepted; a page
    whose title only CONTAINS it (ブルッフ in マックス・ブルッフ) is listed for a person to look at and used only once it is in ``reviewed``."""
    reviewed = reviewed or {}
    want = name_fold(name)
    if want in reviewed:
        page = artist_page(fetcher, reviewed[want])
        return {"name": name, "verdict": "reviewed" if page and "作曲" in page["role"] else "none", "id": reviewed[want], "page": page, "seen": []}
    seen = []
    for cid in candidate_ids(fetcher, clean_name(name))[:3]:
        page = artist_page(fetcher, cid)
        if not page or "作曲" not in page["role"]:
            continue
        t = name_fold(apple_name(page["title"]))
        if t == want:
            seen.append(("exact", page))
        elif want and want in t:
            seen.append(("contains", page))
    exact = [p for k, p in seen if k == "exact"]
    if len(exact) == 1:
        return {"name": name, "verdict": "accepted", "id": exact[0]["id"], "page": exact[0], "seen": seen}
    return {"name": name, "verdict": "ambiguous" if len(exact) > 1 else "review" if seen else "none", "id": None, "page": None, "seen": seen}


# ---- pieces without a generic key: titled works matched against the composer's famous-works shelf (proposals only; a person reads each one) ----
_GENRE = sorted("""協奏曲 交響曲 交響詩 交響的 協奏的 ソナタ ソナチネ 四重奏曲 四重奏 三重奏曲 三重奏 五重奏曲 五重奏 六重奏 八重奏 二重奏 序曲 前奏曲 夜想曲 ノクターン セレナード セレナーデ ロマンス
    舞曲 組曲 変奏曲 幻想曲 狂詩曲 ラプソディ 練習曲 エチュード バラード スケルツォ ワルツ ポロネーズ マズルカ 即興曲 歌曲集 歌曲 小品 行進曲 ロンド アダージョ エア アヴェマリア ミサ曲 ミサ
    レクイエム カプリス フーガ プレリュード パルティータ アリア 間奏曲 ディヴェルティメント カノン 舟歌 子守歌 カデンツァ 歌劇 オペラ バレエ メヌエット ガヴォット ブーレ ジーグ サラバンド
    タランテラ 管弦楽 弦楽 管楽 吹奏楽 合唱 室内 独奏 無伴奏 ピアノ ヴァイオリン ヴィオラ チェロ コントラバス フルート オーボエ クラリネット ファゴット ホルン トランペット
    トロンボーン チューバ オルガン ハープ ギター マンドリン サクソフォン リコーダー ための つの""".split(), key=len, reverse=True)
_GENRE_RE = re.compile("|".join(map(re.escape, _GENRE)))
_ARR_OR_EXCERPT = re.compile(r"編曲|編|arr|版|transcr|アレンジ|管弦楽用|より|から|抜粋|楽章|第\d+曲|全\d+曲|ほか|他|ハイライト", re.I)
_CATALOGUE_TOKEN = re.compile(r"(?<![a-z])(?:op|kv|k|bwv|d|hob|rv|hwv|sz|fwv|wab|woo|av|jw|th|fp|cd|h|s|m|b|l|p|ms|sw|trv|bb|jb|wq|j)\.?\s*\d+[a-z]?(?:\s*[-/,、]\s*\d+[a-z]?)*")


def core_title(text: str) -> str:
    """A title without what is only notation or metadata: marks, brackets, opus / catalogue numbers, key signatures, spaces and dots. Used to
    compare OUR title with Apple's; numbers of a piece in a series (第N番) stay."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(f"[{re.escape(_MARKS + _BRACKETS)}]", "", t)
    t = re.sub(r"作品\s*(?=\d)", "op", t)
    t = _CATALOGUE_TOKEN.sub("", t)
    t = _TONE.sub("", t)
    return re.sub(r"[\s・.,:;、。\-–—/／~～!！?？_]", "", t)


def is_generic(core: str) -> bool:
    """A core title that is only genre and instrument words, connectors and numbers (ピアノ協奏曲, 夜想曲, ヴァイオリン・ソナタ第2番): unique among
    Apple's fifteen does not make it the only one the composer wrote, so such a title is never proposed."""
    rest = re.sub(r"[\d第番曲の と・＆&]", "", _GENRE_RE.sub("", core))
    return not rest


def excluded_text(text: str) -> bool:
    """An arrangement or an excerpt is not the whole work Apple's page is about."""
    return bool(_ARR_OR_EXCERPT.search(unicodedata.normalize("NFKC", text or "")))


_LOOSE_FLOOR = 0.7  # least similarity of two core titles that a person is shown
_LOOSE_SHORT = 6  # a core title shorter than this is compared by containment only: its bigrams mean nothing
_NUMBER = re.compile(r"第?\s*(\d+)\s*番")
_EXCERPT_DASH = re.compile(r"[─―—–]\s*[「『《“]")  # 楽劇「トリスタンとイゾルデ」─「愛の夜よ」: a number out of a stage work


def loose_score(a: str, b: str) -> float:
    """0..1: how alike two core titles are. One inside the other counts from two characters on (the longer the shared part, the nearer to 1);
    otherwise bigram overlap, and only when both are at least ``_LOOSE_SHORT`` long."""
    if not a or not b:
        return 0.0
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 2 and short in long_:
        return 0.6 + 0.4 * len(short) / len(long_)
    if len(short) < _LOOSE_SHORT:
        return 0.0
    ga, gb = {a[i:i + 2] for i in range(len(a) - 1)}, {b[i:i + 2] for i in range(len(b) - 1)}
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def _shares_evidence(texts: list[str], w: dict) -> bool:
    """A key signature or a catalogue number that OUR text and Apple's title both carry. A generic title (ヴァイオリン・ソナタ) needs this:
    'nothing clashes' does not make it the one work."""
    theirs = unicodedata.normalize("NFKC", f"{w['title']} {w['subtitle']}")
    tone, nums = set(_TONE.findall(theirs)), _numbers(theirs)
    for t in texts:
        t = unicodedata.normalize("NFKC", t)
        if tone & set(_TONE.findall(t)) or any(nums.get(p, set()) & v for p, v in _numbers(t).items()):
            return True
    return False


def _loose_hints(texts: list[str], w: dict) -> list[str]:
    """Reasons a person should look twice (the rules the review applies): an overture is not the whole opera, a suite is not the whole ballet, a
    number out of a stage work is not the work."""
    ours, theirs = " ".join(texts), f"{w['title']} {w['subtitle']}"
    hints = []
    if "序曲" in ours and "序曲" not in theirs:
        hints.append("RULE-a:overture-vs-page-without-overture")
    if ("組曲" in ours) != ("組曲" in theirs):
        hints.append("RULE-b:suite-vs-whole")
    if any(_EXCERPT_DASH.search(unicodedata.normalize("NFKC", t)) or "─" in t for t in texts):
        hints.append("RULE-d:excerpt")
    return hints


def _loose_proposals(e: dict, core: str, works: list[dict], arranged: set[str]) -> list[dict]:
    """Candidates of the looser tier for one piece: Apple works whose core title is ALIKE (``loose_score`` >= the floor), best first; those within
    0.05 of the best stay (a person decides between them). Dropped here: a clash of key or catalogue number (as in the exact tier), and a piece
    number ('第N番') that both sides state and that differs. A generic title needs ``_shares_evidence``."""
    ours_numbers = {int(x) for t in e["texts"] for x in _NUMBER.findall(unicodedata.normalize("NFKC", t))}
    scored = []
    for w in works:
        acore = core_title(w["title"])
        sc = loose_score(core, acore)
        if sc < _LOOSE_FLOOR:
            continue
        if any(clash(t, w["title"], w["subtitle"]) for t in e["texts"]):
            continue
        theirs_numbers = {int(x) for x in _NUMBER.findall(unicodedata.normalize("NFKC", f"{w['title']} {w['subtitle']}"))}
        if ours_numbers and theirs_numbers and ours_numbers != theirs_numbers:
            continue
        if (is_generic(core) or is_generic(acore)) and not _shares_evidence(e["texts"], w):  # the part they share may be only a genre, with names after it
            continue
        scored.append((sc, w))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, w in scored[:3]:
        if sc < scored[0][0] - 0.05:
            break
        out.append({"id": e["id"], "n": e["n"], "texts": e["texts"], "title": w["title"], "subtitle": w["subtitle"], "slug": w["slug"],
                    "twin": core_title(w["title"]) in arranged, "loose": True, "score": round(sc, 2), "hints": _loose_hints(e["texts"], w)})
    return out


def propose_works(entities: list[dict], page: dict, loose: bool = False) -> list[dict]:
    """Pieces of ONE composer (``entities``: the node helper's work entries, unkeyed; one flagged ``arranged`` because a programme line names an
    arranger in its composer part is never proposed) that match exactly one non-arranged work on the composer's
    list (the shelf, or the complete list of ``complete_works``) by core title, are not generic, and do not clash with Apple's title. Proposals only.
    ``twin`` says Apple also files an ARRANGEMENT of the same title under this composer (an orchestration, a piano version): the person who reads the
    proposal then has to be sure our programme means the original.

    ``loose`` adds a second tier for what the exact tier cannot name: our title carries a word Apple's does not (交響詩《フィンランディア》 against
    "フィンランディア Op. 26"), writes the long vowel another way, or is generic but shares a key signature or catalogue number with Apple's title.
    Those come back with ``loose``, a ``score`` and ``hints`` (RULE-a/b/d: the places where the review has to say no). They are never links by
    themselves: a person reads each one and adds it to the reviewed ``works``. An exact hit that clashes ends the search for that piece (it IS
    another piece); an excerpt or arrangement on our side is never looked at."""
    apple: dict[str, list[dict]] = {}
    arranged: set[str] = set()
    listed: list[dict] = []
    for w in page["works"]:
        if _ARRANGED.search(w["title"] + " " + w["subtitle"]):
            arranged |= {core_title(w["title"]), core_title(re.sub(r"[(（][^)）]*[)）]", "", w["title"]))}
            continue
        apple.setdefault(core_title(w["title"]), []).append(w)
        listed.append(w)
    out = []
    for e in entities:
        if e.get("keyed") or e.get("arranged") or any(excluded_text(t) for t in e["texts"]):
            continue
        cores = {core_title(t) for t in e["texts"]}
        if len(cores) != 1:
            continue
        core = next(iter(cores))
        hit = apple.get(core, [])
        if core and not is_generic(core) and len(hit) == 1:
            w = hit[0]
            if any(clash(t, w["title"], w["subtitle"]) for t in e["texts"]):
                continue
            out.append({"id": e["id"], "n": e["n"], "texts": e["texts"], "title": w["title"], "subtitle": w["subtitle"], "slug": w["slug"], "twin": core in arranged})
        elif loose and core:
            out.extend(_loose_proposals(e, core, listed, arranged))
    mixed = {e["id"] for e in entities if 0 < e.get("arranged_rows", 0) < e.get("rows", 0)}
    for pr in out:
        pr["mixed"] = pr["id"] in mixed  # some of its programme lines name an arranger and some do not: the person reading the proposal has to look
    return out


# ---- composers written with initials ("F.リスト"): the name folds to its own id, so a person says whose it is (reviewed ``composer_alias``) ----
_FAMILY_NAMES = ("バッハ", "シュトラウス", "ハイドン", "モーツァルト", "シューマン", "メンデルスゾーン", "ウィリアムズ", "フランク", "スカルラッティ", "クープラン")  # several composers share them
_GENERATION = re.compile(r"(?:(?:ii?|[12])世|ii)$")  # "…i世", "…ii世", "…1世", "…2世" or "…ii"


def apply_composer_aliases(composers: dict, pages: dict, aliases: dict[str, str]) -> list[tuple[str, str, str]]:
    """Give a folded name (the browse page id of a composer our alias table does not know, "fリスト" for "F.リスト") the Apple page of the composer
    key a person says it is. ``composers`` and ``pages`` (key -> artist id / artist page) are filled in place; the problems come back as
    (alias, key, why) and that alias is NOT applied. Refused: a key that is not ours or has no Apple page, a name that is not a folded name or that
    works.py already knows (it is a key then), a name that already has another page, and a family name several composers share (バッハ, シュトラウス,
    ...) unless it states the generation (… II世): "J.シュトラウス" alone may be the father, the son or Josef."""
    problems = []
    for alias, key in sorted(aliases.items()):
        why = None
        if key not in _DISPLAY:
            why = "not a composer key"
        elif name_fold(alias) != alias or not alias:
            why = "not a folded name"
        elif alias in _DISPLAY or n(alias) in _ALIAS:
            why = "works.py already keys this name"
        elif any(f in alias for f in map(name_fold, _FAMILY_NAMES)) and not _GENERATION.search(alias):
            why = "a family name several composers share, and no generation is stated"
        elif key not in composers:
            why = "the key has no Apple page"
        elif alias in composers and composers[alias] != composers[key]:
            why = "the name already has another page"
        if why:
            problems.append((alias, key, why))
            continue
        composers[alias] = composers[key]
        if key in pages:
            pages[alias] = pages[key]
    return problems


def render_js(table: dict) -> str:
    body = json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ("// Generated by scripts/resolve_classical_links.py (ADR-0013). Apple Music Classical ids, reviewed by hand; edit through the script, not here.\n"
            "// Keyed by the browse pages' LOCAL ids (ADR-0014). composers: composer_key or folded name -> artist id; works: work_key or ~composer|workFold(title) -> work slug;\n"
            "// people: nameFold(name) -> artist id (conductors and soloists).\n"
            f"window.CR_CLASSICAL = {body};\n")
