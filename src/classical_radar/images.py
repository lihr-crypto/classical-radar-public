"""Freely licensed photos of performers and orchestras from Wikidata (P18) / Wikimedia Commons.

Why not the presenters' own posters and photos: they are copyrighted, KAJIMOTO's terms forbid reusing its images, and the handoff makes
"no reuse of posters / portraits without permission" a hard rule. Commons images carry a free licence; we keep the licence, author and
source page and show them next to every image.

Matching is deliberately strict (a wrong face is worse than no face, and namesakes must never be merged):
* the displayed name must equal a Wikidata label or alias (ja or en) after normalisation (honorifics such as "サー・" removed);
* a person must be human (Q5) with a music occupation; an orchestra must be an orchestra/ensemble;
* exactly one entity may satisfy this, otherwise nothing is stored;
* the image licence must be CC0 / public domain / CC BY / CC BY-SA.
Requests are slow (one every few seconds), identify the project in the User-Agent, and back off on HTTP 429; repeated 429 stops the run.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .works import n

UA = "ClassicalRadarPOC/0.1 (https://github.com/lihr-crypto/classical-radar-public; low-volume personal tool)"
WD = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
HUMAN = "Q5"
MUSIC_OCCUPATIONS = {
    "Q158852", "Q486748", "Q1259917", "Q13219637", "Q177220", "Q2865819", "Q639669", "Q36834", "Q1415090", "Q3455803", "Q2643890",
    "Q16145150", "Q1028181", "Q12800682", "Q855091", "Q1075651", "Q15981151", "Q6168364", "Q20669622", "Q3089940", "Q186360",
    "Q1327329", "Q2490358", "Q17125263", "Q13582652", "Q3922505", "Q4351403", "Q15855946", "Q12902372", "Q11569986", "Q19723482",
}
ORCHESTRA_TYPES = {"Q42998", "Q1060829", "Q2989412", "Q2085381", "Q215380", "Q5741069", "Q1371849", "Q3330723", "Q1546205", "Q4438121", "Q9212979"}
FREE = re.compile(r"^(cc0|public domain|pd\b|pd-|cc[ -]by(-sa)?([ -]\d(\.\d)?)?( \w+)?$)", re.I)
MUSIC_WORDS = re.compile(r"指揮者|ピアニスト|ヴァイオリニスト|バイオリニスト|チェリスト|ヴィオラ奏者|声楽家|歌手|ソプラノ|テノール|バリトン|メゾ|作曲家|音楽家|奏者|conductor|pianist|violinist|cellist|violist|soprano|tenor|baritone|mezzo|singer|composer|musician|flautist|clarinettist|horn player|harpist|organist", re.I)
ORCHESTRA_WORDS = re.compile(r"管弦楽団|交響楽団|フィルハーモニー|オーケストラ|楽団|アンサンブル|orchestra|philharmonic|ensemble|symphon", re.I)
HONORIFIC = re.compile(r"^(サー|デイム|Sir|Dame)\s*[・･]?\s*", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_image (
  name_key TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('matched','no_match','no_image','not_free')),
  wikidata_id TEXT, file_title TEXT, license TEXT, credit TEXT, license_url TEXT, page_url TEXT, local_file TEXT, fetched_at TEXT NOT NULL);
"""


class RateLimited(RuntimeError):
    pass


