"""HTTP layer for 03_CONTRACTS 3.4 (single-user, bearer-token, local). FastAPI is used only for routing and the OpenAPI document.

Every route requires ``Authorization: Bearer <token>``; a missing/empty configured token is a startup error (fail closed), because
personal state and unverified leads must never be public. Extensions beyond 3.4 (documented in docs/adr): confirm/reject routes for
POST /import-url, because that route must stop at a human decision.
"""
from __future__ import annotations

import hmac
import mimetypes
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import db, duplicates, leads as leads_mod, personal
from .contract import ArtistRole, Category, Priority, UserPerformanceStatus
from .discover import calendar_range, concert_detail, coverage, discover, facets
from .ingest import confirm_stored, review_candidates
from datetime import date as _date
from .import_url import ImportRejected, confirm_import, reject_import, stage_import
from .network import Reader
from .parsers import JST

mimetypes.add_type("application/manifest+json", ".webmanifest")  # the web app manifest under /ui/icons/ (not in every Python's table)

USER_ID = "me"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PickupBody(_Body):
    priority: Priority = "normal"
    notes: str | None = None


class StateBody(_Body):
    status: UserPerformanceStatus
    notes: str | None = None


class ReminderBody(_Body):
    milestone: Literal["sale_start", "sale_end"]
    offset_minutes: int = Field(ge=0, le=43200)
    enabled: bool


class ImportBody(_Body):
    url: str


class ConfirmBody(_Body):
    category: Category
    prefecture_overrides: dict[str, str] = {}
    note: str | None = None


class DuplicateBody(_Body):
    concert_id: str
    other_concert_id: str
    decision: Literal["duplicate_of", "different"]


class ReviewConfirmBody(_Body):
    concert_ids: list[str] = Field(min_length=1, max_length=200)
    category_overrides: dict[str, Category] = {}
    prefecture_overrides: dict[str, str] = {}


class Filters(BaseModel):
    model_config = ConfigDict(extra="allow")  # composer/work/conductor/performer/venue appear only when used
    category: Category | Literal["all"]
    months: Literal[12, 24]
    region_mode: Literal["kanto_first", "nationwide"]
    sort: Literal["announcement_desc"]
    view: Literal["concerts"]
    page: int
    limit: int


class DiscoverPerformance(BaseModel):
    performance_id: str
    local_date: str
    starts_at: str | None
    date_precision: Literal["exact_time", "date_only", "month_only", "unknown"]
    prefecture_code: str | None
    venue_name: str
    last_seen_at: str | None


class DiscoverPiece(BaseModel):
    """One programme row as the browse pages need it (ADR-0010): the composer and the piece as written, plus the reviewed keys when the alias table knows them."""
    composer: str = ""
    composer_key: str | None = None
    work: str = ""
    work_key: str | None = None


class DiscoverItem(BaseModel):
    concert_id: str
    category: Category
    title_ja: str
    organization_id: str | None = None  # the source/organiser the concert came from (same value as concert.organization_id in the detail); null = unknown
    announcement_sort_date: str
    announcement_basis: Literal["official", "first_verified_fallback"]
    announcement_label: str
    region_group: Literal["kanto", "rest_of_japan"] | None
    performance_ids: list[str]
    performances: list[DiscoverPerformance]
    ticket_status: Literal["not_announced", "announced", "open", "closed", "unknown"]
    source_url: str
    last_verified_at: str
    user_pickup: bool
    orchestras: list[dict[str, str]] = []
    image: CardImage | None = None
    composers: list[str] = []
    conductors: list[str] = []
    soloists: list[str] = []
    pieces: list[DiscoverPiece] = []  # ADR-0010: every programme row in order (composers above is the short, capped list for cards)
    other_sources: list[dict[str, str]] = []  # ADR-0006: cards from other sources that a reviewer merged under this one {concert_id, source_id, source_url, title_ja}


class DiscoverResponse(BaseModel):
    filters: Filters
    as_of: str
    window: dict[str, str]
    total: int
    groups: list[dict[str, str]]
    items: list[DiscoverItem]
    coverage_notice: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CardImage(BaseModel):
    src: str
    subject: str
    license: str | None = None
    credit: str | None = None
    page_url: str | None = None
    license_url: str | None = None
    file: str | None = None


