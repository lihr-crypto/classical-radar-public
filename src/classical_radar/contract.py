"""V1.5 contract layer (docs/handoff-v1.5/03_CONTRACTS.md is authoritative).

The POC parsers emit ``poc_schema_version=1`` records whose names predate the
contract (``date_precision=minute|day``, ``official_announcement_at``...).
``to_contract_bundles`` maps them to contract-shaped, *unconfirmed* records so the
two never get mixed up. Nothing here promotes a candidate to ``official_confirmed``;
that requires the human confirmation flow that does not exist yet (P1).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .parsers import JST

# ---- 3.2 enums ---------------------------------------------------------------

Category = Literal["domestic_orchestra", "overseas_orchestra_visit", "piano_recital", "other"]
Verification = Literal["official_confirmed", "needs_review"]
DatePrecision = Literal["exact_time", "date_only", "month_only", "unknown"]
PerformanceStatus = Literal["scheduled", "postponed", "cancelled", "completed", "needs_review"]
TicketStatus = Literal["not_announced", "announced", "open", "closed", "unknown"]
ArtistRole = Literal["conductor", "recital_headliner", "concerto_soloist", "other"]
UserPerformanceStatus = Literal["interested", "planning", "applied", "won", "purchased", "skipped", "attended"]
Priority = Literal["normal", "high"]
PolicyStatus = Literal["permitted", "restricted", "unknown", "blocked"]

# 3.4: names that must never reappear.
LEGACY_KEYS = frozenset({
    "announced_at", "official_announcement_at", "event_confirmation_status",
})
LEGACY_PATHS = ("/discover/japan-performances", "/me/watch")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(v: datetime | None, name: str) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return v


class ProgramItem(_Model):
    position: int = Field(ge=1)
    raw_text: str
    composer_display: str | None = None
    composer_key: str | None = None
    work_display: str | None = None
    work_key: str | None = None


class ConcertArtist(_Model):
    name_display: str
    role: ArtistRole
    artist_id: str | None = None


class TicketPhase(_Model):
    id: str
    performance_id: str
    phase_type: str
    channel: str
    eligibility: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    result_at: datetime | None = None
    payment_due_at: datetime | None = None
    start_precision: DatePrecision
    end_precision: DatePrecision
    current_status: TicketStatus
    source_document_id: str

    @model_validator(mode="after")
    def _times(self):
        for field, prec in (("starts_at", self.start_precision), ("ends_at", self.end_precision)):
            value = getattr(self, field)
            _aware(value, field)
            if prec == "exact_time" and value is None:
                raise ValueError(f"{field}: exact_time requires a timestamp")
            if prec != "exact_time" and value is not None:
                # 3.2: date-only/unknown must not be padded to a clock time such as 10:00.
                raise ValueError(f"{field}: timestamp present but precision is {prec}")
        return self


class Performance(_Model):
    id: str
    concert_id: str
    confirmation_status: Verification
    status: PerformanceStatus
    country_code: str
    prefecture_code: str | None = None
    venue_name: str
    starts_at: datetime | None = None
    local_date: date | None = None
    date_precision: DatePrecision
    ticket_phases: list[TicketPhase] = []

    @model_validator(mode="after")
    def _rules(self):
        _aware(self.starts_at, "starts_at")
        if self.date_precision == "exact_time":
            if self.starts_at is None or self.local_date is None:
                raise ValueError("exact_time requires starts_at and local_date")
            if self.starts_at.astimezone(JST).date() != self.local_date:
                raise ValueError("local_date disagrees with starts_at in Asia/Tokyo")
        else:
            if self.starts_at is not None:
                raise ValueError("starts_at must be null unless date_precision=exact_time")
            if self.date_precision == "date_only" and self.local_date is None:
                raise ValueError("date_only requires local_date")
        if self.confirmation_status == "official_confirmed":
            # 3.3: a confirmed performance needs a day-level date and a venue.
            if self.date_precision in ("month_only", "unknown") or not self.venue_name:
                raise ValueError("official_confirmed requires day-level date and venue")
            if not self.prefecture_code:
                raise ValueError("official_confirmed requires prefecture_code")
        for phase in self.ticket_phases:
            if phase.performance_id != self.id:
                raise ValueError("ticket_phase.performance_id mismatch")
        return self


class Concert(_Model):
    id: str
    category: Category
    title_ja: str
    organization_id: str | None = None
    verification_status: Verification
    official_announcement_date: date | None = None
    first_verified_at: datetime
    last_material_change_at: datetime | None = None

    @model_validator(mode="after")
    def _aware_times(self):
        _aware(self.first_verified_at, "first_verified_at")
        _aware(self.last_material_change_at, "last_material_change_at")
        return self


class SourceDocument(_Model):
    id: str
    source_id: str
    url: str
    kind: str
    published_on: date | None = None
    first_seen_at: datetime
    last_verified_at: datetime
    content_hash: str | None = None
    policy_status: PolicyStatus


class ConcertBundle(_Model):
    """Shape of examples/normalized_concert.example.json (minus ``_notice``)."""
    concert: Concert
    program_items: list[ProgramItem] = []
    concert_artists: list[ConcertArtist] = []
    performances: list[Performance]
    source_document: SourceDocument

    @model_validator(mode="after")
    def _links(self):
        for p in self.performances:
            if p.concert_id != self.concert.id:
                raise ValueError("performance.concert_id mismatch")
        return self


class UserPickup(_Model):
    user_id: str
    concert_id: str
    priority: Priority
    notes: str | None = None
    created_at: datetime


class UserPerformanceState(_Model):
    user_id: str
    performance_id: str
    status: UserPerformanceStatus
    notes: str | None = None
    updated_at: datetime


class ReminderSubscription(_Model):
    id: str
    user_id: str
    ticket_phase_id: str
    milestone: str
    offset_minutes: int
    enabled: bool


def find_legacy_keys(obj: Any, path: str = "$") -> list[str]:
    """Return JSON paths that use forbidden pre-V1.5 names or values."""
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in LEGACY_KEYS:
                hits.append(f"{path}.{k}")
            if k == "date_precision" and v in ("minute", "day"):
                hits.append(f"{path}.{k}={v}")
            hits += find_legacy_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += find_legacy_keys(v, f"{path}[{i}]")
    elif isinstance(obj, str) and any(p in obj for p in LEGACY_PATHS):
        hits.append(f"{path}={obj}")
    return hits


def announcement_sort(concert: Concert) -> tuple[date, str]:
    """3.5 rule 5: COALESCE(official_announcement_date, JST_DATE(first_verified_at)).

    Returns (sort_date, basis) where basis is ``official`` or ``first_verified_fallback``.
    """
    if concert.official_announcement_date is not None:
        return concert.official_announcement_date, "official"
    return concert.first_verified_at.astimezone(JST).date(), "first_verified_fallback"


# ---- POC (schema v1) -> contract ------------------------------------------------

_PRECISION = {"minute": "exact_time", "day": "date_only", "unknown": "unknown"}


def _category(poc: dict) -> str:
    # Auto-classification is a hint only; every mapped record stays needs_review.
    if poc["category"] == "piano_recital":
        return "piano_recital"
    if poc["category"] == "domestic_source_candidate":
        return "domestic_orchestra"
    return "other"


def to_contract_bundles(candidates: list[dict], observed_at: datetime, policy_status: str = "unknown") -> tuple[list[ConcertBundle], list[str]]:
    """Group POC candidates by concert and map them.

    Returns (bundles, rejected) where ``rejected`` lists performance ids that cannot be
    represented (no day-level date, so no ``performance`` may be created per 3.3, or an excluded-orchestra hint).
    """
    observed_at = _aware(observed_at, "observed_at")  # type: ignore[assignment]
    grouped: dict[str, list[dict]] = {}
    rejected: list[str] = []
    for c in candidates:
        if c.get("local_date") is None or c.get("category") == "excluded_domestic_orchestra":
            rejected.append(c["performance_id"])
            continue
        grouped.setdefault(c["concert_id"], []).append(c)
    bundles = []
    for concert_id, items in grouped.items():
        head = items[0]
        doc_id = f"doc-{concert_id}"
        performances = []
        for it in items:
            precision = _PRECISION[it["date_precision"]]
            performances.append(Performance(
                id=it["performance_id"], concert_id=concert_id,
                confirmation_status="needs_review", status="needs_review",
                country_code="JP", prefecture_code=None,
                venue_name=it.get("venue") or "",
                starts_at=datetime.fromisoformat(it["starts_at"]).astimezone(JST) if precision == "exact_time" else None,
                local_date=date.fromisoformat(it["local_date"]), date_precision=precision,
            ))
        bundles.append(ConcertBundle(
            concert=Concert(
                id=concert_id, category=_category(head), title_ja=head["title"],
                organization_id=head["source_id"], verification_status="needs_review",
                official_announcement_date=None, first_verified_at=observed_at,
            ),
            performances=performances,
            source_document=SourceDocument(
                id=doc_id, source_id=head["source_id"], url=head["source_url"], kind="detail",
                first_seen_at=observed_at, last_verified_at=observed_at, policy_status=policy_status,  # type: ignore[arg-type]
            ),
        ))
    return bundles, rejected


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compact_candidate(c: dict) -> dict:
    """Evidence-friendly record using V1.5 names only (no legacy keys, contract precision values)."""
    return {
        "performance_id": c["performance_id"], "concert_id": c["concert_id"], "source_id": c["source_id"], "source_url": c["source_url"],
        "title": c["title"], "category_hint": c["category"], "local_date": c["local_date"], "local_time": c["local_time"],
        "date_precision": _PRECISION[c["date_precision"]], "venue": c["venue"], "artists_raw": c["artists_raw"],
        "programme_raw": c["programme_raw"], "date_raw": c["evidence"]["date_raw"],
    }


def compact_claim(c: dict) -> dict:
    keep = ("phase_type", "audience_eligibility", "local_date", "local_time", "starts_at", "label_raw", "source_url", "linkage_status", "performance_ids")
    out = {k: c[k] for k in keep}
    out["start_precision"] = _PRECISION[c["date_precision"]]
    return out
