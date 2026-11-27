"""Cross-source duplicate review (ADR-0003). Hints and reversible human decisions only: nothing is merged, deleted or auto-decided.

Two sources often list the same real concert (Japan Arts and 神奈川艺术协会, 神奈川艺术协会 and 东京交响乐团 ...). We cannot prove
sameness, so ``hints_for`` only *points* at a candidate (same upcoming day + compatible venue, different source) and says why.
The reviewer then decides, per pair:

* ``duplicate_of``: "this needs_review concert is the same show as that one": it leaves the review queue and cannot be confirmed
  (so discover will not show two cards), but its row and evidence stay and the decision is undoable;
* ``different``: "not the same show": the hint is not shown again.

Structure is kept one level deep (a hidden concert points at a visible keeper; a keeper is never itself hidden), so chains and
cycles cannot hide every card. A ``duplicate_of`` decision only counts while the match that justified it still holds
(``effective_duplicate_of``); a re-synced date or venue, or a keeper that is cancelled or past, brings the concert back to the queue.

ADR-0006 adds the already-confirmed case: a confirmed concert may be marked ``duplicate_of`` another confirmed one. Nothing is merged in
the store; the read side (discover / calendar) then lists the hidden card's performances under the keeper, performance by performance
(``merged_map`` + ``venue_compatible``), and both cards keep their own detail page, ticket phases, pickups and reminders.
Decisions are also kept in a reviewed file keyed by ``source|url`` (``merge_file`` / ``apply_file``), because concert ids do not
survive a rebuilt database.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .parsers import JST, _venue_key
from .sources import SOURCES

DECISIONS = ("duplicate_of", "different")
MIN_PREFIX = 3  # a venue label this short may not stand in as the *prefix* of a longer one (exact matches of any length still count)
_UPCOMING = "p.status NOT IN ('cancelled','completed') AND p.date_precision IN ('exact_time','date_only') AND p.local_date IS NOT NULL AND p.local_date>=?"


def _today(now: datetime) -> str:
    return now.astimezone(JST).date().isoformat()


def _source(identity_key: str) -> str:
    return identity_key.split("|", 1)[0]


def venue_compatible(a: str | None, b: str | None) -> bool:
    return _venue_reason(a or "", b or "") is not None


def _venue_reason(a: str, b: str) -> str | None:
    ka, kb = _venue_key(a), _venue_key(b)
    if not ka or not kb:
        return None
    if ka == kb:
        return "venue_exact"
    short, long_ = sorted((ka, kb), key=len)
    return "venue_prefix" if len(short) >= MIN_PREFIX and long_.startswith(short) else None


_STRIP = re.compile(r"[\s　\[\]【】()（）「」『』・･\-–—~〜/／:：!！?？,，、。.]+")


def _norm(text: str) -> str:
    return _STRIP.sub("", text or "").lower()


def _perfs(conn: sqlite3.Connection, today: str, concert_id: str | None = None) -> dict[str, list[tuple[str, str]]]:
    """Upcoming day-level performances as {concert_id: [(local_date, venue_name)]} (all concerts, or just one)."""
    sql = f"SELECT p.concert_id, p.local_date, p.venue_name FROM performance p WHERE {_UPCOMING}" + (" AND p.concert_id=?" if concert_id else "")
    out: dict[str, list[tuple[str, str]]] = {}
    for r in conn.execute(sql, (today, concert_id) if concert_id else (today,)):
        out.setdefault(r["concert_id"], []).append((r["local_date"], r["venue_name"] or ""))
    return out


def _best_venue_reason(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> str | None:
    best = None
    for da, va in a:
        for db_, vb in b:
            if da == db_:
                r = _venue_reason(va, vb)
                if r == "venue_exact":
                    return r
                best = best or r
    return best


def _artists(conn: sqlite3.Connection, concert_id: str) -> set[str]:
    return {n for n in (_norm(r[0]) for r in conn.execute("SELECT name_display FROM concert_artist WHERE concert_id=?", (concert_id,))) if len(n) >= 2}


def _detail(conn: sqlite3.Connection, a: sqlite3.Row, b: sqlite3.Row, venue: str) -> dict:
    reasons = ["same_day", venue]
    shared = sorted(_artists(conn, a["id"]) & _artists(conn, b["id"]))
    if shared:
        reasons.append("shared_artists")
    ta, tb = sorted((_norm(a["title_ja"]), _norm(b["title_ja"])), key=len)
    if len(ta) >= 4 and ta in tb:
        reasons.append("title_contains")
    return {"concert_id": b["id"], "source_id": _source(b["identity_key"]), "title_ja": b["title_ja"], "source_url": b["identity_key"].split("|", 1)[1],
            "verification_status": b["verification_status"], "reasons": reasons, "shared_artists": shared,
            "strength": "strong" if ("shared_artists" in reasons or "title_contains" in reasons) else "weak"}


def _match(conn: sqlite3.Connection, a_id: str, b_id: str, today: str) -> dict | None:
    """Hint-shaped dict describing why b looks like a (seen from a), or None. Different sources only."""
    a = conn.execute("SELECT * FROM concert WHERE id=?", (a_id,)).fetchone()
    b = conn.execute("SELECT * FROM concert WHERE id=?", (b_id,)).fetchone()
    if a is None or b is None or _source(a["identity_key"]) == _source(b["identity_key"]):
        return None
    venue = _best_venue_reason(_perfs(conn, today, a_id).get(a_id, []), _perfs(conn, today, b_id).get(b_id, []))
    return _detail(conn, a, b, venue) if venue else None


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def effective_duplicate_of(conn: sqlite3.Connection, concert_id: str, today: str) -> dict | None:
    """The keeper this concert was marked a duplicate of, if that decision still stands; a stale decision (match gone) counts as none."""
    row = conn.execute("SELECT other_concert_id FROM duplicate_review WHERE concert_id=? AND decision='duplicate_of'", (concert_id,)).fetchone()
    return _match(conn, concert_id, row["other_concert_id"], today) if row else None


def hints_for(conn: sqlite3.Connection, concert_ids: list[str], today: str) -> dict[str, list[dict]]:
    """Possible duplicates of each given concert, strongest first. Pairs the reviewer has already decided are left out."""
    perfs = _perfs(conn, today)
    by_date: dict[str, set[str]] = {}
    for cid, items in perfs.items():
        for d, _ in items:
            by_date.setdefault(d, set()).add(cid)
    decided = {(r["concert_id"], r["other_concert_id"], r["decision"]) for r in conn.execute("SELECT concert_id, other_concert_id, decision FROM duplicate_review")}
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM concert")}
    # concerts the reviewer already hid behind a keeper (decision still stands) are not offered as a target: choosing them would just be refused
    hidden = {c for c, k, d in decided if d == "duplicate_of" and perfs.get(c) and perfs.get(k) and _best_venue_reason(perfs[c], perfs[k])}
    out: dict[str, list[dict]] = {}
    for cid in concert_ids:
        a = rows.get(cid)
        if a is None:
            continue
        candidates = {o for d, _ in perfs.get(cid, []) for o in by_date.get(d, ()) if o != cid and o not in hidden}
        found = []
        for oid in candidates:
            b = rows[oid]
            if _source(b["identity_key"]) == _source(a["identity_key"]):
                continue
            if (*_pair(cid, oid), "different") in decided or (cid, oid, "duplicate_of") in decided or (oid, cid, "duplicate_of") in decided:
                continue
            venue = _best_venue_reason(perfs[cid], perfs[oid])
            if venue:
                found.append(_detail(conn, a, b, venue))
        out[cid] = sorted(found, key=lambda h: (h["strength"] != "strong", h["verification_status"] != "official_confirmed", h["source_id"], h["concert_id"]))
    return out


def _purge_stale(conn: sqlite3.Connection, ids: tuple[str, ...], today: str) -> None:
    for r in conn.execute("SELECT concert_id, other_concert_id FROM duplicate_review WHERE decision='duplicate_of' AND (concert_id IN ({0}) OR other_concert_id IN ({0}))".format(",".join("?" * len(ids))), ids + ids).fetchall():
        if _match(conn, r["concert_id"], r["other_concert_id"], today) is None:
            conn.execute("DELETE FROM duplicate_review WHERE concert_id=? AND other_concert_id=?", (r["concert_id"], r["other_concert_id"]))


def decide(conn: sqlite3.Connection, concert_id: str, other_id: str, decision: str, now: datetime, *, decided_at: str | None = None) -> dict:
    """Record a reviewer decision about a hinted pair; replaces any earlier decision for the pair. Does not touch the concerts themselves."""
    if decision not in DECISIONS or concert_id == other_id:
        raise ValueError("decision must be duplicate_of|different for two different concerts")
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM concert WHERE id IN (?,?)", (concert_id, other_id))}
    if len(rows) != 2:
        raise LookupError("unknown concert")
    today = _today(now)
    _purge_stale(conn, (concert_id, other_id), today)
    if _match(conn, concert_id, other_id, today) is None:
        raise ValueError("not a possible duplicate: needs two different sources with an upcoming performance on the same day at a compatible venue")
    if decision == "duplicate_of":
        if rows[concert_id]["verification_status"] != "needs_review":  # an already confirmed card: listed under the keeper, never deleted (ADR-0006)
            if rows[other_id]["verification_status"] != "official_confirmed":
                raise ValueError("a confirmed card can only be merged into another confirmed card")
            if not _covered(_perfs(conn, today, concert_id).get(concert_id, []), _perfs(conn, today, other_id).get(other_id, [])):
                raise ValueError("the hidden card has a performance the main card lacks: choose the other card as the main one")
        if conn.execute("SELECT 1 FROM duplicate_review WHERE decision='duplicate_of' AND (concert_id=? OR other_concert_id=?)", (other_id, concert_id)).fetchone():
            raise ValueError("the other concert is itself hidden as a duplicate, or this one is already the keeper of another: undo that decision first")
        conn.execute("DELETE FROM duplicate_review WHERE decision='duplicate_of' AND concert_id=?", (concert_id,))  # choosing a different keeper replaces the old choice
        first, second = concert_id, other_id
    else:
        first, second = _pair(concert_id, other_id)
    conn.execute("DELETE FROM duplicate_review WHERE (concert_id=? AND other_concert_id=?) OR (concert_id=? AND other_concert_id=?)", (concert_id, other_id, other_id, concert_id))
    conn.execute("INSERT INTO duplicate_review (concert_id, other_concert_id, decision, decided_at) VALUES (?,?,?,?)", (first, second, decision, decided_at or now.astimezone(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    return {"concert_id": concert_id, "other_concert_id": other_id, "decision": decision}


def undo(conn: sqlite3.Connection, concert_id: str, other_id: str) -> None:
    cur = conn.execute("DELETE FROM duplicate_review WHERE (concert_id=? AND other_concert_id=?) OR (concert_id=? AND other_concert_id=?)", (concert_id, other_id, other_id, concert_id))
    conn.commit()
    if cur.rowcount == 0:
        raise LookupError("no such decision")


def marked_duplicates(conn: sqlite3.Connection, today: str, source_id: str | None = None) -> list[dict]:
    """Concerts the reviewer hid as duplicates and whose decision still stands: needs_review ones (out of the queue) and, since
    ADR-0006, confirmed ones listed under a confirmed keeper."""
    out = []
    merged = merged_map(conn, today)
    for r in conn.execute("""SELECT d.concert_id, d.other_concert_id FROM duplicate_review d JOIN concert c ON c.id=d.concert_id
                             WHERE d.decision='duplicate_of' ORDER BY c.identity_key""").fetchall():
        keeper = _match(conn, r["concert_id"], r["other_concert_id"], today)
        c = conn.execute("SELECT * FROM concert WHERE id=?", (r["concert_id"],)).fetchone()
        if keeper is None or (source_id is not None and _source(c["identity_key"]) != source_id):
            continue
        out.append({"concert_id": c["id"], "source_id": _source(c["identity_key"]), "source_url": c["identity_key"].split("|", 1)[1], "title_ja": c["title_ja"],
                    "verification_status": c["verification_status"],
                    # a confirmed pair whose main card no longer has every date of this one is not merged any more, but stays listed so it can be undone
                    "active": c["verification_status"] == "needs_review" or r["concert_id"] in merged,
                    "duplicate_of": {k: keeper[k] for k in ("concert_id", "source_id", "source_url", "title_ja", "verification_status")}})
    return out


# ---- ADR-0006: already-confirmed pairs ----------------------------------------------------------------------------------------

def _covered(hidden: list[tuple[str, str]], keeper: list[tuple[str, str]]) -> bool:
    """Every upcoming performance of the hidden card is also on the keeper (same day, compatible venue): hiding it loses no date."""
    return bool(hidden) and all(any(d == dk and _venue_reason(v, vk) for dk, vk in keeper) for d, v in hidden)


def _card(c: sqlite3.Row) -> dict:
    return {"concert_id": c["id"], "source_id": _source(c["identity_key"]), "source_url": c["identity_key"].split("|", 1)[1], "title_ja": c["title_ja"]}


def source_card(conn: sqlite3.Connection, concert_id: str) -> dict | None:
    c = conn.execute("SELECT * FROM concert WHERE id=?", (concert_id,)).fetchone()
    return _card(c) if c else None


def merged_map(conn: sqlite3.Connection, today: str) -> dict[str, str]:
    """{hidden concert id: keeper concert id} for the decisions that merge two CONFIRMED cards and still stand."""
    out = {}
    for r in conn.execute("""SELECT d.concert_id, d.other_concert_id FROM duplicate_review d JOIN concert a ON a.id=d.concert_id JOIN concert b ON b.id=d.other_concert_id
                             WHERE d.decision='duplicate_of' AND a.verification_status='official_confirmed' AND b.verification_status='official_confirmed'""").fetchall():
        h, k = r["concert_id"], r["other_concert_id"]
        if _match(conn, h, k, today) and _covered(_perfs(conn, today, h).get(h, []), _perfs(conn, today, k).get(k, [])):
            out[h] = k
    return out


def suggested_keeper(a_source: str, b_source: str) -> str | None:
    """The source whose card should lead (lower ``Source.card_rank``), or None on a tie / unknown source: then the reviewer must choose."""
    ra, rb = (SOURCES[s].card_rank if s in SOURCES else None for s in (a_source, b_source))
    if ra is None or rb is None or ra == rb:
        return None
    return a_source if ra < rb else b_source


def confirmed_pairs(conn: sqlite3.Connection, today: str, source_id: str | None = None) -> list[dict]:
    """Undecided possible duplicates among CONFIRMED concerts (both cards are on discover today), each pair once, strongest first.
    ``can_hide`` says which side may be the hidden one (all its upcoming performances are on the other card)."""
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM concert WHERE verification_status='official_confirmed'")}
    merged = merged_map(conn, today)
    hidden, keepers = set(merged), set(merged.values())
    hidden |= {r[0] for r in conn.execute("SELECT concert_id FROM duplicate_review WHERE decision='duplicate_of'")}  # decided, even if not in effect: shown under "marked", not offered again
    perfs = _perfs(conn, today)
    out, seen = [], set()
    for cid, hints in hints_for(conn, [i for i in rows if i not in hidden and perfs.get(i)], today).items():
        for h in hints:
            oid = h["concert_id"]
            if oid not in rows or oid in hidden or _pair(cid, oid) in seen:
                continue
            seen.add(_pair(cid, oid))
            a, b = (rows[i] for i in sorted((cid, oid), key=lambda i: rows[i]["identity_key"]))
            sa, sb = _source(a["identity_key"]), _source(b["identity_key"])
            if source_id is not None and source_id not in (sa, sb):
                continue
            keep = suggested_keeper(sa, sb)
            # a card that already leads another may not be hidden itself (one level deep), so that choice is not offered
            can = {a["id"]: a["id"] not in keepers and _covered(perfs[a["id"]], perfs[b["id"]]), b["id"]: b["id"] not in keepers and _covered(perfs[b["id"]], perfs[a["id"]])}
            suggested = (a["id"] if keep == sa else b["id"]) if keep else None
            if suggested and not can[b["id"] if suggested == a["id"] else a["id"]]:
                suggested = None  # the card that should lead lacks a date the other has: no suggestion, the reviewer decides
            out.append({"a": _card(a), "b": _card(b), "local_date": min(d for d, _ in perfs[a["id"]] if any(d == x for x, _ in perfs[b["id"]])),
                        "reasons": h["reasons"], "shared_artists": h["shared_artists"], "strength": h["strength"], "suggested_keeper_id": suggested, "can_hide": can})
    return sorted(out, key=lambda p: (p["strength"] != "strong", p["local_date"], p["a"]["source_url"], p["b"]["source_url"]))


# ---- decisions as a reviewed file (identity keys, not ids) ---------------------------------------------------------------------

def _load_file(path: Path) -> list[dict]:
    if not Path(path).is_file():
        return []
    data = json.loads(Path(path).read_text(encoding="utf8"))
    if not isinstance(data, list) or any(not isinstance(e, dict) or e.get("decision") not in DECISIONS or not all(isinstance(e.get(k), str) and "|" in e[k] for k in ("a", "b")) for e in data):
        raise ValueError(f"{path}: expected a list of {{a, b, decision, decided_at}} with a/b as source|url")
    return data


def _order(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e.get("decided_at") or "", e["a"], e["b"]))


def merge_file(conn: sqlite3.Connection, path: Path, *, prune: bool = False) -> dict:
    """Write the database's decisions into the file WITHOUT shrinking it: a database decision replaces the file entry for the same pair
    (and, for duplicate_of, any other entry hiding the same card); every other entry stays. Entries whose two concerts are both in the
    database but undecided there (an undo, or a database the file was never applied to) are reported, and dropped only with ``prune``."""
    path = Path(path)
    kept = _load_file(path)
    idents = {r["id"]: r["identity_key"] for r in conn.execute("SELECT id, identity_key FROM concert")}
    known = set(idents.values())
    ours = [{"a": idents[r["concert_id"]], "b": idents[r["other_concert_id"]], "decision": r["decision"], "decided_at": r["decided_at"]}
            for r in conn.execute("SELECT * FROM duplicate_review ORDER BY decided_at, concert_id, other_concert_id")]
    for e in ours:  # "different" has no direction: write it in identity order, not in the order of this database's random ids
        if e["decision"] == "different":
            e["a"], e["b"] = sorted((e["a"], e["b"]))
    for e in ours:
        kept = [k for k in kept if {k["a"], k["b"]} != {e["a"], e["b"]} and not (e["decision"] == "duplicate_of" and k["decision"] == "duplicate_of" and k["a"] == e["a"])]
    undecided = [k for k in kept if k["a"] in known and k["b"] in known]
    if prune:
        kept = [k for k in kept if k not in undecided]
    entries = _order(kept + ours)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[\n" + ",\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries) + ("\n" if entries else "") + "]\n", encoding="utf8")
    return {"file": str(path), "entries": len(entries), "from_database": len(ours), "pruned": len(undecided) if prune else 0,
            "in_file_but_undecided_in_database": [] if prune else [{"a": k["a"], "b": k["b"], "decision": k["decision"]} for k in undecided]}


def apply_file(conn: sqlite3.Connection, path: Path, now: datetime) -> dict:
    """Replay the file into this database through ``decide`` (so every guard runs), oldest decision first. Entries that name a concert
    this database does not have, or that no longer pass the guards, are skipped and reported - never forced."""
    idents = {r["identity_key"]: r["id"] for r in conn.execute("SELECT id, identity_key FROM concert")}
    applied, skipped = 0, []
    for e in _order(_load_file(Path(path))):
        a, b = idents.get(e["a"]), idents.get(e["b"])
        if a is None or b is None:
            skipped.append({"a": e["a"], "b": e["b"], "reason": "unknown concert"})
            continue
        try:
            decide(conn, a, b, e["decision"], now, decided_at=e.get("decided_at"))
            applied += 1
        except ValueError as err:
            conn.rollback()
            skipped.append({"a": e["a"], "b": e["b"], "reason": str(err)})
    return {"file": str(path), "applied": applied, "skipped": skipped}


# ---- the exported snapshot (static site / demo): plain dicts, no database ------------------------------------------------------

def _export_perfs(c: dict, today: str) -> list[tuple[str, str]]:
    return [(p["local_date"], p["venue_name"] or "") for p in c["performances"]
            if p["status"] not in ("cancelled", "completed") and p["date_precision"] in ("exact_time", "date_only") and p["local_date"] and p["local_date"] >= today]


def mark_export(concerts: list[dict], merged: dict[str, str]) -> None:
    """Write the merge into exported concerts (replacing any earlier marks): the hidden card gets ``duplicate_of`` and each of its
    performances ``same_as`` = the keeper performances (same day, compatible venue) that stand in for it. The page has no venue logic."""
    by_id = {c["id"]: c for c in concerts}
    for c in concerts:
        c.pop("duplicate_of", None)
        for p in c["performances"]:
            p.pop("same_as", None)
    for hidden, keeper in merged.items():
        if hidden in by_id and keeper in by_id:
            by_id[hidden]["duplicate_of"] = keeper
            for p in by_id[hidden]["performances"]:
                p["same_as"] = [k["id"] for k in by_id[keeper]["performances"] if k["local_date"] == p["local_date"] and venue_compatible(k["venue_name"], p["venue_name"])]


def merged_from_file(concerts: list[dict], path: Path, today: str) -> tuple[dict[str, str], list[dict]]:
    """({hidden id: keeper id}, skipped) from the decisions file for an exported snapshot, with the same guards as ``decide`` for two
    confirmed cards: both present, different sources, every upcoming date of the hidden card on the keeper, one level deep."""
    ident = {f'{c["source_id"]}|{c["source_url"]}': c for c in concerts}
    out: dict[str, str] = {}
    skipped = []
    latest: dict[frozenset, dict] = {}
    for e in _order(_load_file(Path(path))):  # the latest entry for a pair wins, as when the file is replayed into a database
        latest[frozenset((e["a"], e["b"]))] = e
    for e in _order(list(latest.values())):
        if e["decision"] != "duplicate_of":
            continue
        h, k = ident.get(e["a"]), ident.get(e["b"])
        if h is None or k is None:
            reason = "unknown concert"
        elif h["source_id"] == k["source_id"]:
            reason = "same source"
        elif not _covered(_export_perfs(h, today), _export_perfs(k, today)):
            reason = "the hidden card has no upcoming performance, or one the main card lacks"
        elif k["id"] in out or h["id"] in out.values():
            reason = "the main card is itself hidden, or the hidden card is the main card of another"
        else:
            out[h["id"]] = k["id"]  # a later decision for the same hidden card replaces the earlier one
            continue
        skipped.append({"a": e["a"], "b": e["b"], "reason": reason})
    return out, skipped