def create_app(db_path: str, token: str, *, raw_dir: Path | None = None, media_dir: Path | None = None, clock: Callable[[], datetime] = _now,
               reader_factory: Callable[[Path], Reader] | None = None, resolver=socket.getaddrinfo) -> FastAPI:
    if not token or len(token) < 16:
        raise ValueError("a bearer token of at least 16 characters is required; the API refuses to start without one")
    raw_dir = raw_dir or Path("data/raw")
    reader_factory = reader_factory or (lambda path: Reader(path))
    app = FastAPI(title="Classical Radar API", version="1.5-p1", docs_url=None, redoc_url=None)
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    # create the schema once at startup so a fresh database file is usable
    boot = db.connect(db_path)
    db.init(boot)
    boot.close()

    def auth(authorization: str | None = Header(default=None)) -> None:
        supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    def conn_dep():
        conn = db.connect(db_path, shared_thread=True)
        try:
            yield conn
        finally:
            conn.close()

    P = "/api/v1"
    def _guard(fn):
        try:
            return fn()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, ImportRejected) as exc:
            raise HTTPException(422, str(exc)) from exc

    guard = [Depends(auth)]

    @app.get(f"{P}/discover", response_model=DiscoverResponse, dependencies=guard)
    def get_discover(category: Category | Literal["all"] = "all", months: int = Query(12, json_schema_extra={"enum": [12, 24]}), region_mode: Literal["kanto_first", "nationwide"] = "kanto_first",
                     sort: Literal["announcement_desc"] = "announcement_desc", page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
                     orchestra: list[str] = Query([], max_length=10), composer: list[str] = Query([], max_length=10), work: list[str] = Query([], max_length=10),
                     conductor: list[str] = Query([], max_length=10), performer: list[str] = Query([], max_length=10), venue: list[str] = Query([], max_length=10), conn=Depends(conn_dep)):
        flt = {"orchestra": orchestra, "composer": composer, "work": work, "conductor": conductor, "performer": performer, "venue": venue}
        return _guard(lambda: discover(conn, as_of=clock(), category=category, months=months, region_mode=region_mode, sort=sort, page=page, limit=limit, user_id=USER_ID, filters=flt))

    @app.get(f"{P}/discover/facets", dependencies=guard)
    def get_facets(category: Category | Literal["all"] = "all", months: int = Query(12, json_schema_extra={"enum": [12, 24]}),
                   orchestra: list[str] = Query([], max_length=10), composer: list[str] = Query([], max_length=10), work: list[str] = Query([], max_length=10),
                   conductor: list[str] = Query([], max_length=10), performer: list[str] = Query([], max_length=10), venue: list[str] = Query([], max_length=10), conn=Depends(conn_dep)):
        flt = {"orchestra": orchestra, "composer": composer, "work": work, "conductor": conductor, "performer": performer, "venue": venue}
        return _guard(lambda: facets(conn, as_of=clock(), category=category, months=months, filters=flt))

    @app.get(f"{P}/discover/announcements", dependencies=guard)
    def get_announcements(conn=Depends(conn_dep)):
        rows = conn.execute("""SELECT a.id, a.organizer_or_artist_name, a.declared_range, a.linked_concert_id, d.url AS official_url, d.last_verified_at
                               FROM tour_announcement a JOIN source_document d ON d.id=a.official_source_document_id ORDER BY d.last_verified_at DESC""").fetchall()
        return {"items": [dict(r) for r in rows], "notice": "官宣但日期/场馆未定；不是公演，不会生成场次或提醒。"}

    @app.get(f"{P}/discover/leads", dependencies=guard)
    def get_leads(conn=Depends(conn_dep)):
        rows = conn.execute("SELECT id, source_url, text_summary, observed_at, review_status FROM unverified_lead ORDER BY observed_at DESC").fetchall()
        return {"items": [dict(r) for r in rows], "trust": "unverified", "notice": "待核实（非官方确认）：不进入正式查询，不能开启售票提醒。"}

    @app.get(f"{P}/discover/coverage", dependencies=guard)
    def get_coverage(conn=Depends(conn_dep)):
        return coverage(conn)

    @app.get(f"{P}/concerts/{{concert_id}}", dependencies=guard)
    def get_concert(concert_id: str, conn=Depends(conn_dep)):
        detail = concert_detail(conn, concert_id, USER_ID, clock())
        if detail is None:
            raise HTTPException(404, "concert not found or not official_confirmed")
        return detail

    @app.put(f"{P}/me/pickups/{{concert_id}}", dependencies=guard)
    def put_pickup(concert_id: str, body: PickupBody, conn=Depends(conn_dep)):
        _guard(lambda: personal.put_pickup(conn, USER_ID, concert_id, body.priority, body.notes, clock()))
        return {"user_id": USER_ID, "concert_id": concert_id, "priority": body.priority, "notes": body.notes}

    @app.delete(f"{P}/me/pickups/{{concert_id}}", status_code=204, dependencies=guard)
    def delete_pickup(concert_id: str, conn=Depends(conn_dep)):
        if not personal.delete_pickup(conn, USER_ID, concert_id):
            raise HTTPException(404, "no such pickup")

    @app.put(f"{P}/me/plans/{{concert_id}}", dependencies=guard)
    def put_plan(concert_id: str, conn=Depends(conn_dep)):
        _guard(lambda: personal.put_plan(conn, USER_ID, concert_id, clock()))
        return {"user_id": USER_ID, "concert_id": concert_id}

    @app.delete(f"{P}/me/plans/{{concert_id}}", status_code=204, dependencies=guard)
    def delete_plan(concert_id: str, conn=Depends(conn_dep)):
        if not personal.delete_plan(conn, USER_ID, concert_id):
            raise HTTPException(404, "no such plan")

    @app.put(f"{P}/me/performances/{{performance_id}}/state", dependencies=guard)
    def put_state(performance_id: str, body: StateBody, conn=Depends(conn_dep)):
        _guard(lambda: personal.put_performance_state(conn, USER_ID, performance_id, body.status, body.notes, clock()))
        return {"user_id": USER_ID, "performance_id": performance_id, "status": body.status, "notes": body.notes}

    @app.put(f"{P}/me/reminders/{{ticket_phase_id}}", dependencies=guard)
    def put_reminder(ticket_phase_id: str, body: ReminderBody, conn=Depends(conn_dep)):
        return _guard(lambda: personal.put_reminder(conn, USER_ID, ticket_phase_id, body.milestone, body.offset_minutes, body.enabled, clock()))

    @app.get(f"{P}/me/pickups", dependencies=guard)
    def list_pickups(conn=Depends(conn_dep)):
        return {"items": personal.list_pickups(conn, USER_ID)}

    @app.get(f"{P}/me/plans", dependencies=guard)
    def list_plans(conn=Depends(conn_dep)):
        return {"items": personal.list_plans(conn, USER_ID)}

    @app.get(f"{P}/leads", dependencies=guard)
    def get_leads(conn=Depends(conn_dep)):
        """Second-hand tour leads (ADR-0007): never official concerts, never in /discover. Leads an official concert already covers are flagged."""
        return leads_mod.page_for_db(conn, clock().astimezone(JST).date().isoformat())

    @app.get(f"{P}/leads/{{lead_id}}", dependencies=guard)
    def get_lead(lead_id: str, conn=Depends(conn_dep)):
        found = next((x for x in leads_mod.page_for_db(conn, clock().astimezone(JST).date().isoformat())["items"] if x["lead_id"] == lead_id), None)
        if found is None:
            raise HTTPException(404, "no such lead")
        return found

    @app.get(f"{P}/calendar", dependencies=guard)
    def get_calendar(start: _date = Query(alias="from"), end: _date = Query(alias="to"), conn=Depends(conn_dep)):
        return _guard(lambda: calendar_range(conn, start, end, clock()))

    @app.get(f"{P}/review/candidates", dependencies=guard)
    def get_review(source_id: str | None = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), conn=Depends(conn_dep)):
        return review_candidates(conn, clock(), source_id=source_id, page=page, limit=limit)

    @app.put(f"{P}/review/duplicates", dependencies=guard)
    def put_duplicate(body: DuplicateBody, conn=Depends(conn_dep)):
        return _guard(lambda: duplicates.decide(conn, body.concert_id, body.other_concert_id, body.decision, clock()))

    @app.delete(f"{P}/review/duplicates/{{concert_id}}/{{other_concert_id}}", status_code=204, dependencies=guard)
    def delete_duplicate(concert_id: str, other_concert_id: str, conn=Depends(conn_dep)):
        _guard(lambda: duplicates.undo(conn, concert_id, other_concert_id))

    @app.post(f"{P}/review/confirm", dependencies=guard)
    def post_review_confirm(body: ReviewConfirmBody, conn=Depends(conn_dep)):
        return confirm_stored(conn, body.concert_ids, clock(), category_overrides=body.category_overrides, prefecture_overrides=body.prefecture_overrides)

    @app.post(f"{P}/import-url", status_code=201, dependencies=guard)
    def post_import(body: ImportBody, conn=Depends(conn_dep)):
        def run():
            reader = reader_factory(raw_dir)
            try:
                return stage_import(conn, body.url, reader, clock(), resolver)
            finally:
                reader.close()
        out = _guard(run)
        out["status"] = "pending"
        out["next"] = f"{P}/import-url/{out['import_id']}/confirm"
        return out

    @app.post(f"{P}/import-url/{{import_id}}/confirm", dependencies=guard)
    def post_confirm(import_id: str, body: ConfirmBody, conn=Depends(conn_dep)):
        result = _guard(lambda: confirm_import(conn, import_id, clock(), category=body.category, prefecture_overrides=body.prefecture_overrides, note=body.note))
        if result["status"] != "succeeded":
            raise HTTPException(422, result.get("error", "confirmation failed"))
        return result

    @app.post(f"{P}/import-url/{{import_id}}/reject", status_code=204, dependencies=guard)
    def post_reject(import_id: str, note: str | None = None, conn=Depends(conn_dep)):
        _guard(lambda: reject_import(conn, import_id, clock(), note))

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/ui/")

    # static UI (no data in it; every data call still needs the token)
    app.mount("/ui", StaticFiles(directory=str(Path(__file__).parent / "web"), html=True), name="ui")
    # freely licensed thumbnails fetched by `classical-radar images` (see images.py); public like the UI shell, no personal data
    media = media_dir or Path("data/media")
    media.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media)), name="media")
    return app