class Client:
    def __init__(self, interval: float = 3.0, transport=None, max_backoffs: int = 4, backoff: float = 20.0):
        self.http = httpx.Client(headers={"User-Agent": UA}, timeout=30, transport=transport, follow_redirects=True)
        self.interval, self.last, self.max_backoffs, self.backoff = interval, 0.0, max_backoffs, backoff

    def close(self):
        self.http.close()

    def get(self, url, **params):
        for attempt in range(self.max_backoffs + 1):
            time.sleep(max(0.0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            r = self.http.get(url, params=params or None)
            if r.status_code == 429:
                if attempt == self.max_backoffs:
                    raise RateLimited("Wikimedia keeps answering 429; stopping this run")
                time.sleep(min(300, float(r.headers.get("retry-after") or 0) or self.backoff * 2 ** attempt))
                continue
            r.raise_for_status()
            return r
        raise RateLimited("unreachable")


def name_key(name: str) -> str:
    return n(HONORIFIC.sub("", name or ""))


def _values(entity: dict, prop: str) -> list[str]:
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        out.append(v.get("id") if isinstance(v, dict) else v)
    return [x for x in out if x]


def _names(entity: dict) -> set[str]:
    names = set()
    for lang in ("ja", "en"):
        if lang in entity.get("labels", {}):
            names.add(name_key(entity["labels"][lang]["value"]))
        for a in entity.get("aliases", {}).get(lang, []):
            names.add(name_key(a["value"]))
    return names


def _desc(entity: dict) -> str:
    return " ".join(d.get("value", "") for d in entity.get("descriptions", {}).values())


def pick_entity(name: str, kind: str, entities: list[dict]) -> dict | None:
    """The single entity whose label/alias equals ``name`` and whose type fits ``kind`` ('person' | 'orchestra'), else None."""
    key = name_key(name)
    ok = []
    for e in entities:
        if key not in _names(e):
            continue
        if kind == "person" and HUMAN in _values(e, "P31") and (MUSIC_OCCUPATIONS & set(_values(e, "P106")) or MUSIC_WORDS.search(_desc(e))):
            ok.append(e)
        elif kind == "orchestra" and HUMAN not in _values(e, "P31") and (ORCHESTRA_TYPES & set(_values(e, "P31")) or ORCHESTRA_WORDS.search(_desc(e))):
            ok.append(e)
    return ok[0] if len(ok) == 1 else None


def _credit(meta: dict) -> str:
    raw = (meta.get("Artist") or {}).get("value") or (meta.get("Credit") or {}).get("value") or ""
    return re.sub(r"\s+", " ", BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))[:120]


def lookup(client: Client, name: str, kind: str, media_dir: Path, width: int = 240) -> dict:
    """One name -> a media_image row (status matched / no_match / no_image / not_free)."""
    base = {"name_key": name_key(name), "kind": kind, "fetched_at": datetime.now(timezone.utc).isoformat()}
    ids = []
    for lang in ("ja", "en"):
        res = client.get(WD, action="wbsearchentities", search=HONORIFIC.sub("", name), language=lang, uselang=lang, type="item", limit="7", format="json").json()
        ids += [x["id"] for x in res.get("search", []) if x["id"] not in ids]
        if ids:
            break
    if not ids:
        return {**base, "status": "no_match"}
    ents = client.get(WD, action="wbgetentities", ids="|".join(ids[:7]), props="labels|aliases|claims|descriptions", languages="ja|en", format="json").json().get("entities", {})
    e = pick_entity(name, kind, list(ents.values()))
    if e is None:
        return {**base, "status": "no_match"}
    images = _values(e, "P18")
    if not images:
        return {**base, "status": "no_image", "wikidata_id": e["id"]}
    title = "File:" + images[0]
    info = client.get(COMMONS, action="query", titles=title, prop="imageinfo", iiprop="url|extmetadata", iiurlwidth=str(width), format="json").json()
    page = next(iter(info.get("query", {}).get("pages", {}).values()), {})
    ii = (page.get("imageinfo") or [{}])[0]
    meta = ii.get("extmetadata", {})
    lic = (meta.get("LicenseShortName") or {}).get("value", "")
    if not FREE.match(lic.strip()):
        return {**base, "status": "not_free", "wikidata_id": e["id"], "file_title": title, "license": lic}
    img = client.get(ii["thumburl"]).content
    fname = hashlib.sha256(img).hexdigest()[:20] + ".jpg"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / fname).write_bytes(img)
    return {**base, "status": "matched", "wikidata_id": e["id"], "file_title": title, "license": lic, "credit": _credit(meta),
            "license_url": (meta.get("LicenseUrl") or {}).get("value"), "page_url": ii.get("descriptionurl"), "local_file": fname}


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def wanted_names(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple[str, str]]:
    """Performers and orchestras of official-confirmed concerts, most frequent first; orchestras from the orchestra table."""
    from .discover import orchestra_map
    from .orchestras import ORCHESTRAS
    counts: dict[tuple[str, str], int] = {}
    for r in conn.execute("""SELECT a.name_display, a.role FROM concert_artist a JOIN concert c ON c.id=a.concert_id
                             WHERE c.verification_status='official_confirmed' AND a.role IN ('conductor','recital_headliner','concerto_soloist')"""):
        counts[(r[0], "person")] = counts.get((r[0], "person"), 0) + 1
    confirmed = {r[0] for r in conn.execute("SELECT id FROM concert WHERE verification_status='official_confirmed'")}
    for cid, keys in orchestra_map(conn).items():
        if cid in confirmed:
            for k in keys:
                if ORCHESTRAS[k]["origin"] in ("seven", "overseas"):
                    counts[(ORCHESTRAS[k]["display"], "orchestra")] = counts.get((ORCHESTRAS[k]["display"], "orchestra"), 0) + 3
    names = sorted(counts, key=lambda x: -counts[x])
    return names[:limit] if limit else names


def run(conn: sqlite3.Connection, media_dir: Path, *, limit: int | None = None, client: Client | None = None, log=print) -> dict:
    init(conn)
    done = {r[0] for r in conn.execute("SELECT name_key FROM media_image")}
    client = client or Client()
    stats: dict[str, int] = {}
    try:
        for name, kind in wanted_names(conn, limit):
            if name_key(name) in done:
                continue
            try:
                row = lookup(client, name, kind, media_dir)
            except RateLimited as exc:
                log(f"stopped: {exc}")
                stats["stopped_rate_limited"] = 1
                break
            except httpx.HTTPError as exc:
                log(f"{name}: {type(exc).__name__}")
                continue
            cols = ["name_key", "kind", "status", "wikidata_id", "file_title", "license", "credit", "license_url", "page_url", "local_file", "fetched_at"]
            conn.execute(f"INSERT OR REPLACE INTO media_image ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row.get(c) for c in cols])
            conn.commit()
            done.add(row["name_key"])
            stats[row["status"]] = stats.get(row["status"], 0) + 1
            log(f"{row['status']:9} {name}")
    finally:
        client.close()
    return stats


def image_for(conn: sqlite3.Connection, name: str) -> dict | None:
    try:
        r = conn.execute("SELECT * FROM media_image WHERE name_key=? AND status='matched'", (name_key(name),)).fetchone()
    except sqlite3.OperationalError:  # table not created yet: no images
        return None
    if r is None:
        return None
    return {"file": r["local_file"], "license": r["license"], "credit": r["credit"], "page_url": r["page_url"], "license_url": r["license_url"]}
