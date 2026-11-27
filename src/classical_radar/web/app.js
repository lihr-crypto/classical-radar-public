"use strict";
// Classical Radar web UI. No build step, no external requests. All text from the API is inserted with textContent
// (never parsed as HTML) because titles/venues come from scraped pages. Design direction: docs/UI_DIRECTION.md.
const API = "/api/v1";
const L = {
  cat: { domestic_orchestra: "国内乐团", overseas_orchestra_visit: "海外乐团来日", piano_recital: "钢琴独奏会", other: "其他" },
  ticket: { not_announced: "售票未公布", announced: "已公布开售", open: "发售中", closed: "已结束", unknown: "售票状态未知" },
  phase: { member_presale: "会员先行", general_sale: "一般发售", lottery: "抽选", additional_sale: "追加发售", other: "其他" },
  user: { interested: "想去", planning: "计划购票", applied: "已申请", won: "已中签", purchased: "已购票", skipped: "放弃", attended: "已观演" },
  precision: { month_only: "仅月份", unknown: "日期未定" },
  pstatus: { scheduled: "已安排", postponed: "延期", cancelled: "已取消", completed: "已结束", needs_review: "待确认" },
  role: { conductor: "指挥", recital_headliner: "独奏会演奏者", concerto_soloist: "客演独奏", other: "其他" },
  issue: { venue_missing: "缺场馆", prefecture_unknown: "场馆无法判定都道府县", date_not_day_level: "日期不到日" },
  run: { succeeded: "成功", failed: "失败", running: "进行中" },
};
const PREF = { "01": "北海道", "02": "青森", "03": "岩手", "04": "宮城", "05": "秋田", "06": "山形", "07": "福島", "08": "茨城", "09": "栃木", "10": "群馬", "11": "埼玉", "12": "千葉", "13": "東京", "14": "神奈川", "15": "新潟", "16": "富山", "17": "石川", "18": "福井", "19": "山梨", "20": "長野", "21": "岐阜", "22": "静岡", "23": "愛知", "24": "三重", "25": "滋賀", "26": "京都", "27": "大阪", "28": "兵庫", "29": "奈良", "30": "和歌山", "31": "鳥取", "32": "島根", "33": "岡山", "34": "広島", "35": "山口", "36": "徳島", "37": "香川", "38": "愛媛", "39": "高知", "40": "福岡", "41": "佐賀", "42": "長崎", "43": "熊本", "44": "大分", "45": "宮崎", "46": "鹿児島", "47": "沖縄" };

// <cover-rules>
// The cover of a concert is decoration made from fields the data already has; it never invents anything. Pure functions, no DOM:
// tests/js/cover.test.mjs evaluates only this block. `c` is any card-like object: { title_ja, category, organization_id, conductors?, soloists? }.
// The one place that knows an organiser's name: kicker, sources table and review list all read ORG.
const ORG = {
  nhkso: { name: "NHK交響楽団", short: "N響", code: "NHKSO", orch: true },
  tmso: { name: "東京都交響楽団", short: "都響", code: "TMSO", orch: true },
  tso: { name: "東京交響楽団", short: "東響", code: "TSO", orch: true },
  jpo: { name: "日本フィルハーモニー交響楽団", short: "日本フィル", code: "JPO", orch: true },
  njp: { name: "新日本フィルハーモニー交響楽団", short: "新日本フィル", code: "NJP", orch: true },
  yomikyo: { name: "読売日本交響楽団", short: "読響", code: "YOMIKYO", orch: true },
  tpo: { name: "東京フィルハーモニー交響楽団", short: "東京フィル", code: "TPO", orch: true },
  japanarts: { name: "ジャパン・アーツ", short: "ジャパン・アーツ", code: "JAPAN ARTS", orch: false },
  kajimoto: { name: "KAJIMOTO", short: "KAJIMOTO", code: "KAJIMOTO", orch: false },
  kanagawa_geikyo: { name: "神奈川芸術協会", short: "神奈川芸術協会", code: "KANAGAWA", orch: false },
};
const HOOK_MAX = 14;  // a quoted hook longer than this is not used: it would have to be cut, and a cut title looks like data
const CJK = /[　-ヿ㐀-鿿＀-￯]/;
const orgOf = (c) => ORG[c.organization_id] || null;
const noSpace = (s) => String(s || "").replace(/[\s　]+/g, "");
const tail = (name) => {  // the last segment of a name: ダニール・トリフォノフ -> トリフォノフ, Tomoki Kitamura -> Kitamura
  const n = String(name || "").trim();
  if (!CJK.test(n)) return n.split(/\s+/).pop();
  const parts = noSpace(n).split(/[・･＝=]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
};
function coverKind(c) {
  if (c.category === "piano_recital") return "piano";
  const o = orgOf(c);
  return o && o.orch ? "orchestra" : "presenter";
}
function coverKicker(c) {
  const o = orgOf(c);
  return o ? (coverKind(c) === "orchestra" ? o.short : o.name) : "";
}
function leadWidth(lead) {  // the widest line in em: a Japanese character is 1, a condensed Latin capital about a half
  const w = (ch) => (CJK.test(ch) ? 1 : /[A-Z]/.test(ch) ? 0.52 : /[a-z]/.test(ch) ? 0.46 : /\s/.test(ch) ? 0.25 : 0.5);
  return Math.max(0, ...leadLines(lead).map((line) => [...line].reduce((a, ch) => a + w(ch), 0)));
}
function leadLines(lead) { return CJK.test(lead) ? [lead] : String(lead).split(/\s+/).filter(Boolean); }
const LEAD_STEPS = [1.5, 2.5, 3.5, 4.5, 6, 8, 10, 14];
function leadSize(lead) { const i = LEAD_STEPS.findIndex((s) => leadWidth(lead) <= s); return i < 0 ? LEAD_STEPS.length : i + 1; }
function coverCandidates(c) {  // in order of preference; the last one is the organiser's own code and always fits
  const o = orgOf(c), kind = coverKind(c), title = c.title_ja || "", out = [];
  const hook = (title.match(/[「『《]([^」』》]+)[」』》]/) || [])[1];
  const hookOk = hook && hook.trim().length > 0 && hook.trim().length <= HOOK_MAX ? hook.trim() : null;
  if (kind === "orchestra") {
    const no = (title.match(/第\s*(\d+)\s*回/) || [])[1];
    if (no) out.push(no);
    if (hookOk) out.push(hookOk);
  } else if (kind === "piano") {
    const name = (c.soloists || [])[0];
    if (name && tail(name)) out.push(tail(name));
  } else {
    if (hookOk) out.push(hookOk);
    const flat = noSpace(title);
    for (const name of [...(c.conductors || []), ...(c.soloists || [])]) if (name && flat.includes(noSpace(name)) && tail(name)) { out.push(tail(name)); break; }
  }
  if (o) out.push(o.code);
  return out;
}
function coverLead(c, { maxW = Infinity } = {}) {  // maxW: a small thumbnail passes a limit; anything wider falls back, it is never cut
  const list = coverCandidates(c);
  return list.find((t) => leadWidth(t) <= maxW) || list[list.length - 1] || "";
}
// </cover-rules>

const TABS = [["discover", "发现", "compass"], ["season", "乐季", "table"], ["calendar", "日历", "calendar"], ["mine", "Pickup", "bookmark"], ["search", "搜索", "search"], ["review", "待确认", "check"]]
  .filter(([k]) => !(window.CR_DEMO && k === "review"));

const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }, del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } } };
const $ = (s) => document.querySelector(s);
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v; else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else if (k === "text") el.textContent = v; else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));  // any depth: a list of [separator, node] pairs is fine
  return el;
}

// the app icon's mark (five organ pipes, the middle one lit), drawn like the line icons so no image is fetched
function brandMark() {
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("viewBox", "0 0 1024 1024"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
  const add = (attrs) => { const el = document.createElementNS(SVGNS, "rect"); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); svg.append(el); };
  add({ width: 1024, height: 1024, fill: "#2e3442" });
  [380, 520, 640, 520, 380].forEach((hgt, i) => add({ x: 157 + i * 150, y: 832 - hgt, width: 110, height: hgt, rx: 55, fill: i === 2 ? "#b8955a" : "#e6e4df" }));
  return svg;
}

// ---------- icons: inline SVG line icons, 1.5 stroke, current text colour (built with createElementNS, never parsed from a string) ----------
const SVGNS = "http://www.w3.org/2000/svg";
const ICONS = {
  compass: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM15.5 8.5l-2 5-5 2 2-5z",
  calendar: "M5 6h14a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1zM4 10h16M8 4v4M16 4v4",
  table: "M5 5h14a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM4 10h16M4 14.5h16M10 10v9",
  bookmark: "M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
  x: "M6 6l12 12M18 6L6 18",
  "chevron-left": "M15 5l-7 7 7 7",
  "chevron-right": "M9 5l7 7-7 7",
  "chevron-down": "M5 9l7 7 7-7",
  "external-link": "M14 5h5v5M19 5l-9 9M17 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h5",
  check: "M5 12.5l4.5 4.5L19 7.5",
  bell: "M6 17h12M7 17v-6a5 5 0 0 1 10 0v6M10.5 20a1.5 1.5 0 0 0 3 0",
  "bell-ring": "M6 17h12M7 17v-6a5 5 0 0 1 10 0v6M10.5 20a1.5 1.5 0 0 0 3 0M20 8c0-2-.7-3.7-1.7-5M4 8c0-2 .7-3.7 1.7-5",
  alert: "M12 4l9 16H3zM12 10v4M12 17.5v.01",
  share: "M12 15V4M8.5 7.5L12 4l3.5 3.5M8 10H6a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-2",
  list: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
};
function icon(name, { size = 18, fill = false } = {}) {
  const svg = document.createElementNS(SVGNS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: fill ? "currentColor" : "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" })) svg.setAttribute(k, String(v));
  const path = document.createElementNS(SVGNS, "path"); path.setAttribute("d", ICONS[name]); svg.append(path);
  return svg;
}

// ---------- dates: everything is shown in Japan time, one format per place ----------
const TZ = "Asia/Tokyo", WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const DEMO = window.CR_DEMO || null;
const jst = (when) => {
  const o = {};
  for (const p of new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(when))) o[p.type] = p.value;
  return { y: Number(o.year), m: Number(o.month), d: Number(o.day), hh: o.hour, mm: o.minute };
};
const pad = (n) => String(n).padStart(2, "0");
const today = () => { if (DEMO && DEMO.mode === "demo") return String(DEMO.asOf).slice(0, 10); const t = jst(Date.now()); return `${t.y}-${pad(t.m)}-${pad(t.d)}`; };
const curYear = () => Number(today().slice(0, 4));
const weekday = (y, m, d) => WEEK[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
const fmt = {
  parts(p) { const [y, m, d] = p.local_date.split("-").map(Number); return { y, m, d, wd: weekday(y, m, d) }; },
  hm(iso) { const t = jst(iso); return `${t.hh}:${t.mm}`; },
  ymd(s) { const [y, m, d] = s.split("-").map(Number); return `${y === curYear() ? "" : y + "年"}${m}月${d}日`; },
  day(iso) { const t = jst(iso); return `${t.y === curYear() ? "" : t.y + "年"}${t.m}月${t.d}日 ${weekday(t.y, t.m, t.d)}`; },
  ts(iso) { if (!iso) return ""; const t = jst(iso); return `${t.y === curYear() ? "" : t.y + "年"}${t.m}月${t.d}日 ${t.hh}:${t.mm} JST`; },
  pref(c) { return c ? (PREF[c] || c) : ""; },
};
const stamp = () => (DEMO && DEMO.mode === "site" ? `数据 ${DEMO.snapshot}` : "");
function ymd(d) { return d.toISOString().slice(0, 10); }
const dayText = (key) => { const [y, m, d] = key.split("-").map(Number); return `${m}月${d}日 ${weekday(y, m, d)}`; };

async function api(path, opts = {}) {
  if (DEMO) return DEMO.handle(opts.method || "GET", path, opts.body ? JSON.parse(opts.body) : undefined);
  const res = await fetch(API + path, { ...opts, headers: { Authorization: "Bearer " + token, ...(opts.body ? { "Content-Type": "application/json" } : {}) } });
  if (res.status === 401) { logout(); throw new Error("令牌无效，请重新登录"); }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : res.status === 422 ? "请求参数不合法" : "请求失败 " + res.status);
  return data;
}
let token = DEMO ? "demo" : (store.get("cr_token") || "");
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 3500); }
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };
function logout() { token = ""; store.del("cr_token"); render(); }

// ---------- performances as text ----------
const sortedPerfs = (perfs) => (perfs || []).slice().sort((a, b) => (a.local_date + (a.starts_at || "")).localeCompare(b.local_date + (b.starts_at || "")));
const clock = (p) => (p.starts_at && p.date_precision !== "date_only" ? fmt.hm(p.starts_at) : null);  // an unknown time is never guessed
function venueText(p) {
  const pref = fmt.pref(p.prefecture_code), v = p.venue_name || "";
  return pref && v ? v.replace(new RegExp(`^${pref}[/／]\\s*`), "") : v;
}
// "11月6日 周五　14:00", "11月18日 – 19日　2 场": the dates of a concert in one line
function whenText(perfs) {
  const ps = sortedPerfs(perfs);
  if (!ps.length) return "日期未定";
  const a = ps[0], z = ps[ps.length - 1], pa = fmt.parts(a), pz = fmt.parts(z);
  if (ps.length === 1) return `${fmt.ymd(a.local_date)} ${pa.wd}　${clock(a) || "时间未公布"}`;
  if (a.local_date === z.local_date) return `${fmt.ymd(a.local_date)} ${pa.wd}　${ps.length} 场`;
  const end = pa.y === pz.y && pa.m === pz.m ? `${pz.d}日` : pa.y === pz.y ? `${pz.m}月${pz.d}日` : `${pz.y}年${pz.m}月${pz.d}日`;
  return `${fmt.ymd(a.local_date)} – ${end}　${ps.length} 场`;
}
const dateKey = (it) => { const p = sortedPerfs(it.performances)[0]; return p ? p.local_date + (p.starts_at || "") : "9999"; };
const byDate = (a, b) => dateKey(a).localeCompare(dateKey(b)) || a.concert_id.localeCompare(b.concert_id);

// ---------- cover: decoration, hidden from screen readers (the title next to it is the accessible name) ----------
function coverEl(c, { compact = false } = {}) {
  const kind = coverKind(c), cls = `cover kind-${kind}` + (compact ? " compact" : "");
  if (c.image && c.image.src) return h("div", { class: cls + " photo", "aria-hidden": "true" }, h("img", { src: c.image.src, alt: "", loading: "lazy", decoding: "async" }));
  const lead = coverLead(c, compact ? { maxW: 4.5 } : {}), latin = !CJK.test(lead), kicker = coverKicker(c);
  return h("div", { class: cls, "aria-hidden": "true" },
    compact || !kicker || kicker.toUpperCase() === lead.toUpperCase() ? null : h("span", { class: "kicker", lang: "ja" }, kicker),  // not twice when the lead is the organiser's own name
    lead ? h("span", { class: `lead s${leadSize(lead)}` + (latin ? " lat" : ""), lang: latin ? false : "ja" }, leadLines(lead).map((t) => h("span", { class: "line" }, t))) : null);
}
function saleTag(it) { return it.ticket_status === "open" || it.ticket_status === "announced" ? h("span", { class: "sale-tag" }, L.ticket[it.ticket_status]) : null; }
// a shelf card: cover, title, dates, venue. One link over the whole card
function shelfCard(it, big = false) {
  const p = sortedPerfs(it.performances)[0];
  return h("a", { class: "card" + (big ? " lead-card" : ""), href: "#concert/" + it.concert_id, "data-cid": it.concert_id },
    coverEl(it),
    h("div", { class: "text" }, saleTag(it), h("h3", { class: "title", lang: "ja" }, it.title_ja), h("p", { class: "when" }, whenText(it.performances)), p ? h("p", { class: "venue", lang: "ja" }, venueText(p) || "场馆未公布") : null));
}
// a card that stands for the same concert listed by other sources too (a reviewer said so; ADR-0006)
const moreSources = (it) => (it.other_sources && it.other_sources.length ? `+${it.other_sources.length}来源` : "");
// a list row: small cover, title, organiser and venue, date on the right
function rowItem(it, extra) {
  const ps = sortedPerfs(it.performances), p = ps[0], o = orgOf(it);
  const who = coverKind(it) === "orchestra" && o ? o.short : (o ? o.name : "");
  const day = p ? fmt.ymd(p.local_date) : "日期未定", sub = !p ? "" : ps.length > 1 ? `共 ${ps.length} 场` : [fmt.parts(p).wd, clock(p)].filter(Boolean).join(" "), tag = saleTag(it);
  return h("li", {}, h("a", { class: "item", href: "#concert/" + it.concert_id, "data-cid": it.concert_id },
    h("div", { class: "thumb" }, coverEl(it, { compact: true })),
    h("div", { class: "body" }, h("span", { class: "title", lang: "ja" }, it.title_ja), h("span", { class: "meta", lang: "ja" }, tag, tag ? " " : null, [[who, moreSources(it)].filter(Boolean).join(" "), p ? venueText(p) : ""].filter(Boolean).join("　"))),
    h("div", { class: "date" }, h("span", { class: "day" }, day), sub ? h("span", { class: "sub" }, sub) : null)), extra || null);
}
// a link from data is followed only when it is http(s): a javascript: or data: URL in scraped text must never become an href
const safeHref = (u) => { try { return ["http:", "https:"].includes(new URL(u, location.href).protocol) ? u : null; } catch { return null; } };
function credit(img) {
  if (!img) return null;
  return h("div", { class: "credit" }, `${img.subject}：© ${img.credit || "作者不明"} · ${img.license} · `, h("a", { href: safeHref(img.page_url), target: "_blank", rel: "noopener noreferrer" }, "Wikimedia Commons"));
}

// ---------- orchestra filter (calendar and search share it) ----------
// <orch-rules>
// The seven orchestras whose own concerts are the "东京乐团" type, in their fixed order. Both filters offer exactly these, several at once; any other orchestra is found by typing its name in the search box.
const SEVEN_ORDER = ["nhkso", "tmso", "tso", "jpo", "njp", "yomikyo", "tpo"];
// any selected orchestra plays: a row with no known orchestra is hidden while a filter is on
const orchMatch = (orchestras, selected) => selected.size === 0 || (orchestras || []).some((o) => selected.has(o.key));
// a selection can only hold the seven: a stale key is dropped, so a filter can never hide every row while no chip is lit
const onlySeven = (selected) => { for (const k of [...selected]) if (!SEVEN_ORDER.includes(k)) selected.delete(k); return selected; };
// </orch-rules>
// The chips: "全部乐团" and one per orchestra. The buttons are built once and only their pressed state changes (paint), so the focused one is never replaced.
function orchFilterChips(selected, onChange, { small = false } = {}) {
  const cls = "chip tokiwa" + (small ? " small" : "");
  const all = h("button", { type: "button", class: cls, onclick: () => { selected.clear(); onChange(); } }, "全部乐团");
  const each = SEVEN_ORDER.map((k) => h("button", { type: "button", class: cls, onclick: () => { selected.has(k) ? selected.delete(k) : selected.add(k); onChange(); } }, ORG[k].short));
  const paint = () => { onlySeven(selected); all.setAttribute("aria-pressed", String(selected.size === 0)); each.forEach((b, i) => b.setAttribute("aria-pressed", String(selected.has(SEVEN_ORDER[i])))); };
  paint();
  return { kids: [all, ...each], paint };
}

// ---------- data for the lists ----------
const EMPTY_FLT = () => ({ composer: [], work: [], conductor: [], performer: [], venue: [] });
const state = { months: 12, browse: { q: {}, shown: {} }, search: { q: "", kind: null, orch: new Set() }, calMonth: null, calDay: null, calMode: "show", calOrch: new Set(), calPick: false, calPickYear: null, calDir: 0, calFocusTitle: false, reviewSel: new Set(), navCount: 0, restore: null };
const listCache = new Map();
// the discover API has no "kind" filter (kind is a UI idea), so the lists fetch every page once and group in the browser
function loadAll(months, flt) {
  const key = JSON.stringify([months, flt]);
  if (!listCache.has(key)) {
    const qs = (page) => { const q = new URLSearchParams({ months, region_mode: "kanto_first", page, limit: 100 }); for (const [d, vs] of Object.entries(flt)) vs.forEach((v) => q.append(d, v)); return q; };
    listCache.set(key, (async () => {
      const first = await api(`/discover?${qs(1)}`);
      const more = await Promise.all(Array.from({ length: Math.max(0, Math.ceil(first.total / 100) - 1) }, (_, i) => api(`/discover?${qs(i + 2)}`)));
      return [first, ...more].flatMap((r) => r.items);
    })().catch((e) => { listCache.delete(key); throw e; }));
  }
  return listCache.get(key);
}
// the discover shelves and lists show the capital area only (33 of 537 concerts are elsewhere, so a switch was not worth its place); search and the browse pages include everything
const inKanto = (items) => items.filter((it) => it.region_group === "kanto");
function bucket(items) {
  const out = { presenter: [], piano: [], orchestra: [] };
  for (const it of items) out[coverKind(it)].push(it);
  for (const k of Object.keys(out)) out[k].sort(byDate);
  return out;
}
// the chips of an orchestra list: the chosen orchestra lives in the address (#list/orchestra/<id>), so a reload, a copied link or a new tab shows the same page.
// replaceState, not a new history entry: "back" still goes to the page the list was opened from, and no hashchange is fired, so render() is called by hand
const orchName = (id) => (ORG[id] && ORG[id].short) || id;
function orchChips(orchItems, current) {
  const n = (id) => orchItems.filter((it) => it.organization_id === id).length;
  const go = (id) => { history.replaceState(history.state, "", id ? "#list/orchestra/" + id : "#list/orchestra"); render(); };
  return h("div", { class: "chip-row", role: "group", "aria-label": "按乐团" },
    h("button", { type: "button", class: "chip tokiwa", "aria-pressed": String(!current), onclick: () => go(null) }, "全部"),
    Object.entries(ORG).filter(([, o]) => o.orch).map(([id, o]) => h("button", { type: "button", class: "chip tokiwa", "aria-pressed": String(current === id), disabled: !n(id) && current !== id,
      onclick: () => go(current === id ? null : id) }, o.short)));
}
function section(title, count, href, ...kids) {
  return h("section", { class: "section" }, h("div", { class: "section-head" }, h("h2", { class: "section-title" }, title), count ? h("a", { class: "section-link", href }, `全部 ${count}`) : null), ...kids);
}
// a shelf for one orchestra on the discover page; its link is an ordinary address (#list/orchestra/<id>), so it also works opened in a new tab, copied or bookmarked
const ORCH_SHELF_ROWS = 4;
function orchSection(id, items) {
  return h("section", { class: "section" }, h("div", { class: "section-head" }, h("h2", { class: "section-title" }, orchName(id)),
    h("a", { class: "section-link", href: "#list/orchestra/" + id, "aria-label": `${orchName(id)} 全部 ${items.length} 场` }, `全部 ${items.length}`)),
  h("ul", { class: "row-list" }, items.slice(0, ORCH_SHELF_ROWS).map((it) => rowItem(it))));
}
// ---------- tour leads from a third-party site (ADR-0007): outlined, labelled unverified, never mixed into the official lists ----------
const LEAD_NOTE = "第三方整理，未经官方核实，请以主办方官网为准。";
function leadPeriod(l) {
  if (l.date_from) {
    const a = l.date_from, b = l.date_to || l.date_from, [, bm, bd] = b.split("-").map(Number);
    if (a === b) return fmt.ymd(a);
    // same month: "11月20日 – 23日", the way whenText writes a range; another month or year keeps its month (and year)
    return `${fmt.ymd(a)} – ${a.slice(0, 7) === b.slice(0, 7) ? "" : (a.slice(0, 4) === b.slice(0, 4) ? "" : b.slice(0, 4) + "年") + bm + "月"}${bd}日`;
  }
  if (l.month_hint) { const [y, m] = l.month_hint.split("-").map(Number); return `${y}年${m}月（具体日期未定）`; }
  return l.period_raw || "日期未定";
}
const leadName = (l) => (l.orchestra && l.orchestra.display) || l.orchestra_name;
const leadCities = (l) => (l.cities || []).slice(0, 4).join("、") + ((l.cities || []).length > 4 || l.more_cities ? " 等" : "");
function leadCard(l) {
  return h("a", { class: "tour-card", href: "#lead/" + l.lead_id },
    h("span", { class: "tag warn" }, "未核实"),
    h("span", { class: "tour-name", lang: "ja", title: leadName(l) }, leadName(l)),  // title: the shelf cuts long text, the full text is still one hover away
    h("span", { class: "muted small tour-when", title: leadPeriod(l) }, leadPeriod(l)),
    leadCities(l) ? h("span", { class: "muted small tour-line tour-cities", lang: "ja", title: leadCities(l) }, leadCities(l)) : null,
    l.conductor ? h("span", { class: "muted small tour-line", lang: "ja", title: "指挥 " + l.conductor }, "指挥 " + l.conductor) : null);
}
async function loadLeads() {
  try { return await api("/leads"); } catch { return null; }  // no data, no shelf: the page works without it
}
async function viewLeads(root) {
  const data = await loadLeads(), items = data ? data.items : [];
  const page = h("div", { class: "page" }, h("a", { class: "back-link", href: "#discover" }, icon("chevron-left", { size: 18 }), "发现"), h("h1", { class: "page-title", tabindex: "-1" }, "海外乐团来日"),
    h("p", { class: "muted small" }, LEAD_NOTE));
  if (!items.length) page.append(h("div", { class: "empty" }, "目前没有收录海外乐团来日线索。"));
  const open = items.filter((l) => !l.covered_by), done = items.filter((l) => l.covered_by);
  if (open.length) page.append(h("ul", { class: "tour-list" }, open.map((l) => h("li", {}, leadCard(l)))));
  if (done.length) page.append(h("section", { class: "section" }, h("h2", { class: "section-title" }, "已有官方信息"),
    h("ul", { class: "tour-list" }, done.map((l) => h("li", {}, h("div", { class: "tour-card done" }, h("span", { class: "tour-name", lang: "ja" }, leadName(l)), h("span", { class: "muted small" }, leadPeriod(l)),
      h("a", { href: "#concert/" + l.covered_by }, "查看官方信息")))))));
  const srcHref = data && data.source ? safeHref(data.source.url) : null;  // the link comes from the data, never from the code
  page.append(h("p", { class: "meta-line" }, "来源：", srcHref ? h("a", { href: srcHref, target: "_blank", rel: "noopener noreferrer" }, "オケミン！") : "オケミン！"));
  root.append(page);
  return { title: "海外乐团来日" };
}
async function viewLead(root, r) {
  const data = await loadLeads(), l = data && data.items.find((x) => x.lead_id === r.arg);
  if (!l) { root.append(h("div", { class: "page" }, h("a", { class: "back-link", href: "#leads" }, icon("chevron-left", { size: 18 }), "海外乐团来日"), h("div", { class: "empty" }, "没有找到这条线索，或者它已经从来源页面消失。"))); return { title: "海外乐团来日" }; }
  const src = safeHref(l.article_url);
  const facts = [["日期", leadPeriod(l)], ["城市", leadCities(l)], ["指挥", l.conductor], ["独奏", l.soloists]].filter(([, v]) => v);
  const page = h("div", { class: "page tour-page" }, h("a", { class: "back-link", href: "#leads" }, icon("chevron-left", { size: 18 }), "海外乐团来日"),
    h("header", { class: "tour-head" }, h("h1", { class: "tour-title", tabindex: "-1", lang: "ja" }, leadName(l)),
      h("ul", { class: "tour-facts" }, facts.map(([k, v]) => h("li", {}, h("span", { class: "k" }, k), h("span", { lang: "ja" }, v))))));
  if (l.covered_by) page.append(h("a", { class: "button-secondary tour-official", href: "#concert/" + l.covered_by }, "已有官方信息，查看"));
  if ((l.performances || []).length) page.append(h("section", { class: "tour-block" }, h("h2", { class: "tour-sub" }, "场次"),
    h("ol", { class: "tour-perfs" }, l.performances.map((p) => h("li", {},
      h("div", { class: "tour-perf-head" }, h("span", { class: "num" }, `${fmt.ymd(p.local_date)} ${p.local_time}`), h("span", { lang: "ja" }, [p.city, p.venue].filter(Boolean).join(" · "))),
      (p.program || []).length ? h("ul", { class: "tour-prog", lang: "ja" }, p.program.map((x) => h("li", {}, x))) : null)))));
  else page.append(h("p", { class: "muted" }, "来源页面还没有列出各场次。"));
  page.append(h("p", { class: "muted small tour-credit" }, LEAD_NOTE, " 来源：", src ? h("a", { href: src, target: "_blank", rel: "noopener noreferrer" }, "オケミン！原文") : "オケミン！"));
  root.append(page);
  return { title: leadName(l) };
}

const footnote = () => h("p", { class: "meta-line" }, stamp() ? h("span", {}, stamp()) : null, h("a", { href: "#sources" }, "数据来源与采集状态"), h("span", {}, "未收录不代表没有公演"));

// ---------- views ----------
async function viewDiscover(root) {
  const all = await loadAll(state.months, EMPTY_FLT()), b = bucket(inKanto(all));
  const page = h("div", { class: "page" },
    h("div", { class: "head" }, h("div", { class: "title-row" }, h("h1", { class: "page-title", tabindex: "-1" }, "发现"), monthsSeg())),
    all.length ? browseStrip(all) : null);
  if (b.presenter.length) {
    const [first, ...rest] = b.presenter;
    page.append(section("主办方公演", b.presenter.length, "#list/presenter", h("div", { class: "lead-wrap" }, shelfCard(first, true), rest.length ? h("div", { class: "shelf" }, rest.slice(0, 11).map((it) => shelfCard(it))) : null)));
  }
  if (b.piano.length) page.append(section("钢琴独奏会", b.piano.length, "#list/piano", h("div", { class: "shelf" }, b.piano.slice(0, 12).map((it) => shelfCard(it)))));
  const leadData = await loadLeads(), openLeads = leadData ? leadData.items.filter((l) => !l.covered_by) : [];  // after the official shelves, before the long list of domestic concerts
  if (openLeads.length) page.append(section("海外乐团来日", openLeads.length, "#leads", h("div", { class: "shelf" }, openLeads.slice(0, 12).map((l) => leadCard(l)))));
  // one shelf per orchestra, never one merged shelf: each has its own title, count and "全部" link into that orchestra's list
  // the known orchestras in their fixed order, then any other organisation that has orchestra items (so no item can silently drop off the page)
  const shelfIds = [...Object.keys(ORG).filter((k) => ORG[k].orch), ...new Set(b.orchestra.map((it) => it.organization_id))];
  for (const id of new Set(shelfIds)) {
    const mine = b.orchestra.filter((it) => it.organization_id === id);
    if (mine.length) page.append(orchSection(id, mine));
  }
  if (!b.presenter.length && !b.piano.length && !b.orchestra.length) page.append(h("div", { class: "empty" }, "这个时间范围内没有项目。可以切换到 24 个月。"));
  page.append(h("p", { class: "meta-line" }, "这里只列首都圈的节目；其他地区的请用搜索。"), footnote());
  root.append(page);
}

const LIST_TITLE = { presenter: "主办方公演", piano: "钢琴独奏会", orchestra: "东京乐团" };
async function viewList(root, r) {
  const key = r.arg, orch = key === "orchestra" ? r.sub || null : null;  // the chosen orchestra comes from the address, never from remembered state
  // from the season page (#list/orchestra/<id>/<season>): the cards of that orchestra and that season, the very ones its grid shows, over the 24 months the season page loads.
  // The plain orchestra list is "the next state.months months, every season", so it cannot be what a season's 全部公演 link opens (ADR-0020, revision 3)
  const season = orch && r.season != null && SEVEN_ORDER.includes(orch) ? r.season : null;
  const all = await loadAll(season != null ? 24 : state.months, EMPTY_FLT()), b = bucket(inKanto(all));
  const items = season != null ? seasonGrid(inKanto(all).filter((it) => itemOrchs(it, SEVEN_ORDER).includes(orch)), orch, season).items.sort(byDate) : orch ? b.orchestra.filter((it) => it.organization_id === orch) : b[key];
  const title = season != null ? `${orchName(orch)} ${seasonName(season)} 乐季` : orch ? orchName(orch) : LIST_TITLE[key];
  const page = h("div", { class: "page" }, h("button", { type: "button", class: "back", onclick: season != null ? goBackOr(seasonHref(orch)) : goBack }, icon("chevron-left", { size: 20 }), season != null ? "乐季" : "发现"),
    h("h1", { class: "page-title", tabindex: "-1" }, title));
  if (key === "orchestra" && season == null) page.append(h("div", { class: "section" }, orchChips(b.orchestra, orch)));
  if (!items.length) page.append(h("div", { class: "empty" }, season != null ? `暂无 ${seasonName(season)} 乐季的节目（仅首都圈）` : "这个时间范围内没有项目。可以在发现页切换到 24 个月。"));
  // the season's count is not "个节目": the season page merges a programme played on two days into one 节目, while this list has one row per card
  else page.append(h("p", { class: "meta-line" }, season != null ? `共 ${items.length} 条` : `${items.length} 个节目`), h("ul", { class: "row-list" }, items.map((it) => rowItem(it))));
  root.append(page);
  return { title };
}

// ---------- browse: conductors, soloists, composers and pieces (ADR-0010) ----------
// <browse-rules>
// Pure (no DOM, no globals): tests/js/browse.test.mjs evaluates only this block. Concerts are grouped by what is WRITTEN, never by how alike two texts look (03_CONTRACTS 3.2: no edit distance, no
// fuzzy matching). bfold folds width, case, accents, whitespace and punctuation (and a dash written in place of ー) the way demo.js and works.py fold text for the filters. On top of that two kinds of
// sameness are written down as rules (ADR-0014, ADR-0019): NOTATION (how a title is quoted or bracketed, the marks a scraped line carries, the word that introduces an opus number, the long-vowel mark)
// and EVIDENCE the row itself carries (an arranger credit in a composer field, an opus / catalogue / key that is present in one spelling and absent in another, the same opus or catalogue number on a
// translated title). Composers written with initials or a generation come from a short reviewed list (COMPOSER_ALIAS). A rule never joins two pieces when the loaded rows show two different numbers.
const bfold = (s) => String(s || "").normalize("NFKC").toLowerCase().replace(/[―—]/g, "ー").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[\s.・·=＝|\-‐‑–]/g, "").normalize("NFC");
const MARKS = /[*★☆◆◇\u2665\u2661※●○■□▲△♪♫]/g, BRACKETS = "《》「」『』〈〉⟨⟩“”‘’\"'()（）\\[\\]【】", NOTATION = new RegExp("[" + BRACKETS + "]", "g"), BETWEEN_DIGITS = new RegExp("(\\d)\\s*[" + BRACKETS + "]+\\s*(?=\\d)", "g");
const nameFold = (s) => bfold(String(s || "").normalize("NFKC").replace(MARKS, ""));  // a person's or composer's name: bfold, minus the marks a scraped line carries ("カミラ・ニールンド◇")
// a title: bfold, minus the marks and bracket glyphs (a bracket between two digits stays a separator, so "op.10(12)" and "op.101(2)" never become one number), with op. / Op. / 作品 written "op"
const workFold = (s) => bfold(String(s || "").normalize("NFKC").replace(MARKS, "").replace(BETWEEN_DIGITS, "$1_").replace(NOTATION, "").replace(/(?:op\.?|作品)\s*(?=\d)/gi, "op"));
// a credit after the name ("W.A.モーツァルト(オスピタル編)", "J.ブラームス (阪田知樹 編曲)") is not part of the name; a bracket that is cut off ("ラヴェル(志村和音") is dropped by the resolver, and only when what is left is a known name
const CREDIT_TAIL = /\s*[（(][^）)]*(?:編|アレンジ|arr|版|補筆|校訂|訳)[^）)]*[）)]\s*$/i, OPEN_TAIL = /\s*[（(][^）)]*$/;
const creditless = (s) => { let t = String(s || "").trim(); for (let u = t.replace(CREDIT_TAIL, "").trim(); u !== t; u = t.replace(CREDIT_TAIL, "").trim()) t = u; return t; };
// scraped programme lines sometimes put a note or a title in the composer field: such a string is neither listed nor linked
const JUNK_COMPOSER = /^[(（◎※]|[/／]/, JUNK_WORDS = ["作曲", "振付", "編曲", "作詞", "指揮"];
function isComposerName(s) {
  const t = creditless(s);
  return t.length > 0 && t.length <= 20 && !JUNK_COMPOSER.test(t) && !JUNK_WORDS.includes(t);
}
// Composers written another way in rows that are already stored (ADR-0019): spelling -> the composer key the stored rows of that composer carry, or -> the other spelling for a composer that has no key.
// Reviewed one by one against the real data; a bare family name is never listed (シュトラウス, アダムズ, ロウ, ノルドグレン stay as they are: they could be several people).
const COMPOSER_ALIAS = {
  "P.チャイコフスキー": "tchaikovsky", "P.I.チャイコフスキー": "tchaikovsky", "W.A.モーツァルト": "mozart", "J.ブラームス": "brahms", "A.ドヴォルジャーク": "dvorak", "M.ラヴェル": "ravel",
  "S.V.ラフマニノフ": "rachmaninoff", "I.ストラヴィンスキー": "stravinsky", "F.リスト": "liszt", "G.ヴェルディ": "verdi", "G.ガーシュウィン": "gershwin", "G.フォーレ": "faure", "P.デュカス": "dukas",
  "P.マスカーニ": "mascagni", "J.シュトラウスII世": "j-strauss-ii", "ヨハン・シュトラウスII": "j-strauss-ii", "シュトラウスII": "j-strauss-ii", "シュトラウスII世": "j-strauss-ii",
  "J.シュトラウスI世": "j-strauss-i", "シュトラウスI世": "j-strauss-i", "バッハ=ブゾーニ": "bach", "J.S.バッハ=J.ブラームス": "bach",
  "エンニオ・モリコーネ": "モリコーネ", "シャルル=マリー・ヴィドール": "ヴィドール", "グノー=リスト編": "グノー",
};
const ALIAS_ID = new Map(Object.entries(COMPOSER_ALIAS).map(([from, to]) => [nameFold(from), /^[a-z][a-z0-9-]*$/.test(to) ? to : nameFold(to)]));
// role -> page: the conductor page, the soloist page; role "other" (orchestras, choruses, stray names) is plain text, never linked, never counted
const personDim = (role) => (role === "conductor" ? "conductor" : role === "recital_headliner" || role === "concerto_soloist" ? "performer" : null);
// the ids a link can carry without knowing any other concert (the detail page has only its own rows); the browse page canonicalises them with makeResolver
const localComposerId = (p) => p.composer_key || nameFold(p.composer);
const localWorkId = (p) => p.work_key || (workFold(p.work) ? "~" + localComposerId(p) + "|" + workFold(p.work) : "");
const browseHref = (dim, id) => "#browse/" + dim + (id ? "/" + encodeURIComponent(id) : "");
// "open in Apple Music Classical" (ADR-0013): the page of this composer / piece / conductor / soloist in Apple's Classical app. Apple's ids are not ours, so they come from the
// reviewed table window.CR_CLASSICAL (classical-links.js, written by scripts/resolve_classical_links.py): composers[composer id] and people[nameFold(name)] are artist ids, works[work id] a work slug.
// The table is keyed by LOCAL ids (the ones a programme row carries by itself, see localWorkId): they do not change when other concerts join or leave the loaded list, which the resolver's ids can.
// A page the table does not know gets NO link: a search link is a dead end (the app drops the text and opens its empty search screen). Only the fixed address plus an id of the right shape is ever produced.
const CLASSICAL = "https://classical.music.apple.com/jp/";
const CLASSICAL_GROUP = { composer: "composers", work: "works", conductor: "people", performer: "people" };
const ownKey = (o, k) => !!o && typeof o === "object" && Object.prototype.hasOwnProperty.call(o, k);  // "constructor" or "__proto__" is never an id
// ids: one id or a list. Exactly one distinct answer is a link; none, or two ids that disagree, is no link
const classicalHref = (dim, ids, table) => {
  const group = ownKey(CLASSICAL_GROUP, dim) && ownKey(table, CLASSICAL_GROUP[dim]) ? table[CLASSICAL_GROUP[dim]] : null, seen = new Set();
  for (const id of [].concat(ids)) if (ownKey(group, id)) seen.add(String(group[id]));
  const v = seen.size === 1 ? [...seen][0] : "";
  if (dim === "work") return /^[a-z0-9-]{3,100}$/.test(v) ? CLASSICAL + "work/" + v : null;
  return /^[1-9]\d{0,11}$/.test(v) ? CLASSICAL + "artist/" + v : null;
};
// A piece with no page of its own (ADR-0019, which replaces the composer-page button of ADR-0016): the Classical app's SEARCH screen with the composer and the title already typed in. The app reads ?q= (the user tried it on an iPhone,
// 2026-11-20) and drops the ?term= of ADR-0013. searchTerm is the text put in the address: one line, no control characters, at most 100 characters.
const searchTerm = (title) => [...String(title == null ? "" : title).replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, " ").replace(/\s+/g, " ").trim()].slice(0, 100).join("").trim();
const classicalSearchHref = (term) => { const t = searchTerm(term); try { return t ? CLASSICAL + "search?q=" + encodeURIComponent(t) : null; } catch (e) { return null; } };  // encodeURIComponent throws on a lone surrogate
const programPiece = (it) => ({ composer: it.composer_display || "", composer_key: it.composer_key || null, work: it.work_display || it.raw_text || "", work_key: it.work_key || null });  // a detail-page programme row in the shape of a card's `pieces`
const personHref = (role, name) => { const dim = personDim(role), id = nameFold(name); return dim && id ? browseHref(dim, id) : null; };
const composerHref = (p) => { const id = isComposerName(p.composer) ? localComposerId(p) : ""; return id ? browseHref("composer", id) : null; };
const workHref = (p) => { const id = isComposerName(p.composer) ? localWorkId(p) : ""; return id ? browseHref("work", id) : null; };
// What the loaded concerts say about each other. These are PAGE ids: they can change when other concerts join or leave the list. The reviewed Apple table is keyed by LOCAL ids (localComposerId /
// localWorkId, which never change) and classicalIds hands the page the local id of every row joined to it, so a merge never costs a link.
const KANJI_KANA = /[\u3040-\u30ff\u3400-\u9fff]/;
const pageFold = (s) => workFold(s).replace(/ー/g, "");  // the page id's fold also drops the long-vowel mark (ラプソディー / ラプソディ, サクソフォーン / サクソフォン)
// genre, instrument and filler words: what is left of a title without them is what makes it THAT piece
const GENERIC = ["四重奏曲", "三重奏曲", "五重奏曲", "二重奏曲", "ヴァイオリン", "オーケストラ", "ノクターン", "エチュード", "プレリュード", "ポロネーズ", "スケルツォ", "ヴィオラ", "クラリネット", "オーボエ", "フルート", "ワルツ", "マズルカ", "バラード", "ソナチネ", "ソナタ", "ロンド", "フーガ",
  "序曲", "前奏曲", "間奏曲", "幻想曲", "狂詩曲", "協奏曲", "交響曲", "交響詩", "変奏曲", "舞曲", "組曲", "小品", "練習曲", "夜想曲", "即興曲", "奇想曲", "行進曲", "歌曲集", "歌曲", "舟歌", "ピアノ", "チェロ", "管弦楽", "弦楽", "合唱", "独奏", "全曲", "ための", "による", "第", "番", "no", "と", "の"];
const GENERIC_RX = new RegExp(GENERIC.join("|"), "g");
const isSpecific = (core) => [...core.replace(GENERIC_RX, "").replace(/[\d_]+/g, "")].length >= 2;
// a title without its key signature, opus number, catalogue numbers and the year of composition in brackets, and without the word that names the kind of the parent work in front of it (歌劇「フィガロの結婚」序曲 = 「フィガロの結婚」序曲).
// The digits of an opus run together with its sub-number in the fold (op.49-1 -> op491), so none of it is left in the title. `opus`, `cat` (the first catalogue number), `key` and `year` are what two spellings of one piece must not contradict
const KIND_PREFIX = /^(?:喜歌劇|歌劇|楽劇|オペラ|交響詩|劇音楽|バレエ音楽|バレエ)/, CATALOGUE = /(^|[^a-z])(kv?|bwv|hwv|hob|wab|wwv|rv|sz|trv|woo|bb|d|s|b|r)(\d+(?:[a-z](?![a-z\d]))?)/;
const coreOf = (fold) => {
  let opus = "", cat = "", key = "", year = "";
  let core = fold.replace(/[嬰変]?[ハニホヘへトイロ][長短]調/g, (m) => { key = key || m; return ""; }).replace(/op(\d+(?:[a-z](?![a-z\d]))?(?:_\d+(?:[a-z](?![a-z\d]))?)*)/g, (m, d) => { opus = opus || d; return ""; });
  for (let before = ""; before !== core; ) { before = core; core = core.replace(CATALOGUE, (m, pre, k, d) => { cat = cat || k + d; return pre; }); }
  core = core.replace(/(?:19|20)\d{2}$/, (m) => { year = m; return ""; }).replace(/[,/、;]+/g, "").replace(KIND_PREFIX, "");
  return { core, opus, cat, key, year };
};
// opus, catalogue and piece number of a title in either script, to tell whether an English line is the translation of the Japanese line before it
const GENRE_PAIRS = [["交響曲", /symphon/], ["協奏曲", /concert/], ["ソナタ", /sonat/], ["四重奏", /quartet/], ["三重奏", /trio/]];
function sameListing(jp, other) {
  const num = (t) => {
    const x = String(t || "").normalize("NFKC").toLowerCase(), o = x.match(/(?:op\.?|作品)\s*(\d+(?:\s*[-_/–]\s*\d+)*)/), c = x.match(/(?:^|[^a-z])(?:kv?|bwv|hob|wab|wwv|rv|sz|trv|woo|d|s)\.?\s*(\d+[a-z]?)/), n = x.match(/第\s*(\d+)\s*番|no\.?\s*(\d+)/);
    return { opus: o ? o[1].replace(/\D+/g, "_") : "", cat: c ? c[0].replace(/[^a-z\d]/g, "") : "", num: n ? n[1] || n[2] : "", x };
  };
  const a = num(jp), b = num(other);
  if ((a.opus && b.opus && a.opus !== b.opus) || (a.cat && b.cat && a.cat !== b.cat) || (a.num && b.num && a.num !== b.num)) return false;
  if (a.opus && a.opus === b.opus) return true;
  if (a.cat && a.cat === b.cat) return true;
  const g = GENRE_PAIRS.find(([, rx]) => rx.test(b.x));
  return !!(a.num && a.num === b.num && g && a.x.includes(g[0]));
}
const TAIL_BRACKET = /[（(]([^（()）]*)[）)]\s*$/;
// a trailing bracket of names ("ヴァイオリン・ソナタ(諏訪内、プレトニョフ)", "(ピアノ:桑原志織)") that are all the concert's own conductor or soloists is a performer credit, not part of the title; names shorter than two characters count for nothing
const creditOf = (work, it) => {
  const w = String(work || ""), m = w.match(TAIL_BRACKET);
  if (!m) return null;
  const names = [...(it.conductors || []), ...(it.soloists || [])].map(nameFold).filter(Boolean);
  const toks = m[1].replace(/[^、，,／/＆&:：]{1,10}[:：]/g, "").split(/[、，,／/・＆&:：\s]+/).map(nameFold).filter(Boolean);  // "(ピアノ:桑原志織)": the role word before a colon is dropped
  return toks.length && toks.every((t) => [...t].length >= 2 && names.some((n) => n.includes(t))) ? w.slice(0, m.index).trim() : null;
};
// Two ids of one name: a spelling that has no key is joined to a keyed one only when that is unambiguous (one folded spelling that carries two keys, or one composer+title that carries two work keys, is left out).
function makeResolver(items) {
  const comp = new Map(), work = new Map(), keys = new Set(), bad = new Set(), valid = (p) => isComposerName(p.composer);
  const note = (map, tag, k, v) => { const kk = tag + k; if (bad.has(kk)) return; if (map.has(k) && map.get(k) !== v) { map.delete(k); bad.add(kk); } else map.set(k, v); };
  for (const it of items) for (const p of it.pieces || []) if (valid(p) && p.composer_key) { keys.add(p.composer_key); note(comp, "c", nameFold(creditless(p.composer)), p.composer_key); }
  const known = (f) => ALIAS_ID.get(f) || comp.get(f) || "";
  const baseName = (s) => { const t = creditless(s), open = t.replace(OPEN_TAIL, "").trim(); return open && open !== t && known(nameFold(open)) ? open : t; };
  const composerId = (p) => p.composer_key || known(nameFold(baseName(p.composer))) || nameFold(baseName(p.composer));
  const canonComposer = (id) => { if (keys.has(id)) return id; const f = nameFold(baseName(id)); return known(f) || f; };
  // a performer credit is dropped for a spelling when it fits the concert it stands in, and then in every concert (the same text is the same credit)
  const credited = new Set();
  for (const it of items) for (const p of it.pieces || []) if (valid(p) && creditOf(p.work, it) !== null) credited.add(p.work);
  const analyse = (it) => (it.pieces || []).map((p) => {
    if (!valid(p)) return null;
    const title = credited.has(p.work) ? creditOf(p.work, it) || String(p.work).replace(TAIL_BRACKET, "").trim() : String(p.work || "");
    return { p, cid: composerId(p), title, text: baseName(p.composer), full: pageFold(p.work), fold: pageFold(title) };
  });
  const all = items.map(analyse);
  for (const rows of all) for (const r of rows) if (r && r.p.work_key && r.fold) note(work, "w", r.cid + "|" + r.fold, r.p.work_key);
  // families: the same composer and the same title once key, opus and catalogue number are taken away. A family is one piece only if its rows show no two different numbers or keys
  const fam = new Map(), info = (r) => r.info || (r.info = coreOf(r.fold)), loose = (r) => !r.p.work_key && r.fold && !work.has(r.cid + "|" + r.fold);
  for (const rows of all) for (const r of rows) if (r && loose(r)) {
    const i = info(r), k = r.cid + "|" + i.core;
    if (!fam.has(k)) fam.set(k, { opus: new Set(), cat: new Set(), key: new Set(), year: new Set() });
    const f = fam.get(k);
    if (i.opus) f.opus.add(i.opus);
    if (i.cat) f.cat.add(i.cat);
    if (i.key) f.key.add(i.key);
    if (i.year) f.year.add(i.year);
  }
  const oneFamily = (r) => { const i = info(r), f = fam.get(r.cid + "|" + i.core); return isSpecific(i.core) && (!f || (f.opus.size <= 1 && f.cat.size <= 1 && f.key.size <= 1 && f.year.size <= 1)); };
  const baseId = (r) => {
    if (!r.fold) return "";
    const one = !r.p.work_key && oneFamily(r);
    return r.p.work_key || work.get(r.cid + "|" + r.fold) || (one && work.get(r.cid + "|" + info(r).core)) || "~" + r.cid + "|" + (one ? info(r).core : r.fold);  // a family joins the keyed piece that is written as its plain title
  };
  // an English line right after the Japanese line of the same composer joins that piece only on evidence (same opus or catalogue number, or the same piece number of the same genre),
  // and only if that holds for EVERY place the English spelling is written; a piece such as an English-titled new work after a Japanese one stays its own piece
  const follows = (rows, i) => { const r = rows[i], q = i ? rows[i - 1] : null; return !!(r && q && q.cid === r.cid && r.fold && q.fold && !KANJI_KANA.test(r.p.work || "") && KANJI_KANA.test(q.p.work || "") && sameListing(q.p.work, r.p.work)); };
  const tr = new Map();
  for (const rows of all) rows.forEach((r, i) => {
    if (!r || KANJI_KANA.test(r.p.work || "") || !r.fold) return;
    const k = r.cid + "|" + r.full, t = tr.get(k) || tr.set(k, { ids: new Set(), lone: false }).get(k);
    if (follows(rows, i)) t.ids.add(baseId(rows[i - 1])); else t.lone = true;
  });
  const memo = new WeakMap();
  const rowsOf = (it) => { const hit = memo.get(it); if (hit) return hit; const rows = analyse(it), out = rows.map((r, i) => { if (!r) return null; const t = tr.get(r.cid + "|" + r.full), joined = !!t && !t.lone && t.ids.size === 1 && follows(rows, i); return { ...r, tr: joined, id: joined ? [...t.ids][0] : baseId(r) }; }).filter(Boolean); memo.set(it, out); return out; };
  // every spelling (and every merged core) any loaded row is written with -> the page that row lands on, so an address or a detail link written with the row's own text finds its page.
  // A core shared by several pages (the family split after all) goes to the smallest id: a stored address still opens a page
  const seen = new Map(), cores = new Map(), pages = new Set();
  for (const it of items) for (const r of rowsOf(it)) {
    pages.add(r.id);
    for (const k of [r.cid + "|" + r.full, r.cid + "|" + r.fold]) seen.set(k, r.id);
    if (!r.tr && loose(r)) { const k = r.cid + "|" + info(r).core; if (info(r).core && (!cores.has(k) || r.id < cores.get(k))) cores.set(k, r.id); }
  }
  const canonWork = (id) => {
    if (!String(id).startsWith("~")) return id;  // a reviewed work key is used as it is
    const rest = id.slice(1), i = rest.indexOf("|");
    if (i < 0) return id;
    const k = canonComposer(rest.slice(0, i)) + "|" + pageFold(rest.slice(i + 1));  // an address written before ADR-0014 / ADR-0019 carries an older fold of the title: folding it again lands on the new id
    return pages.has("~" + k) ? "~" + k : seen.get(k) || work.get(k) || cores.get(k) || "~" + k;  // an id some row's page really has stays; anything else is routed by the spelling it was written with
  };
  return { composerId, composerText: (p) => baseName(p.composer), rowsOf, workId: (p) => baseId({ p, cid: composerId(p), fold: pageFold(p.work) }), canon: (dim, id) => (dim === "composer" ? canonComposer(id) : dim === "work" ? canonWork(id) : nameFold(id)) };
}
// the entries one card belongs to in a dimension. conductors and soloists are the card's own lists (soloists = recital headliner + concerto soloist)
function entriesOf(it, dim, R) {
  const people = (names) => (names || []).map((n) => ({ id: nameFold(n), label: n })).filter((e) => e.id);
  if (dim === "conductor") return people(it.conductors);
  if (dim === "performer") return people(it.soloists);
  if (dim === "composer") return (it.pieces || []).filter((p) => isComposerName(p.composer)).map((p) => ({ id: R.composerId(p), label: R.composerText(p) })).filter((e) => e.id);
  if (dim === "work") return R.rowsOf(it).filter((r) => !r.tr).map((r) => ({ id: r.id, label: r.title, sub: r.text, cid: r.cid })).filter((e) => e.id);  // a translated line adds nothing: the piece is already listed through its Japanese line
  return [];
}
// every id the reviewed table might know this page by: the page's own, the one written in the address, and the LOCAL id of each programme row the app joined to this page
function classicalIds(dim, id, rawId, matched, R) {
  const out = new Set([id, rawId]);
  if (dim === "composer") for (const it of matched) for (const p of it.pieces || []) if (isComposerName(p.composer) && R.composerId(p) === id) out.add(localComposerId(p));
  if (dim === "work") for (const it of matched) for (const r of R.rowsOf(it)) if (r.id === id) out.add(localWorkId(r.p));
  return [...out].filter(Boolean);
}
const matchesEntity = (it, dim, id, R) => entriesOf(it, dim, R).some((e) => e.id === R.canon(dim, id));
const mostUsed = (counts) => [...counts].sort((a, b) => b[1] - a[1] || a[0].length - b[0].length || (a[0] < b[0] ? -1 : 1))[0][0];  // the spelling written most often; the shorter, then the smaller one on a tie
// [{id, label, sub, cid, n}] most concerts first; n counts DISTINCT concerts, so a piece listed twice in one programme is one
function buildIndex(items, dim, R) {
  const m = new Map();
  for (const it of items) for (const e of entriesOf(it, dim, R)) {
    let x = m.get(e.id);
    if (!x) m.set(e.id, x = { id: e.id, cid: e.cid || "", concerts: new Set(), labels: new Map(), subs: new Map() });
    x.concerts.add(it.concert_id);
    x.labels.set(e.label, (x.labels.get(e.label) || 0) + 1);
    if (e.sub) x.subs.set(e.sub, (x.subs.get(e.sub) || 0) + 1);
  }
  const shown = (t) => t.replace(MARKS, "").trim() || t;  // a mark a scraped line carries is no part of the name that is displayed
  return [...m.values()].map((x) => ({ id: x.id, cid: x.cid, label: shown(mostUsed(x.labels)), sub: x.subs.size ? shown(mostUsed(x.subs)) : "", n: x.concerts.size }))
    .sort((a, b) => b.n - a.n || a.label.localeCompare(b.label, "ja") || (a.id < b.id ? -1 : 1));
}
// what typing in the index box matches: the name, the composer under a piece, and the reviewed key (so "brahms" finds ブラームス)
const entryHay = (e, dim) => bfold([e.label, e.sub, dim === "work" ? e.cid : e.id.startsWith("~") ? "" : e.id].join(" "));
// </browse-rules>
const BROWSE_TITLE = { conductor: "指挥", performer: "演奏家", composer: "作曲家", work: "曲目" };
const BROWSE_UNIT = { conductor: "位指挥", performer: "位演奏家", composer: "位作曲家", work: "首曲目" };
const BROWSE_HINT = { conductor: "如 佐渡、小林", performer: "如 辻井、藤田", composer: "如 ブラームス、brahms", work: "如 第9番、beethoven" };
// built once per loaded list (loadAll returns the same array while it is cached)
const browseCache = new WeakMap();
function browseOf(items) {
  let b = browseCache.get(items);
  if (!b) browseCache.set(items, b = { R: makeResolver(items), idx: {} });
  return b;
}
const indexOf = (items, dim) => { const b = browseOf(items); return b.idx[dim] || (b.idx[dim] = buildIndex(items, dim, b.R)); };
const monthsSeg = () => h("div", { class: "segmented", role: "group", "aria-label": "时间范围" }, [12, 24].map((m) => h("button", { type: "button", "aria-pressed": String(state.months === m), onclick: () => { state.months = m; render(); } }, `${m} 个月`)));
const chevron = () => icon("chevron-right", { size: 18 });
// the top bar of a detail or browse page: a round back button and a round share button. The system share sheet when there is one, otherwise the address is copied
async function shareLink(title) {
  const url = location.href;
  if (navigator.share) {
    try { await navigator.share({ title, url }); return; } catch (e) { if (e && e.name === "AbortError") return; }  // the person closed the sheet: nothing to report; any other failure falls back to copying
  }
  try { await navigator.clipboard.writeText(url); toast("链接已复制"); } catch { toast("没能复制链接，请从地址栏复制"); }
}
const topBar = (title) => h("div", { class: "topbar" },
  h("button", { type: "button", class: "round", "aria-label": "返回", onclick: goBack }, icon("chevron-left", { size: 22 })),
  h("button", { type: "button", class: "round", "aria-label": "分享这一页", onclick: () => shareLink(title) }, icon("share", { size: 20 })));
const blockTitle = (text, ...more) => h("h2", { class: "block-title" }, text, ...more);
// the strip on the discover page: how many conductors, soloists, composers and pieces the loaded concerts have. It reads the list the page already waited for
function browseStrip(all) {
  return h("section", { class: "section" }, h("h2", { class: "section-title" }, "按人物与曲目浏览"),
    h("div", { class: "browse-grid" }, BROWSE_DIMS.map((dim) => h("a", { class: "browse-tile", href: browseHref(dim) }, h("span", { class: "n" }, String(indexOf(all, dim).length)), h("span", { class: "t" }, BROWSE_TITLE[dim])))));
}
const entryRow = (dim, e, withSub = true) => h("li", {}, h("a", { class: "entry", href: browseHref(dim, e.id), "data-cid": e.id },
  h("span", { class: "entry-main" }, h("span", { class: "entry-name", lang: "ja" }, e.label), withSub && e.sub ? h("span", { class: "entry-sub", lang: "ja" }, e.sub) : null),
  h("span", { class: "entry-n" }, `${e.n} 个节目`), chevron()));
async function viewBrowse(root, r) {
  const all = await loadAll(state.months, EMPTY_FLT()), dim = r.arg;
  return r.sub ? browseEntity(root, all, dim, r.sub) : browseIndex(root, all, dim);
}
function browseIndex(root, all, dim) {
  const entries = indexOf(all, dim), ui = state.browse;
  const input = h("input", { type: "search", class: "search-input", placeholder: BROWSE_HINT[dim], autocomplete: "off", enterkeyhint: "search", "aria-label": `搜索${BROWSE_TITLE[dim]}`, value: ui.q[dim] || "" });
  const list = h("div"), count = h("p", { class: "count", role: "status" }), more = h("button", { type: "button", class: "btn", hidden: true });
  const paint = () => {  // only the list changes while typing, so the caret stays where it is
    const t = bfold(ui.q[dim] || ""), hits = t ? entries.filter((e) => entryHay(e, dim).includes(t)) : entries, shown = hits.slice(0, Math.max(t ? 100 : 0, ui.shown[dim] || 60));
    count.textContent = t ? `${hits.length} 个匹配` : `共 ${entries.length} ${BROWSE_UNIT[dim]}`;
    list.replaceChildren(shown.length ? h("ul", { class: "row-list" }, shown.map((e) => entryRow(dim, e))) : h("p", { class: "empty" }, t ? `没有匹配“${ui.q[dim]}”的结果。可以试试日文写法。` : `这个时间范围内没有${BROWSE_TITLE[dim]}。可以切换到 24 个月。`));
    more.hidden = shown.length >= hits.length;
    more.textContent = `显示更多（还有 ${hits.length - shown.length}）`;
  };
  input.addEventListener("input", () => { ui.q[dim] = input.value; paint(); });
  more.addEventListener("click", () => { ui.shown[dim] = Math.max(60, ui.shown[dim] || 0) + 100; paint(); });
  // the chosen kind lives in the address (#browse/<kind>); replaceState like the orchestra chips, so "back" still leaves the browse pages in one step
  const go = (d) => { history.replaceState(history.state, "", browseHref(d)); render(); };
  paint();
  root.append(h("div", { class: "page" }, h("button", { type: "button", class: "back", onclick: goBack }, icon("chevron-left", { size: 20 }), "发现"),
    h("div", { class: "title-row" }, h("h1", { class: "page-title", tabindex: "-1" }, "浏览"), monthsSeg()),
    h("div", { class: "section" }, h("div", { class: "chip-row", role: "group", "aria-label": "浏览方式" }, BROWSE_DIMS.map((d) => h("button", { type: "button", class: "chip tokiwa", "aria-pressed": String(d === dim), onclick: () => go(d) }, BROWSE_TITLE[d])))),
    h("form", { class: "search-form", role: "search", onsubmit: (e) => e.preventDefault() }, input), count, list, more));
  return { title: `浏览 · ${BROWSE_TITLE[dim]}` };
}
// one concert as a card on a browse page: the days (and a sale tag), the title, the organiser, who plays what (everything except the thing the page is about), the venue.
// One link over the whole card; data-cid lets "back" land on the same card
function concertCard(it, dim) {
  const ps = sortedPerfs(it.performances), o = orgOf(it), tag = saleTag(it), venues = [...new Set(ps.map(venueText).filter(Boolean))];
  const orgs = (it.orchestras || []).map((x) => x.display).join("・") || (o ? o.name : "");
  const lines = [orgs];
  if (dim !== "conductor" && (it.conductors || []).length) lines.push("指挥 " + it.conductors.slice(0, 2).join("、"));
  if (dim !== "performer" && (it.soloists || []).length) lines.push("演奏 " + it.soloists.slice(0, 2).join("、"));
  if ((dim === "conductor" || dim === "performer") && (it.composers || []).length) lines.push("曲目 " + it.composers.slice(0, 3).join(" / "));
  if (venues.length) lines.push(venues[0] + (venues.length > 1 ? `　另 ${venues.length - 1} 个场馆` : ""));
  return h("li", {}, h("a", { class: "concert-card", href: "#concert/" + it.concert_id, "data-cid": it.concert_id },
    h("p", { class: "cc-when" }, tag, tag ? " " : null, whenText(it.performances)),
    h("h3", { class: "cc-title", lang: "ja" }, it.title_ja),
    ...lines.filter(Boolean).map((t) => h("p", { class: "cc-line", lang: "ja" }, t))));
}
const MUSIC_NOTE = { work: "在 Apple Music Classical 里打开这首曲子", composer: "在 Apple Music Classical 里打开这位作曲家", conductor: "在 Apple Music Classical 里打开这位指挥", performer: "在 Apple Music Classical 里打开这位演奏家" };
function browseEntity(root, all, dim, rawId) {
  const { R } = browseOf(all), id = R.canon(dim, rawId), matched = all.filter((it) => matchesEntity(it, dim, id, R)).sort(byDate);
  const ent = matched.length ? buildIndex(matched, dim, R).find((e) => e.id === id) : null;
  const name = ent ? ent.label : String(rawId).replace(/^~[^|]*\|/, "");
  // a missing table (classical-links.js did not load) just means no own page; a piece without one gets the search screen with its title (ADR-0019)
  const own = classicalHref(dim, classicalIds(dim, id, rawId, matched, R), window.CR_CLASSICAL), link = own ? { href: own } : null;
  const searchHref = dim === "work" && !link && ent ? classicalSearchHref([ent.sub, ent.label].filter(Boolean).join(" ")) : null;  // composer and title: a bare "交響曲第5番" would find every composer's
  const page = h("div", { class: "entity" }, topBar(name),
    h("div", { class: "entity-body" },
      h("header", { class: "entity-head" }, h("a", { class: "entity-kicker", href: browseHref(dim) }, `全部${BROWSE_TITLE[dim]}`), h("h1", { class: "entity-title", tabindex: "-1", lang: "ja" }, name)),
      dim === "work" && ent && ent.sub ? h("a", { class: "row-link by-row", href: browseHref("composer", ent.cid) }, h("span", { class: "row-text", lang: "ja" }, h("span", { class: "row-k" }, "作曲"), ent.sub), chevron()) : null));
  const body = page.querySelector(".entity-body");
  // this piece's or person's own page in Apple Music Classical, only when the reviewed table has its id; a piece without one: the search screen, title copied for pasting
  if (link) {
    body.append(h("section", { class: "block" }, blockTitle("找音源"),
      h("div", { class: "pills" }, h("a", { class: "pill-link", href: link.href, target: "_blank", rel: "noopener noreferrer" }, icon("external-link", { size: 16 }), "Apple Music Classical")),
      h("p", { class: "muted small" }, MUSIC_NOTE[dim])));
  } else if (searchHref) {
    body.append(h("section", { class: "block" }, blockTitle("找音源"),
      h("div", { class: "pills" }, h("a", { class: "pill-link via", href: searchHref, target: "_blank", rel: "noopener noreferrer" },
        icon("external-link", { size: 16 }), "Apple Music Classical", h("span", { class: "pill-tag" }, "搜索"))),
      h("p", { class: "muted small" }, "这首曲子在 Apple Music Classical 没有单独的页面。点按钮，用作曲家和曲名直接搜。")));
  }
  if (dim === "composer" && matched.length) {
    const pieces = buildIndex(matched, "work", R).filter((e) => e.cid === id), head = pieces.slice(0, 6), rest = pieces.slice(6);
    if (pieces.length) body.append(h("section", { class: "block" }, blockTitle("曲目", h("span", { class: "count-n" }, `　${pieces.length}`)),
      h("ul", { class: "row-list" }, head.map((e) => entryRow("work", e, false))),  // the composer is the page itself: not repeated under every piece
      rest.length ? h("details", { class: "more-details" }, h("summary", {}, `其余 ${rest.length} 首`), h("ul", { class: "row-list" }, rest.map((e) => entryRow("work", e, false)))) : null));
  }
  if (!matched.length) body.append(h("div", { class: "empty" }, h("span", {}, `${state.months} 个月内已收录的节目里没有这一项。`), state.months < 24 ? h("button", { type: "button", class: "button-secondary", onclick: () => { state.months = 24; render(); } }, "查看 24 个月") : null));
  else body.append(h("section", { class: "block" }, h("div", { class: "block-head" }, blockTitle("演出", h("span", { class: "count-n" }, `　${matched.length}`)), monthsSeg()),
    h("ul", { class: "cards" }, matched.map((it) => concertCard(it, dim))),
    h("p", { class: "meta-line" }, `未来 ${state.months} 个月内已收录的节目，含首都圈外。未收录不代表没有公演。`)));
  root.append(page);
  return { title: name };
}

const norm = (s) => String(s || "").normalize("NFKC").toLowerCase().replace(/[\s・=＝]/g, "");
const hay = new WeakMap();
function haystack(it) {
  if (!hay.has(it)) hay.set(it, norm([it.title_ja, ...(it.composers || []), ...(it.conductors || []), ...(it.soloists || []), ...(it.orchestras || []).flatMap((o) => [o.display, o.names]), ...(it.performances || []).map((p) => p.venue_name), (orgOf(it) || {}).name].filter(Boolean).join(" ")));
  return hay.get(it);
}
const SEARCH_KINDS = [[null, "全部"], ["presenter", "主办方公演"], ["piano", "钢琴独奏会"], ["orchestra", "东京乐团"], ["overseas", "海外乐团"]];
// One text box, one row of types. The seven orchestras appear as a second row only while "东京乐团" is on (several can be on at once; leaving that type clears them).
// An orchestra outside the seven is found by typing its name: the box also matches the Chinese / English names the data carries, so 柏林 or Berlin finds Berlin orchestras.
async function viewSearch(root) {
  const s = state.search, all = await loadAll(state.months, EMPTY_FLT());
  const results = h("div"), countEl = h("p", { class: "count", role: "status" });  // only the count is announced, not the whole list
  const input = h("input", { id: "q", type: "search", class: "search-input", placeholder: "作品、作曲家、演奏者、乐团、场馆", autocomplete: "off", enterkeyhint: "search", "aria-label": "搜索作品、作曲家、演奏者、乐团或场馆", value: s.q });
  // the buttons are built once and only their pressed state changes, so the focused one is never replaced
  const kindBtns = SEARCH_KINDS.map(([k, t]) => h("button", { type: "button", class: "chip", onclick: () => { s.kind = k; if (k !== "orchestra") s.orch.clear(); paint(); } }, t));
  const kinds = h("div", { class: "chip-row" }, h("div", { class: "chips-group", role: "group", "aria-label": "类别" }, kindBtns));
  const oc = orchFilterChips(s.orch, () => paint(), { small: true });
  const orchRow = h("div", { class: "chip-row sub-row", role: "group", "aria-label": "按乐团筛选（可多选）" }, h("span", { class: "sub-label", "aria-hidden": "true" }, "乐团"), ...oc.kids);
  const paint = () => {
    kindBtns.forEach((b, i) => b.setAttribute("aria-pressed", String(s.kind === SEARCH_KINDS[i][0])));
    orchRow.hidden = s.kind !== "orchestra";
    oc.paint();
    const terms = s.q.split(/\s+/).map(norm).filter(Boolean);
    const kindOk = (it) => !s.kind || (s.kind === "overseas" ? it.category === "overseas_orchestra_visit" : coverKind(it) === s.kind);
    const hits = all.filter(kindOk).filter((it) => orchMatch(it.orchestras, s.orch)).filter((it) => terms.every((t) => haystack(it).includes(t))).sort(byDate);
    countEl.textContent = `${terms.length || s.kind ? hits.length : "全部 " + hits.length} 个节目，含首都圈外`;
    results.replaceChildren(...[hits.length ? h("ul", { class: "row-list" }, hits.slice(0, 200).map((it) => rowItem(it))) : h("p", { class: "empty" }, s.q ? `没有匹配“${s.q}”的节目。试试日文写法，例如 ブラームス、サントリー；或少写一个词。` : "没有符合条件的节目。"),
      hits.length > 200 ? h("p", { class: "meta-line" }, `只显示前 200 个，请缩小范围`) : null].filter(Boolean));
  };
  input.addEventListener("input", () => { s.q = input.value; paint(); });
  paint();
  const page = h("div", { class: "page" }, h("h1", { class: "page-title", tabindex: "-1" }, "搜索"),
    h("form", { class: "search-form", role: "search", onsubmit: (e) => e.preventDefault() }, h("label", { for: "q", class: "visually-hidden" }, "搜索"), input), kinds, orchRow);
  page.append(countEl, results, h("p", { class: "meta-line" }, stamp() ? h("span", {}, stamp()) : null, h("a", { href: "#sources" }, "数据来源与采集状态")));
  root.append(page);
}

// <cal-nav>
// The calendar's month moves. Pure, so tests/js/calnav.test.mjs runs them under node (the block must stay free of DOM and globals).
// the 1st of the month n months away from `from` (a Date on the 1st, UTC): December + 1 is January of the next year, January - 1 is December of the last
const stepMonth = (from, n) => new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth() + n, 1));
// a finger that moved (dx, dy) pixels in ms milliseconds: 1 = next month (swiped left), -1 = previous month (swiped right), 0 = not a month swipe (short, mostly vertical = a scroll, or slow = a drag)
const swipeDir = (dx, dy, ms) => (Math.abs(dx) >= 48 && Math.abs(dx) >= 1.5 * Math.abs(dy) && ms <= 600 ? (dx < 0 ? 1 : -1) : 0);
// a touch that starts this close to the left or right edge of the screen belongs to the browser's own back / forward swipe
const inEdge = (x, width) => x < 20 || x > width - 20;
// </cal-nav>
async function viewCalendar(root) {
  const [ty, tm] = today().split("-").map(Number);
  if (!state.calMonth) state.calMonth = new Date(Date.UTC(ty, tm - 1, 1));
  const m = state.calMonth, y = m.getUTCFullYear(), mo = m.getUTCMonth(), monthKey = `${y}-${pad(mo + 1)}`, todayKey = today();
  const dir = state.calDir, focusTitle = state.calFocusTitle;  // this render's slide direction and focus request: read before the first await, spent right away so no other render replays them
  state.calDir = 0; state.calFocusTitle = false;
  const first = new Date(Date.UTC(y, mo, 1)), last = new Date(Date.UTC(y, mo + 1, 0));
  const [cal, pk] = await Promise.all([api(`/calendar?from=${ymd(first)}&to=${ymd(last)}`), api("/me/pickups")]);
  if (state.calMonth !== m) return;  // a quicker tap already asked for another month: this answer is stale (render() drops it too)
  const picked = new Set(pk.items.map((x) => x.concert_id));
  if (!state.calDay || state.calDay.slice(0, 7) !== monthKey) state.calDay = todayKey.slice(0, 7) === monthKey ? todayKey : `${monthKey}-01`;
  const group = (arr) => { const mp = new Map(); for (const e of arr) { if (!mp.has(e.local_date)) mp.set(e.local_date, []); mp.get(e.local_date).push(e); } return mp; };
  onlySeven(state.calOrch);  // a stale key can never leave the calendar empty with no chip lit
  const keep = (e) => orchMatch(e.orchestras, state.calOrch), filtering = state.calOrch.size > 0;  // one rule feeds the counts under the dates, the day list and the announcement
  const shows = group(cal.performances.filter(keep)), sales = group(cal.sales.filter(keep));
  const goMonth = (target, d) => { state.calMonth = target; state.calDay = null; state.calPick = false; state.calDir = d; render(); };
  const step = (n) => goMonth(stepMonth(state.calMonth, n), n);  // from the month the page is on NOW, not the one this render drew: quick taps and swipes add up instead of repeating one step
  const cells = new Map(), dayBox = h("section", { class: "day-list" }), live = h("p", { class: "visually-hidden", role: "status" });  // announce the chosen day, not the whole list
  const eventsOn = (key) => (state.calMode === "show" ? shows : sales).get(key) || [];
  const tile = (e, text) => h("span", { class: `tile kind-${coverKind(e)}` + (text === "––:––" ? " blank" : "") }, text);
  const paintDay = () => {
    for (const [key, btn] of cells) btn.setAttribute("aria-pressed", String(state.calDay === key));
    const list = eventsOn(state.calDay), unit = state.calMode === "show" ? "场" : "个开票节点";
    live.textContent = `${dayText(state.calDay)}，${list.length ? list.length + " " + unit : "无"}`;
    dayBox.replaceChildren(h("h2", { class: "section-title" }, dayText(state.calDay), list.length ? h("span", { class: "count-n" }, `　${list.length} ${unit}`) : null),
      list.length ? h("ul", { class: "row-list" }, list.map((e) => {
        const isShow = state.calMode === "show";
        const text = isShow ? (e.starts_at && e.date_precision !== "date_only" ? fmt.hm(e.starts_at) : "––:––") : (e.local_time || "全天");
        const meta = isShow ? (venueText(e) || "场馆未公布") : (eligText(e, null) || (e.local_time ? "" : "仅日期，无精确时刻"));
        return h("li", {}, h("a", { class: "day-item", href: "#concert/" + e.concert_id, "data-cid": e.concert_id }, tile(e, text),
          h("span", { class: "day-body" }, isShow ? null : h("span", { class: "sale-tag" }, L.phase[e.phase_type] || e.phase_type), h("span", { class: "day-title", lang: "ja" }, e.title_ja), meta ? h("span", { class: "day-meta", lang: "ja" }, meta) : null)));
      })) : h("p", { class: "empty" }, filtering ? (state.calMode === "show" ? "这一天没有所选乐团的演出。" : "这一天没有所选乐团的开票节点。") : state.calMode === "show" ? "这一天没有收录演出。" : "这一天没有开票节点。"));
  };
  const grid = h("div", { class: "grid" }, Array(first.getUTCDay()).fill(0).map(() => h("span", { "aria-hidden": "true" })));
  for (let d = 1; d <= last.getUTCDate(); d++) {
    const key = `${monthKey}-${pad(d)}`, list = eventsOn(key);
    const isShow = state.calMode === "show", hasPick = isShow && list.some((e) => picked.has(e.concert_id));
    // under the date: how many that day, in words ("3场"); blue and bold when one of them is in the user's Pickup list. Nothing on an empty day.
    const btn = h("button", { type: "button", class: "cell" + (key < todayKey ? " past" : ""), "aria-pressed": "false", "aria-label": `${dayText(key)}，${list.length ? list.length + (isShow ? " 场演出" : " 个开票节点") + (hasPick ? "，含 Pickup" : "") : "无"}`,
      onclick: () => { state.calDay = key; paintDay(); } }, h("span", { class: "n" + (key === todayKey ? " today" : "") }, String(d)), h("span", { class: "c" + (hasPick ? " picked" : ""), "aria-hidden": "true" }, list.length ? `${list.length}${isShow ? "场" : "项"}` : ""));
    cells.set(key, btn); grid.append(btn);
  }
  // the month name is a button: it opens a picker (a year stepper and the twelve months), so any month is one tap away instead of a row of arrow taps
  const titleBtn = h("button", { type: "button", class: "month-btn", "aria-expanded": String(state.calPick), "aria-controls": "month-picker", onclick: () => setPick(!state.calPick) },
    h("span", { class: "m" }, `${mo + 1}月`), h("span", { class: "y" }, String(y)), icon("chevron-down", { size: 20 }), h("span", { class: "visually-hidden" }, "，点此选择月份"));
  const yearLabel = h("strong", { class: "mp-year-n", "aria-live": "polite" }), monthsBox = h("div", { class: "mp-grid" });
  const yearStep = (n, label) => h("button", { type: "button", class: "ib", "aria-label": label, onclick: () => { state.calPickYear += n; paintPicker(); } }, icon(n < 0 ? "chevron-left" : "chevron-right", { size: 20 }));
  const picker = h("section", { class: "month-picker", id: "month-picker", "aria-label": "选择月份", hidden: !state.calPick }, h("div", { class: "mp-year" }, yearStep(-1, "上一年"), yearLabel, yearStep(1, "下一年")), monthsBox);
  const paintPicker = () => {
    const Y = state.calPickYear;
    yearLabel.textContent = `${Y}年`;
    monthsBox.replaceChildren(...Array.from({ length: 12 }, (_, i) => h("button", { type: "button", "aria-pressed": String(Y === y && i === mo), "aria-current": Y === ty && i === tm - 1 ? "date" : false,
      onclick: () => { const target = new Date(Date.UTC(Y, i, 1)); if (target.getTime() === state.calMonth.getTime()) { setPick(false, true); return; } state.calFocusTitle = true; goMonth(target, target > state.calMonth ? 1 : -1); } }, `${i + 1}月`)));
  };
  const setPick = (open, refocus = false) => {
    state.calPick = open; picker.hidden = !open; titleBtn.setAttribute("aria-expanded", String(open));
    if (open) { state.calPickYear = y; paintPicker(); const cur = monthsBox.querySelector('[aria-pressed="true"]'); if (cur) cur.focus({ preventScroll: true }); } else if (refocus) titleBtn.focus({ preventScroll: true });
  };
  const closeOnEsc = (e) => { if (e.key === "Escape" && state.calPick) setPick(false, true); };
  picker.addEventListener("keydown", closeOnEsc); titleBtn.addEventListener("keydown", closeOnEsc);
  if (state.calPick) { if (state.calPickYear == null) state.calPickYear = y; paintPicker(); }
  // "今天" sits beside the show / sale switch; greyed out (not removed, so nothing jumps) while the current month is already shown
  const todayBtn = h("button", { type: "button", class: "cal-today", disabled: y === ty && mo === tm - 1, onclick: () => { const t = new Date(Date.UTC(ty, tm - 1, 1)); goMonth(t, t > state.calMonth ? 1 : -1); } }, "今天");
  const modeBtn = (mode, label, key) => h("button", { type: "button", "aria-pressed": String(state.calMode === mode), onclick: () => { state.calMode = mode; render(); } }, key, label);
  const wrap = h("section", { class: "grid-wrap" + (dir ? (dir > 0 ? " slide-next" : " slide-prev") : ""), "aria-label": `${y}年${mo + 1}月` },
    h("div", { class: "weekdays", "aria-hidden": "true" }, ["日", "一", "二", "三", "四", "五", "六"].map((d) => h("span", {}, d))), grid);
  // swipe the grid sideways to change month: one finger, not from the screen edge (that is the browser's back swipe), not while pinch-zoomed in
  let t0 = null;
  wrap.addEventListener("touchstart", (e) => {
    const t = e.touches[0], zoomed = window.visualViewport && window.visualViewport.scale > 1.01;
    t0 = e.touches.length === 1 && !zoomed && !inEdge(t.clientX, window.innerWidth) ? { x: t.clientX, y: t.clientY, at: Date.now() } : null;
  }, { passive: true });
  wrap.addEventListener("touchmove", (e) => { if (e.touches.length > 1) t0 = null; }, { passive: true });
  wrap.addEventListener("touchcancel", () => { t0 = null; }, { passive: true });
  wrap.addEventListener("touchend", (e) => { const s = t0; t0 = null; if (!s) return; const t = e.changedTouches[0], d = swipeDir(t.clientX - s.x, t.clientY - s.y, Date.now() - s.at); if (d) step(d); }, { passive: true });
  const touchScreen = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  root.append(h("div", { class: "page" },
    h("header", { class: "cal-head" },
      h("div", { class: "cal-title" }, h("h1", { class: "month", tabindex: "-1" }, titleBtn),
        h("div", { class: "cal-nav" }, h("button", { type: "button", class: "ib", "aria-label": "上个月", onclick: () => step(-1) }, icon("chevron-left", { size: 20 })), h("button", { type: "button", class: "ib", "aria-label": "下个月", onclick: () => step(1) }, icon("chevron-right", { size: 20 })))),
      picker,
      h("div", { class: "mode-row" }, h("div", { class: "mode", role: "group", "aria-label": "日历显示" }, modeBtn("show", "演出日"), modeBtn("sale", "开票日", h("span", { class: "sale-key", "aria-hidden": "true" }))), todayBtn),
      h("div", { class: "chip-row", role: "group", "aria-label": "按乐团筛选（可多选）" }, ...orchFilterChips(state.calOrch, render).kids)),
    wrap, live, dayBox,
    h("div", { class: "legend" }, h("span", {}, state.calMode === "show" ? "日期下面的小字 = 当天演出场数" : "日期下面的小字 = 当天开票节点数"),
      state.calMode === "show" ? h("span", { class: "picked" }, "蓝色 = 含你 Pickup 的演出") : null, touchScreen ? h("span", {}, "左右滑动日历 = 换月") : null)));
  paintDay();
  if (focusTitle) setTimeout(() => { const b = document.querySelector(".month-btn"); if (b) b.focus({ preventScroll: true }); }, 0);  // after a month was picked: back to the month name (render() has put the page in place by then)
}

async function viewMine(root) {
  const [pk, pl] = await Promise.all([api("/me/pickups"), api("/me/plans")]), t = today();
  const page = h("div", { class: "page" }, h("h1", { class: "page-title", tabindex: "-1" }, "Pickup"));
  if (!pk.items.length && !pl.items.length) { page.append(h("div", { class: "empty" }, h("span", {}, "还没有关注或预定的节目。在节目页点“加入 Pickup”（想看，也会标在日历上）或“预定前往”（打算去），它们会出现在这里。"), h("a", { class: "button-secondary", href: "#discover" }, "去发现"))); root.append(page); return; }
  page.append(h("p", { class: "lede muted" }, "Pickup 是想看的节目，预定前往是打算去的节目；想去、已购票、已看过按场次标记。"));
  const upcoming = (it) => it.performances.some((p) => p.local_date >= t);
  const rows = (items) => h("ul", { class: "row-list" }, items.map((it) => {
    const marks = [it.priority === "high" ? "重点" : null, ...it.performances.filter((p) => p.user_status).map((p) => `${fmt.ymd(p.local_date)} ${L.user[p.user_status]}`)].filter(Boolean);
    return rowItem(it, marks.length ? h("p", { class: "marks" }, marks.join("　")) : null);
  }));
  const block = (title, items) => items.length ? h("section", { class: "section" }, h("h2", { class: "section-title" }, title, h("span", { class: "count-n" }, `　${items.length}`)), rows(items)) : null;
  const plans = pl.items.filter(upcoming).sort(byDate), picks = pk.items.filter(upcoming);
  // the ended ones of both lists together, a concert in both only once; the pickup row goes first because it carries the 重点 mark
  const ended = [...pk.items, ...pl.items].filter((it) => !upcoming(it)).filter((it, i, all) => all.findIndex((x) => x.concert_id === it.concert_id) === i);
  page.append(...[block("预定前往", plans), block("Pickup", picks)].filter(Boolean));
  if (!plans.length && !picks.length) page.append(h("p", { class: "muted" }, "接下来没有预定或关注的节目。"));  // before the ended block, where the upcoming ones would be
  page.append(...[block("已结束", ended)].filter(Boolean));
  root.append(page);
}

// ---------- concert detail: a page of its own (#concert/<id>), so the browser's back button works and a link can be shared ----------
const ROLE_ORDER = ["conductor", "recital_headliner", "concerto_soloist", "other"];
const MAIN_STATES = ["interested", "purchased", "attended"];
// "now" follows the data: the static demo is pinned to its snapshot time, everything else uses the real clock
const nowMs = () => (DEMO && DEMO.mode === "demo" && DEMO.asOf ? Date.parse(DEMO.asOf) : Date.now());
const jstDay = (ms) => Math.floor((ms + 9 * 3600e3) / 864e5);
function untilStart(t) {
  if (!t.starts_at) return null;
  const at = Date.parse(t.starts_at), now = nowMs(), days = jstDay(at) - jstDay(now);
  if (days > 0) return { past: false, text: `还有 ${days} 天` };
  if (days === 0 && (t.start_precision !== "exact_time" || at > now)) return { past: false, text: "今天" };
  return { past: true, text: "已开始" };
}
async function viewDetail(root, r) {
  const id = r.arg, d = await api(`/concerts/${id}`);
  const c = d.concert, perfs = d.performances || [], artists = d.concert_artists || [], program = d.program_items || [];
  const card = { title_ja: c.title_ja, category: c.category, organization_id: c.organization_id || null,
    conductors: artists.filter((a) => a.role === "conductor").map((a) => a.name_display), soloists: artists.filter((a) => a.role === "recital_headliner" || a.role === "concerto_soloist").map((a) => a.name_display) };
  const kind = coverKind(card), when = perfs.filter((p) => p.date_precision === "exact_time" || p.date_precision === "date_only"), srcUrl = safeHref(d.source_url), org = orgOf(card);
  let picked = !!d.user_pickup, planned = !!d.user_plan;
  const pb = h("button", { type: "button", class: "button-primary grow" });
  const paintPick = () => { pb.setAttribute("aria-pressed", String(picked)); pb.replaceChildren(icon("bookmark", { size: 20, fill: picked }), picked ? "已加入 Pickup" : "加入 Pickup"); };
  pb.addEventListener("click", guard(async () => {
    if (!picked) await api(`/me/pickups/${id}`, { method: "PUT", body: JSON.stringify({ priority: "normal" }) }); else await api(`/me/pickups/${id}`, { method: "DELETE" });
    picked = !picked; paintPick();
  }));
  paintPick();
  // 预定前往: "I intend to go" for the whole concert, saved like a Pickup and listed on the Pickup tab. The per-date chips below (想去 / 已购票 / 已观演) record tickets and attendance of each date
  const plb = h("button", { type: "button", class: "button-secondary button-plan grow" });
  const paintPlan = () => { plb.setAttribute("aria-pressed", String(planned)); plb.replaceChildren(icon("check", { size: 20 }), planned ? "已预定前往" : "预定前往"); };
  plb.addEventListener("click", guard(async () => {
    if (!planned) await api(`/me/plans/${id}`, { method: "PUT" }); else await api(`/me/plans/${id}`, { method: "DELETE" });
    planned = !planned; paintPlan();
  }));
  paintPlan();
  // the type chip, the title, and the organiser. An orchestra opens its own list; any other organiser is only named, because there is no page of one presenter's concerts
  const body = h("div", { class: "detail-body" },
    h("header", { class: "intro" }, h("span", { class: "cat-chip" }, c.category === "overseas_orchestra_visit" ? "海外乐团来日" : LIST_TITLE[kind]),
      h("h1", { class: "detail-title", id: "detail-title", tabindex: "-1", lang: "ja" }, c.title_ja), h("p", { class: "detail-when" }, when.length ? whenText(when) : "日期未定"),
      org && org.orch ? h("a", { class: "row-link org-row", href: "#list/orchestra/" + card.organization_id }, h("span", { class: "row-text", lang: "ja" }, org.name), chevron())
        : org ? h("p", { class: "org-line", lang: "ja" }, org.name) : null));
  if (c.last_material_change_at) body.append(h("p", { class: "notice" }, icon("alert", { size: 18 }), h("span", {}, "近期有重要变更 " + fmt.ts(c.last_material_change_at))));
  if (d.merged_into) body.append(h("p", { class: "notice" }, icon("alert", { size: 18 }), h("span", {}, "这场和 ", h("a", { href: "#concert/" + d.merged_into.concert_id }, srcName(d.merged_into.source_id) + " 的卡片"), " 是同一场，列表里只显示那一张。这里的售票信息来自本页来源。")));
  if (program.length) body.append(programBlock(program));
  if (artists.length) body.append(artistsBlock(artists));
  body.append(h("section", { class: "block" }, blockTitle("日程"), h("ol", { class: "perfs" }, perfs.map((p) => perfItem(p)))),
    h("div", { class: "action-block" }, h("div", { class: "actions" }, pb, plb),
      srcUrl ? h("a", { class: "row-link site-row", href: srcUrl, target: "_blank", rel: "noopener noreferrer" }, h("span", { class: "row-text" }, "官网"), icon("external-link", { size: 18 })) : null));
  body.append(salesSection(perfs));
  const src = srcUrl ? new URL(srcUrl, location.href).hostname : "";
  body.append(h("dl", { class: "facts" },
    h("div", {}, h("dt", {}, c.official_announcement_date ? "官方公布" : "首次收录"), h("dd", {}, c.official_announcement_date ? fmt.ymd(c.official_announcement_date) : (fmt.ts(c.first_verified_at) || "未知"))),
    c.last_material_change_at ? h("div", {}, h("dt", {}, "最近变更"), h("dd", {}, fmt.ts(c.last_material_change_at))) : null,
    srcUrl ? h("div", {}, h("dt", {}, "来源"), h("dd", {}, h("a", { href: srcUrl, target: "_blank", rel: "noopener noreferrer" }, src))) : null,
    (d.other_sources || []).length ? h("div", {}, h("dt", {}, "其他来源"), h("dd", {}, d.other_sources.flatMap((s, i) => [i ? "、" : null, h("a", { href: "#concert/" + s.concert_id }, srcName(s.source_id))]))) : null));
  root.append(h("article", { class: "detail", "aria-labelledby": "detail-title" }, topBar(c.title_ja), body));
  return { title: c.title_ja };
}
// one performance as a card: the day and the time on one line, the venue under it, then my status
function perfItem(p) {
  const prec = p.date_precision, { y, m, wd } = fmt.parts(p), pref = fmt.pref(p.prefecture_code), venue = venueText(p);
  const date = prec === "unknown" ? "日期待定" : prec === "month_only" ? `${y === curYear() ? "" : y + "年"}${m}月` : `${fmt.ymd(p.local_date)} ${wd}`;
  const time = prec === "exact_time" && p.starts_at ? [fmt.hm(p.starts_at), " 开演"] : prec === "date_only" ? [h("span", { class: "blank", title: "时刻未公布" }, "––:––"), h("span", { class: "muted small" }, "　时间未公布")] : prec === "unknown" ? null : [L.precision[prec] || "时间未公布"];
  return h("li", { class: "perf" + (p.local_date < today() ? " past" : "") },
    h("p", { class: "perf-when" }, date, time ? h("span", { class: "perf-time" }, "　", time) : null),
    h("p", { class: "perf-venue", lang: "ja" }, [venue || "场馆未公布", pref].filter(Boolean).join(" · ")),
    p.status !== "scheduled" ? h("p", {}, h("span", { class: "tag warn" }, L.pstatus[p.status] || p.status)) : null, stateRow(p));
}
// my status of one performance: three chips (想去 / 已购票 / 已观演). It can be switched but the API has no way to clear it. The API still accepts the four older states (计划购票 / 已申请 / 已中签 / 放弃)
// so anything already saved keeps reading back (the Pickup tab still shows it); the page just no longer offers them
function stateRow(p) {
  let shown = (p.user_state && p.user_state.status) || "";
  const chips = MAIN_STATES.map((v) => h("button", { type: "button", class: "chip small", "aria-pressed": "false", onclick: () => choose(v) }, L.user[v]));
  const paint = () => chips.forEach((b, i) => b.setAttribute("aria-pressed", String(shown === MAIN_STATES[i])));
  const choose = guard(async (v) => {
    if (v === shown) return;
    await api(`/me/performances/${p.id}/state`, { method: "PUT", body: JSON.stringify({ status: v }) });
    shown = v; paint(); toast("已保存");
  });
  paint();
  return h("div", { class: "status", role: "group", "aria-label": "我的状态" }, chips);
}
function salesSection(perfs) {
  const withPhases = perfs.filter((p) => (p.ticket_phases || []).length);
  // reminders are only RECORDED today (the fake sender writes a local file; the hosted site only stores the choice): say so next to the buttons
  const anyRemind = withPhases.some((p) => p.ticket_phases.some((t) => t.start_precision === "exact_time" && t.starts_at && !(untilStart(t) || {}).past));
  const head = h("div", {}, h("h2", { class: "block-title" }, "售票"), h("p", { class: "muted small" }, "余票以官网为准"),
    anyRemind ? h("p", { class: "muted small remind-note" }, "提醒目前只做记录，到点不会发通知。") : null);
  if (!withPhases.length) return h("section", { class: "block" }, head, h("p", { class: "muted" }, "还没有收录售票信息，请在官网确认。"));
  return h("section", { class: "block sales" }, head, withPhases.map((p) => {
    const phases = [...p.ticket_phases].sort((a, b) => (Date.parse(a.starts_at) || Infinity) - (Date.parse(b.starts_at) || Infinity));
    const until = phases.map(untilStart), next = until.findIndex((u) => u && !u.past), q = fmt.parts(p);
    return h("div", {}, perfs.length > 1 ? h("h3", { class: "small muted" }, `${q.m}/${q.d} 场`) : null, h("ol", { class: "timeline" }, phases.map((t, i) => phaseRow(t, until[i], i === next))));
  }));
}
// ticket-class labels are scraped and sometimes repeat the sale date the row already shows: drop only a date that equals the row's own
function eligText(t, j) {
  const s = String(t.eligibility || "").replace(/(\d{4})年(\d{1,2})月(\d{1,2})日\s*(?:[（(][^）)]*[）)])?\s*(?:\d{1,2}:\d{2})?/g,
    (m, y, mo, d) => (j && +y === j.y && +mo === j.m && +d === j.d ? "" : m)).replace(/^[\s：:]+|[\s：:]+$/g, "").replace(/^[[［]([^\]］]+)[\]］]$/, "$1");
  return s && !/^一般(発売|販売|发售)?$/.test(s) ? s : null;
}
function phaseRow(t, until, isNext) {
  const exact = t.start_precision === "exact_time" && !!t.starts_at, j = t.starts_at ? jst(t.starts_at) : null;
  const at = j ? (exact ? [fmt.day(t.starts_at), " ", h("span", { class: "num" }, `${fmt.hm(t.starts_at)} JST`)] : [fmt.day(t.starts_at), h("span", { class: "dim" }, "（仅日期）")]) : "开售时间未公布";
  // a stored open/closed state wins over the clock; otherwise show how far away the start is
  const live = t.current_status === "open" ? ["发售中", "ok"] : t.current_status === "closed" ? ["已结束", ""] : until ? [until.text, isNext ? "next" : ""] : null;
  const elig = eligText(t, j);
  return h("li", { class: "step" + (isNext ? " next" : until && until.past ? " past" : "") },
    h("span", { class: "pin", "aria-hidden": "true" }),
    h("div", { class: "col" },
      h("div", { class: "head-line" }, h("span", { class: t.phase_type === "general_sale" ? "sale-tag" : "tag" }, L.phase[t.phase_type] || t.phase_type), live ? h("span", { class: "live " + live[1] }, live[0]) : null),
      h("p", { class: "at" }, at),
      elig ? h("p", { class: "elig", lang: "ja" }, elig) : null,
      remindControl(t, exact, until)));
}
function remindControl(t, exact, until) {
  if (!t.starts_at || (until && until.past)) return null;
  if (!exact) return h("button", { type: "button", class: "remind", disabled: true }, "无精确时刻");
  let on = !!(t.reminder && t.reminder.enabled);
  const b = h("button", { type: "button", class: "remind", title: "记下一条开售前 1 小时的提醒；目前不会发送通知" });
  const paint = () => { b.setAttribute("aria-pressed", String(on)); b.replaceChildren(icon(on ? "bell-ring" : "bell", { size: 16 }), on ? "已记下提醒（暂不发送）" : "记下提醒"); };
  b.addEventListener("click", guard(async () => {
    const want = !on;
    await api(`/me/reminders/${t.id}`, { method: "PUT", body: JSON.stringify({ milestone: "sale_start", offset_minutes: 60, enabled: want }) });
    on = want; paint();
    toast(want ? "已记下。提醒目前不会发送通知" : "已取消这条提醒记录");
  }));
  paint();
  return b;
}
// a conductor and a soloist open their own browse page; role "other" (orchestras, choruses, stray names) stays plain text
function artistsBlock(list) {
  const known = new Set(ROLE_ORDER), roleOf = (a) => (known.has(a.role) ? a.role : "other");
  const rows = ROLE_ORDER.flatMap((r) => list.filter((a) => roleOf(a) === r)).map((a) => {
    const href = personHref(a.role, a.name_display), kids = [a.image ? h("img", { class: "avatar", src: a.image.src, alt: "", loading: "lazy" }) : null,
      h("span", { class: "row-text" }, h("span", { class: "row-k" }, L.role[roleOf(a)]), h("span", { lang: "ja" }, a.name_display))];
    return h("li", {}, href ? h("a", { class: "row-link", href }, ...kids, chevron()) : h("div", { class: "row-link plain" }, ...kids));
  });
  return h("section", { class: "block" }, blockTitle("出演"), h("ul", { class: "rows" }, rows), list.filter((a) => a.image).map((a) => credit(a.image)));
}
// one row per piece, "composer / title"; the row opens the piece's browse page (which names the composer and links to theirs). The same junk check as the index
// decides, so a link always lands on a page that lists it; a row with no piece page falls back to the composer's page, else it is plain text
function programBlock(items) {
  const rows = items.map((it) => {
    const piece = programPiece(it), comp = it.composer_display || "", name = it.work_display || it.raw_text || "", href = workHref(piece) || composerHref(piece);
    const text = h("span", { class: "row-text", lang: "ja" }, comp ? [h("span", { class: "row-lead" }, comp), h("span", { class: "row-sep" }, " / ")] : null, name);
    return h("li", {}, href ? h("a", { class: "row-link", href }, text, chevron()) : h("div", { class: "row-link plain" }, text));
  });
  return h("section", { class: "block" }, blockTitle("曲目"), h("ul", { class: "rows" }, rows));
}

// ---------- review and import (the local app only) ----------
function summaryLine(it) {
  const bits = [];
  if (it.orchestras && it.orchestras.length) bits.push(it.orchestras.map((o) => o.display).join("・"));
  if (it.conductors && it.conductors.length) bits.push("指挥 " + it.conductors.join("、"));
  if (it.soloists && it.soloists.length) bits.push(it.soloists.slice(0, 3).join("、"));
  if (it.composers && it.composers.length) bits.push(it.composers.join(" / "));
  return bits.length ? h("div", { class: "small muted", lang: "ja" }, bits.join(" · ")) : null;
}
const perfRow = (p, extra) => h("div", { class: "perfrow" }, h("span", { class: "num" }, `${fmt.ymd(p.local_date)} ${fmt.parts(p).wd} ${clock(p) || "––:––"}`), h("span", { lang: "ja" }, [fmt.pref(p.prefecture_code), p.venue_name].filter(Boolean).join(" · ")), extra || null);
const DUP_WHY = { same_day: "同一天", venue_exact: "场馆相同", venue_prefix: "场馆名相近", title_contains: "标题互相包含" };
const dupWhy = (d) => d.reasons.filter((r) => DUP_WHY[r]).map((r) => DUP_WHY[r]).concat(d.shared_artists.length ? [`共同艺人 ${d.shared_artists.join("、")}`] : []).join(" · ");
const decideDup = (concertId, otherId, decision, msg) => guard(async () => {
  await api("/review/duplicates", { method: "PUT", body: JSON.stringify({ concert_id: concertId, other_concert_id: otherId, decision }) });
  toast(msg); render();
});
const dupBlock = (it) => (it.possible_duplicates || []).map((d) => h("div", { class: "dup" },
  h("div", { class: "small" }, h("span", { class: "tag warn" }, d.strength === "strong" ? "很可能重复" : "可能重复"), " ",
    h("a", { href: safeHref(d.source_url), target: "_blank", rel: "noopener noreferrer", lang: "ja" }, d.title_ja), `（${srcName(d.source_id)}${d.verification_status === "official_confirmed" ? "，已确认" : ""}）`),
  h("div", { class: "small muted" }, dupWhy(d)),
  h("div", { class: "row" },
    h("button", { type: "button", class: "btn", onclick: decideDup(it.concert_id, d.concert_id, "duplicate_of", "已标为重复，页面底部可撤销") }, "同一场，隐藏这条"),
    h("button", { type: "button", class: "btn", onclick: decideDup(it.concert_id, d.concert_id, "different", "已标为不同场") }, "不是同一场"))));
const markedBlock = (list) => !list || !list.length ? null : h("details", { class: "marked" }, h("summary", {}, `已标为重复 ${list.length}`),
  list.map((m) => h("div", { class: "dup-row" },
    h("div", { class: "small" }, h("a", { href: safeHref(m.source_url), target: "_blank", rel: "noopener noreferrer", lang: "ja" }, m.title_ja), `（${srcName(m.source_id)}）是 `,
      h("a", { href: safeHref(m.duplicate_of.source_url), target: "_blank", rel: "noopener noreferrer", lang: "ja" }, m.duplicate_of.title_ja), `（${srcName(m.duplicate_of.source_id)}）的重复`, m.active === false ? "（暂未生效：主卡缺少它的某一场）" : ""),
    h("button", { type: "button", class: "btn", onclick: guard(async () => { await api(`/review/duplicates/${encodeURIComponent(m.concert_id)}/${encodeURIComponent(m.duplicate_of.concert_id)}`, { method: "DELETE" }); toast("已撤销"); render(); }) }, "撤销"))));
// two cards that are BOTH already confirmed and look like the same concert: the reviewer picks the main card (suggested one first)
const confirmedBlock = (list) => !list || !list.length ? null : h("section", { class: "merge" }, h("h2", { class: "section-title" }, `已确认、可能是同一场 ${list.length}`),
  h("div", { class: "muted small" }, "这些节目两个来源都已确认，发现页现在各显示一张。选定主卡后列表只显示主卡，另一张仍可从主卡的“其他来源”打开；可随时撤销。"),
  list.map((p) => {
    const sides = p.suggested_keeper_id === p.b.concert_id ? [p.b, p.a] : [p.a, p.b];
    const keepBtn = (keep, hide) => !p.can_hide[hide.concert_id] ? null : h("button", { type: "button", class: "btn" + (p.suggested_keeper_id === keep.concert_id ? " primary" : ""),
      onclick: decideDup(hide.concert_id, keep.concert_id, "duplicate_of", "已合并，页面底部可撤销") }, `同一场，以${srcName(keep.source_id)}为主卡`);
    return h("div", { class: "dup" },
      h("div", { class: "small" }, h("span", { class: "tag warn" }, p.strength === "strong" ? "很可能重复" : "可能重复"), " ", fmt.ymd(p.local_date)),
      sides.map((s) => h("div", { class: "small" }, h("a", { href: safeHref(s.source_url), target: "_blank", rel: "noopener noreferrer", lang: "ja" }, s.title_ja), `（${srcName(s.source_id)}）`)),
      h("div", { class: "small muted" }, dupWhy(p)),
      h("div", { class: "row" }, keepBtn(sides[0], sides[1]), keepBtn(sides[1], sides[0]),
        h("button", { type: "button", class: "btn", onclick: decideDup(p.a.concert_id, p.b.concert_id, "different", "已标为不同场") }, "不是同一场")));
  }));
async function viewReview(root) {
  const page = h("div", { class: "page" }, h("h1", { class: "page-title", tabindex: "-1" }, "待确认"), h("div", { class: "banner" }, "自动解析的候选，还不是官方确认。确认前请对照来源。"));
  const url = h("input", { type: "url", placeholder: "粘贴官方演出页 URL（仅限已登记来源）", class: "grow", "aria-label": "官方 URL" });
  const stage = h("div");
  page.append(h("div", { class: "row" }, url, h("button", { type: "button", class: "btn", onclick: guard(async () => {
    const r = await api("/import-url", { method: "POST", body: JSON.stringify({ url: url.value.trim() }) });
    stage.replaceChildren(importCard(r)); url.value = "";
  }) }, "导入官方 URL")), stage);
  const q = await api("/review/candidates?limit=200");
  page.append(h("h2", { class: "section-title" }, `候选 ${q.total}`), h("div", { class: "muted small" }, Object.entries(q.by_source).map(([k, v]) => `${srcName(k)} ${v}`).join(" · ")));
  const marked = markedBlock(q.marked_duplicates), merge = confirmedBlock(q.confirmed_duplicates);
  if (!q.items.length) { page.append(h("div", { class: "empty" }, "没有待确认的候选。运行 classical-radar sync 取得最新数据。")); if (merge) page.append(merge); if (marked) page.append(marked); root.append(page); return; }
  const cats = {}, prefs = {};
  const doConfirm = guard(async () => {
    const ids = [...state.reviewSel];
    if (!ids.length) return toast("请先勾选");
    const r = await api("/review/confirm", { method: "POST", body: JSON.stringify({ concert_ids: ids, category_overrides: Object.fromEntries(ids.filter((i) => cats[i]).map((i) => [i, cats[i]])), prefecture_overrides: prefs }) });
    state.reviewSel = new Set(); toast(`已确认 ${r.confirmed.length} 个` + (Object.keys(r.failed).length ? `，${Object.keys(r.failed).length} 个被拒绝` : "")); render();
  });
  page.append(h("div", { class: "row" },
    h("button", { type: "button", class: "btn", onclick: () => { q.items.filter((i) => i.confirmable).forEach((i) => state.reviewSel.add(i.concert_id)); render(); } }, "选择全部可确认"),
    h("button", { type: "button", class: "btn", onclick: () => { state.reviewSel = new Set(); render(); } }, "清除选择"), h("button", { type: "button", class: "btn primary", onclick: doConfirm }, `确认选中 (${state.reviewSel.size})`)));
  let src = null;
  for (const it of q.items) {
    if (it.source_id !== src) { src = it.source_id; page.append(h("h2", { class: "section-title" }, srcName(src))); }
    const cb = h("input", { type: "checkbox", checked: state.reviewSel.has(it.concert_id), disabled: !it.confirmable && !it.performances.some((p) => !p.prefecture_code), "aria-label": "选择 " + it.title_ja });
    cb.addEventListener("change", () => { cb.checked ? state.reviewSel.add(it.concert_id) : state.reviewSel.delete(it.concert_id); });
    const cat = h("select", { "aria-label": "类别" }, Object.entries(L.cat).map(([v, t]) => h("option", { value: v, selected: v === it.suggested_category }, t)));
    cats[it.concert_id] = null; cat.addEventListener("change", () => { cats[it.concert_id] = cat.value; });
    page.append(h("article", { class: "q" }, cb, h("div", { class: "grow" },
      h("h3", { class: "title", lang: "ja" }, it.title_ja), summaryLine(it), dupBlock(it), h("div", { class: "chips" }, it.blockers.map((b) => h("span", { class: "tag bad" }, L.issue[b] || b)), cat, h("a", { href: safeHref(it.source_url), target: "_blank", rel: "noopener noreferrer", class: "small" }, "来源")),
      it.performances.map((p) => {
        let ps = null;
        if (!p.prefecture_code) { ps = h("select", { "aria-label": "都道府县" }, h("option", { value: "" }, "选择都道府县…"), Object.entries(PREF).map(([v, t]) => h("option", { value: v }, t))); ps.addEventListener("change", () => { prefs[p.performance_id] = ps.value; }); }
        return perfRow(p, h("span", { class: "small" }, p.date_raw ? `原文：${p.date_raw}　` : "", ps));
      }))));
  }
  if (merge) page.append(merge);
  if (marked) page.append(marked);
  root.append(page);
}
function importCard(r) {
  const hint = r.performances[0] ? { piano_recital: "piano_recital", domestic_source_candidate: "domestic_orchestra" }[r.performances[0].category_hint] || "other" : "other";
  const cat = h("select", { "aria-label": "类别" }, Object.entries(L.cat).map(([v, t]) => h("option", { value: v, selected: v === hint }, t)));
  const prefs = {};
  return h("section", { class: "stage-card" }, h("h2", { class: "section-title" }, "已暂存，请核对后确认"), h("div", { class: "small" }, h("a", { href: safeHref(r.url), target: "_blank", rel: "noopener noreferrer" }, r.url)),
    r.performances.map((p) => {
      const ps = h("select", { "aria-label": "都道府县（可选，场馆未登记时必填）" }, h("option", { value: "" }, "都道府县：自动"), Object.entries(PREF).map(([v, t]) => h("option", { value: v }, t)));
      ps.addEventListener("change", () => { if (ps.value) prefs[p.performance_id] = ps.value; else delete prefs[p.performance_id]; });
      return h("div", { class: "perfrow" }, h("span", { class: "num" }, `${p.local_date} ${p.local_time || ""}`), h("span", { lang: "ja" }, p.venue || "（无场馆）"), ps);
    }),
    r.ticket_claims_unlinked ? h("div", { class: "muted small" }, `页面含 ${r.ticket_claims_unlinked} 条售票声明，不会自动挂到场次`) : null,
    h("div", { class: "row" }, cat, h("button", { type: "button", class: "btn primary", onclick: guard(async () => { await api(`/import-url/${r.import_id}/confirm`, { method: "POST", body: JSON.stringify({ category: cat.value, prefecture_overrides: prefs }) }); toast("已确认并发布"); render(); }) }, "确认并发布"),
      h("button", { type: "button", class: "btn", onclick: guard(async () => { await api(`/import-url/${r.import_id}/reject`, { method: "POST" }); toast("已驳回"); render(); }) }, "驳回")));
}

const srcName = (id) => (ORG[id] && ORG[id].name) || id;
async function viewSources(root) {
  const c = await api("/discover/coverage");
  const page = h("div", { class: "page" }, h("button", { type: "button", class: "back", onclick: goBack }, icon("chevron-left", { size: 20 }), "返回"), h("h1", { class: "page-title", tabindex: "-1" }, "来源"));
  if (!c.sources.length) { page.append(h("div", { class: "empty" }, "还没有数据。运行 classical-radar sync <db> 取得。")); root.append(page); return; }
  page.append(h("p", { class: "meta-line" }, h("span", {}, `${c.sources.length} 个来源`), stamp() ? h("span", {}, stamp()) : null));
  page.append(h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, [["来源"], ["已存节目", 1], ["已确认", 1], ["场次", 1], ["最近成功（JST）"], ["最近一次运行"]].map(([t, n]) => h("th", { class: n ? "num" : "", scope: "col" }, t)))),
    h("tbody", {}, c.sources.map((s) => h("tr", {}, h("td", { lang: "ja" }, srcName(s.source_id)), h("td", { class: "num" }, s.concerts_stored), h("td", { class: "num" }, s.concerts_official_confirmed), h("td", { class: "num" }, s.performances_stored), h("td", {}, fmt.ts(s.last_success_at).replace(" JST", "") || "—"),
      h("td", {}, s.latest_run_status === "failed" ? h("span", { class: "tag bad", title: s.latest_error || "" }, L.run.failed) : L.run[s.latest_run_status] || s.latest_run_status || "—")))))));
  page.append(h("p", { class: "meta-line" }, "东京爱乐暂不采集"), h("p", { class: "meta-line" }, "Classical Radar v0.1"));
  if (token && !DEMO) page.append(h("div", { class: "row" }, h("button", { type: "button", class: "btn", onclick: logout }, "退出登录")));
  root.append(page);
}

// ---------- season: a whole season as a grid, months down and series across (ADR-0020) ----------
// <season-rules>
// Pure (no DOM, no globals): tests/js/season.test.mjs evaluates only this block. A card is placed by what it SAYS: its first performance that has a day gives its season and month, its title
// gives its series. Nothing is guessed: a title no rule knows goes to "其他公演", a performance without a day is never given one, and no card is ever dropped (each card is in exactly one block).
const SEASON_START = { nhkso: 9 };  // N響 opens its season in September; every other orchestra opens in April
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);  // an orchestra id from an address is looked up with this: "constructor" is no orchestra
const seasonOf = (orch, date) => (Number(date.slice(5, 7)) >= (own(SEASON_START, orch) ? SEASON_START[orch] : 4) ? Number(date.slice(0, 4)) : Number(date.slice(0, 4)) - 1);
const seasonName = (y) => `${y}-${String((y + 1) % 100).padStart(2, "0")}`;
// [column id, column label, regex on the NFKC title]; the first rule that matches wins. The letters are the orchestras' own (N響 A/B/C programmes, 都響 A/B/C series).
// jpo 東京定期 金/土/日 and njp すみだクラシックへの扉 金/土 are one column each (the same programme on two days is merged into one block); njp's two オペラシティ concerts belong to its サントリー series (2027-28 notice).
const SERIES = {
  nhkso: [["A", "A 节目", /Aプログラム/], ["B", "B 节目", /Bプログラム/], ["C", "C 节目", /Cプログラム/]],
  tmso: [["A", "A 系列", /定期演奏会Aシリーズ/], ["B", "B 系列", /定期演奏会Bシリーズ/], ["C", "C 系列", /定期演奏会Cシリーズ/], ["P", "プロムナード", /プロムナード/]],
  tso: [["teiki", "定期演奏会", /^第\s*\d+回\s*定期演奏会/], ["kawasaki", "川崎定期", /^川崎定期演奏会/], ["opera", "オペラシティ", /^東京オペラシティシリーズ/], ["meikyoku", "名曲全集", /^名曲全集/]],
  jpo: [["tokyo", "東京定期", /東京定期演奏会/], ["yokohama", "横浜定期", /横浜定期演奏会/], ["saitama", "さいたま定期", /さいたま定期演奏会/]],
  njp: [["trifony", "トリフォニーホール", /トリフォニーホール・シリーズ/], ["suntory", "サントリーホール", /(?:サントリーホール|オペラシティ)・シリーズ/], ["sumida", "すみだクラシックへの扉", /すみだクラシックへの扉/]],
  yomikyo: [["osaka", "大阪定期", /大阪定期演奏会/], ["teiki", "定期演奏会", /定期演奏会/], ["meikyoku", "名曲シリーズ", /名曲シリーズ/], ["sat", "土曜マチネー", /土曜マチネー/], ["sun", "日曜マチネー", /日曜マチネー/], ["yoko", "横浜マチネー", /横浜マチネー/], ["ens", "アンサンブル", /アンサンブル・シリーズ/]],
};
const OTHER_SERIES = { id: "other", label: "其他公演" };
function seriesOf(orch, title) {
  const t = String(title || "").normalize("NFKC"), hit = (own(SERIES, orch) ? SERIES[orch] : []).find((s) => s[2].test(t));
  return hit ? { id: hit[0], label: hit[1] } : OTHER_SERIES;
}
// a performance "has a day" unless its precision says month only or unknown (a month-only one is kept, shown as a month, never given a day)
const hasDay = (p) => !!p.local_date && p.date_precision !== "month_only" && p.date_precision !== "unknown";
const hasMonth = (p) => !!p.local_date && p.date_precision === "month_only";
const byWhen = (a, b) => (a.local_date + (a.starts_at || "")).localeCompare(b.local_date + (b.starts_at || ""));
function placeOf(it) {  // the date a card is placed by, or null for a card with no dated performance at all
  const ps = it.performances || [], d = ps.filter(hasDay).sort(byWhen)[0] || ps.filter(hasMonth).sort(byWhen)[0];
  return d ? d.local_date : null;
}
// the orchestras of a card, restricted to the ones the page knows; a card with no orchestra tag falls back to its source when that source is one of them
const itemOrchs = (it, known) => { const ks = (it.orchestras || []).map((o) => o.key).filter((k) => known.includes(k)); return ks.length ? ks : known.includes(it.organization_id) ? [it.organization_id] : []; };
const squash = (s) => String(s || "").normalize("NFKC").replace(/\s+/g, "");
// two cards of one month and one series are the SAME programme (one block with all its dates) only when pieces, conductors AND soloists agree; a card with no pieces is never merged
const mergeKey = (it) => ((it.pieces || []).length ? [(it.pieces || []).map((p) => squash(p.work)).join("|"), (it.conductors || []).map(squash).sort().join(","), (it.soloists || []).map(squash).sort().join(",")].join("¦") : "id:" + it.concert_id);
const WD_JA = ["日", "月", "火", "水", "木", "金", "土"];
// a header or a chip wants only the hall name. A venue field can hold a notice glued to the name ("ミューザ川崎シンフォニーホールサントリーホール改修工事による休館のため、…開催いたします。"): keep the name up to its first
// ホール / 劇場 / 会館 / センター. An English translation after a space that follows Japanese ("東京オペラシティ コンサートホール Tokyo Opera City Concert Hall") is dropped, so the two spellings of one hall are one hall
const hallOf = (venue) => {
  let v = String(venue || "").trim();
  if (v.includes("。")) { const m = v.match(/^.*?(?:ホール|劇場|会館|センター)/); v = m ? m[0] : v.split(/[\s　]+/)[0]; }
  return v.replace(/([\u3040-\u30ff\u3400-\u9fff)）])\s+[A-Za-z][A-Za-z0-9 .,&'()\/-]*$/, "$1").trim();  // only after Japanese text: an all-English name ("Hakuju Hall") stays whole
};
const wdJa = (date) => WD_JA[new Date(Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)))).getUTCDay()];
// the grid of one orchestra and one season: { cols: [{id,label}], rows: [{ym, cells: {colId: [block]}}], items, undated }. Cards of another season are left out; undated cards are returned apart
function seasonGrid(items, orch, year) {
  const rows = new Map(), used = new Set(), undated = [], placed = [];
  for (const it of items) {
    const at = placeOf(it);
    if (!at) { undated.push(it); continue; }
    if (seasonOf(orch, at) !== year) continue;
    const col = seriesOf(orch, it.title_ja), ym = at.slice(0, 7), row = rows.get(ym) || rows.set(ym, new Map()).get(ym), cell = row.get(col.id) || row.set(col.id, []).get(col.id), key = mergeKey(it);
    let b = cell.find((x) => x.key === key);
    if (!b) cell.push(b = { key, col: col.id, ym, items: [] });
    b.items.push(it); used.add(col.id); placed.push(it);
  }
  const cols = [...(own(SERIES, orch) ? SERIES[orch] : []).map(([id, label]) => ({ id, label })), OTHER_SERIES].filter((c) => used.has(c.id));
  const finish = (b) => { const perfs = b.items.flatMap((it) => (it.performances || []).filter((p) => hasDay(p) || hasMonth(p))).sort(byWhen); return { ...b, perfs, first: perfs[0].local_date }; };
  const out = [...rows.keys()].sort().map((ym) => ({ ym, cells: Object.fromEntries(cols.map((c) => [c.id, (rows.get(ym).get(c.id) || []).map(finish).sort((a, z) => a.first.localeCompare(z.first))])) }));
  return { cols, rows: out, items: placed, undated };
}
// "9/17(金)・18(土)", "4/24(土) 14:00・25(日)"; a month-only block reads "6月（日期未定）". clock(p) gives "HH:MM" or null (the page passes its Japan-time formatter; an unknown time is never guessed).
// `usual`: the weekday + time slots the column's header already states ("金 19:00"); a date at one of those carries no time, any other date writes its time. Without `usual` every known time is written
function compactDates(perfs, clock, usual) {
  const days = perfs.filter(hasDay).sort(byWhen);
  if (!days.length) { const m = perfs.filter(hasMonth).sort(byWhen)[0]; return m ? `${Number(m.local_date.slice(5, 7))}月（日期未定）` : ""; }
  const groups = [];  // two performances on one day are one date with two times: "4/29(木) 11:00・14:30"
  for (const p of days) { const g = groups[groups.length - 1]; if (g && g.date === p.local_date) g.perfs.push(p); else groups.push({ date: p.local_date, perfs: [p] }); }
  let last = "";
  return groups.map((g) => {
    const y = g.date.slice(0, 4), m = Number(g.date.slice(5, 7)), d = Number(g.date.slice(8, 10)), k = y + "-" + m;
    const text = (k === last ? "" : (y !== days[0].local_date.slice(0, 4) ? y + "/" : "") + m + "/") + `${d}(${wdJa(g.date)})`;
    last = k;
    const times = [...new Set(g.perfs.map((p) => (clock ? clock(p) : null)).filter(Boolean))];
    const say = times.length > 1 || times.some((c) => !(usual && usual.has(wdJa(g.date) + " " + c)));
    return say ? `${text} ${times.join("・")}` : text;
  }).join("・");
}
// the dated sale events of the chosen orchestras, soonest first. saleCountdown reads "还有 N 天" / "今天" / "已开始" in Japan time; an event with no printed time counts as that day
function saleCountdown(d, t, now) {
  const at = Date.parse(`${d}T${t || "00:00"}:00+09:00`), day = (ms) => Math.floor((ms + 9 * 3600e3) / 864e5), n = day(at) - day(now);
  if (n > 0) return { past: false, n, text: `还有 ${n} 天` };
  if (n === 0 && (!t || at > now)) return { past: false, n: 0, text: "今天" };
  return { past: true, n, text: "已开始" };
}
function saleEvents(members, orchs, now) {
  const out = [];
  for (const o of orchs) for (const s of (own((members || {}).orchestras || {}, o) ? members.orchestras[o].sales : []) || []) out.push({ orch: o, ...s, ...saleCountdown(s.d, s.t, now) });
  return out.sort((a, b) => (a.d + (a.t || "")).localeCompare(b.d + (b.t || "")) || (a.orch < b.orch ? -1 : 1));
}
// the page shows one orchestra at a time (there is no "all"): the one in the address, else the one chosen last time, else the first of the list. includes(), never an object lookup
function pickOrch(arg, remembered, order) {
  return order.includes(arg) ? arg : order.includes(remembered) ? remembered : order[0];
}
// what the sale-calendar row says: the sales that have not started, the ones that have, and the next one
function saleSummary(events) {
  const soon = events.filter((s) => !s.past), done = events.filter((s) => s.past);
  return { soon, done, next: soon.length ? soon[0] : null };
}
// </season-rules>

// ---------- a bottom sheet: a long list that should not make the page long (ADR-0020, 2026-11-20 revision 2) ----------
// A native <dialog> opened with showModal(): Esc, the × button, a tap on the dimmed area and sheet.close() all close it, focus is kept inside while it is open, and focus goes back to the button that opened it.
// Put the dialog inside the page that owns it: leaving the page removes it (the scroll lock in app.css is a :has() rule, so it goes with the dialog). onClose runs after every close.
// Focus starts on the × button (the first control in the card), not on a text box, so a phone's keyboard does not pop up by itself.
function makeSheet({ title, sub, body, footer, onClose }) {
  const titleEl = h("h2", { class: "sheet-title" }, title);
  const dlg = h("dialog", { class: "sheet", "aria-label": title },
    h("div", { class: "sheet-card" },  // the card fills the dialog, so a click whose target is the dialog itself is a click on the dimmed area
      h("header", { class: "sheet-head" }, h("div", { class: "sheet-heads" }, titleEl, sub ? h("p", { class: "sheet-sub" }, sub) : null),
        h("button", { type: "button", class: "ib", "aria-label": "关闭", onclick: () => dlg.close() }, icon("x", { size: 20 }))),
      h("div", { class: "sheet-body" }, body),
      footer ? h("footer", { class: "sheet-foot" }, footer) : null));
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("close", () => { if (onClose && dlg.isConnected) onClose(); });  // a page that was replaced while the sheet was open does not redraw itself again
  return { el: dlg, close: () => dlg.close(), open() { if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", ""); } };
}

// ---------- the season page (ADR-0020): one orchestra's season as the poster grid, an interest filter over it, and the membership / presale guide ----------
const MEMBERS = () => window.CR_MEMBERS || { checked: "", orchestras: {} };
const PICK_KEY = "cr_season_pick", ORCH_KEY = "cr_season_orch";
function loadPicks() {
  try { const v = JSON.parse(store.get(PICK_KEY) || "[]"); return Array.isArray(v) ? v.filter((x) => x && BROWSE_DIMS.includes(x.dim) && typeof x.id === "string" && typeof x.label === "string").slice(0, 40) : []; } catch { return []; }
}
const seasonHref = (orch) => "#season" + (orch ? "/" + orch : "");  // the season is not in the address: the page always shows the newest one that has programmes
const ymLabel = (ym) => h("span", { class: "sg-m" }, h("span", { class: "sg-mn" }, String(Number(ym.slice(5, 7)))), h("span", { class: "sg-my" }, "月"), h("span", { class: "sg-yr" }, ym.slice(0, 4)));
// the hall and the weekday + time of a column, read from its own performances: the most used halls (two at most) and the distinct weekday + time pairs (three at most)
function colInfo(blocks) {
  const venues = new Map(), slots = new Map();
  for (const b of blocks) for (const p of b.perfs.filter(hasDay)) {
    const v = hallOf(venueText(p)) || "场馆未公布"; venues.set(v, (venues.get(v) || 0) + 1);
    const c = clock(p), k = wdJa(p.local_date) + (c ? " " + c : ""); slots.set(k, (slots.get(k) || 0) + 1);
  }
  const top = (m, n) => [...m].sort((a, z) => z[1] - a[1] || (a[0] < z[0] ? -1 : 1)).slice(0, n).map((e) => e[0]);
  return { halls: top(venues, 2), slots: top(slots, 3), moreHalls: venues.size > 2 };
}
// withName: the orchestra's name leads the line (only useful in a list that mixes orchestras); withNote: the long note under it (only in the orchestra's own guide)
function saleRow(s, withName, withNote) {
  const [y, m, d] = s.d.split("-").map(Number), src = safeHref(s.src);
  return h("li", { class: "sale-row" + (s.past ? " past" : "") },
    h("p", { class: "sr-when" }, h("span", { class: "sr-day" }, `${fmt.ymd(s.d)} ${weekday(y, m, d)}`), s.t ? h("span", { class: "sr-time" }, "　" + s.t) : null, h("span", { class: "sr-left" + (s.past ? "" : " next") }, "　" + s.text)),
    h("p", { class: "sr-what", lang: "ja" }, withName ? h("span", { class: "sr-orch" }, orchName(s.orch) + "　") : null, s.what, " ", h("span", { class: "tag" }, s.who)),
    s.note && withNote ? h("p", { class: "muted small" }, s.note) : null,
    src ? h("a", { class: "sr-src small", href: src, target: "_blank", rel: "noopener noreferrer" }, "官网出处", icon("external-link", { size: 14 })) : null);
}
// the membership / presale guide of one orchestra: what the official pages say, nothing more. Opens by itself for an orchestra with no programme yet
function memberPanel(orch, open) {
  const m = ownKey(MEMBERS().orchestras, orch) ? MEMBERS().orchestras[orch] : null;
  if (!m) return null;
  const series = m.ways.filter((w) => w.kind === "series"), presale = m.ways.filter((w) => w.kind === "presale");  // the dated sales are in the 购票日程 sheet, not repeated here
  const ways = (title, list) => list.length ? h("section", { class: "mem-block" }, h("h4", { class: "mem-sub" }, title), h("ul", { class: "mem-ways" }, list.map((w) => h("li", {}, h("span", { class: "mw-name", lang: "ja" }, w.name), h("span", { class: "mw-text" }, w.text))))) : null;
  const noteSrc = m.noteSrc ? safeHref(m.noteSrc) : null;
  return h("details", { class: "mem", open: open }, h("summary", {}, "会员 · 购票入口"),
    h("div", { class: "mem-body" },
      h("p", { class: "mem-note" }, m.note, noteSrc ? h("a", { href: noteSrc, target: "_blank", rel: "noopener noreferrer" }, "　官网出处") : null),
      ways("连续券（同一个座位）", series), ways("不买连续券也能先买", presale),
      m.lastYear.length ? h("section", { class: "mem-block" }, h("h4", { class: "mem-sub" }, "去年的节奏（仅供参考）"), h("ul", { class: "mem-last muted small" }, m.lastYear.map((t) => h("li", {}, t)),
        m.lastYearSrc && safeHref(m.lastYearSrc) ? h("li", {}, h("a", { href: m.lastYearSrc, target: "_blank", rel: "noopener noreferrer" }, "官网出处")) : null)) : null,
      h("div", { class: "pills" }, m.links.map((l) => safeHref(l.url) ? h("a", { class: "pill-link", href: l.url, target: "_blank", rel: "noopener noreferrer" }, icon("external-link", { size: 16 }), l.label) : null)),
      m.phone ? h("p", { class: "muted small" }, m.phone) : null,
      h("p", { class: "muted small" }, `官网 ${MEMBERS().checked} 确认，购买前以官网为准`)));
}
// one block of the grid: dates, the programme, who conducts and plays, a Pickup button. The whole block opens the concert page of its first card; a merged block lists the others below
function seasonBlock(b, orch, col, ctx, usual) {
  const it = b.items[0], { R, picks } = ctx, rows = new Map(R.rowsOf(it).map((r) => [r.p, r]));
  const markC = new Set(picks.filter((x) => x.dim === "composer").map((x) => x.id)), markW = new Set(picks.filter((x) => x.dim === "work").map((x) => x.id));
  const markP = new Set(picks.filter((x) => x.dim === "conductor" || x.dim === "performer").map((x) => x.dim + ":" + x.id));
  const lines = (it.pieces || []).map((p) => {
    const r = rows.get(p);
    if (r && r.tr) return null;  // the English line of a piece already listed in Japanese
    return { text: r ? `${r.text}／${r.title}` : [p.composer, p.work].filter(Boolean).join("／"), hit: !!r && (markW.has(r.id) || markC.has(r.cid)) };
  }).filter((l) => l && l.text);
  const who = [["指挥", it.conductors, "conductor"], ["独奏", it.soloists, "performer"]].filter(([, l]) => (l || []).length)
    .map(([k, names, dim]) => ({ k, names: names.map((n) => ({ n, hit: markP.has(dim + ":" + nameFold(n)) })) }));
  const hit = lines.some((l) => l.hit) || who.some((w) => w.names.some((x) => x.hit));
  const tag = saleTag(it), hall = hallOf(venueText(b.perfs.find(hasDay) || b.perfs[0])) || "";
  const pick = h("button", { type: "button", class: "sb-pick" });
  const picked = () => b.items.every((x) => x.user_pickup);
  // the column name is not on a desktop block (the header says it), so the button's label names it
  const paint = () => { pick.setAttribute("aria-pressed", String(picked())); pick.setAttribute("aria-label", (picked() ? "已加入 Pickup：" : "加入 Pickup：") + col.label + " " + compactDates(b.perfs, clock)); pick.replaceChildren(icon("bookmark", { size: 18, fill: picked() })); };
  pick.addEventListener("click", guard(async () => {
    const on = !picked();
    await Promise.all(b.items.filter((x) => !!x.user_pickup !== on).map((x) => (on ? api(`/me/pickups/${x.concert_id}`, { method: "PUT", body: JSON.stringify({ priority: "normal" }) }) : api(`/me/pickups/${x.concert_id}`, { method: "DELETE" }))));
    b.items.forEach((x) => { x.user_pickup = on; });
    paint(); toast(on ? "已加入 Pickup" : "已移出 Pickup");
  }));
  paint();
  const others = b.items.slice(1);
  return h("article", { class: "sb" + (hit ? " hit" : "") },
    h("a", { class: "sb-main", href: "#concert/" + it.concert_id, "data-cid": it.concert_id },
      h("span", { class: "sb-chip", lang: "ja" }, [col.label, hall, usual ? [...usual].join(" / ") : ""].filter(Boolean).join(" · ")),  // a phone has no column header: the chip carries the series, the hall and the usual days and times
      h("span", { class: "sb-date" }, compactDates(b.perfs, clock, usual), tag ? h("span", { class: "sb-tag" }, tag) : null),
      lines.length ? h("ul", { class: "sb-lines", lang: "ja" }, lines.map((l) => h("li", { class: l.hit ? "mk" : false }, l.text))) : h("span", { class: "muted small" }, "曲目未公布"),
      who.length ? h("span", { class: "sb-who", lang: "ja" }, who.map((w) => h("span", {}, `${w.k} `, w.names.map((x, i) => [i ? "、" : null, h("span", { class: x.hit ? "mk" : false }, x.n)])))) : null),
    pick,
    others.length ? h("p", { class: "sb-more small" }, "另一天的详情页：", others.map((o, i) => [i ? "、" : null, h("a", { href: "#concert/" + o.concert_id, "data-cid": o.concert_id }, compactDates(o.performances.filter((p) => hasDay(p) || hasMonth(p)), clock))])) : null);
}
// one orchestra's grid. `only`: hide the blocks that match none of the chosen interests (rows left empty go too; columns stay so their "命中 a/b" count stays readable)
function seasonGridEl(orch, grid, ctx) {
  const { picks, only, hitOf } = ctx, n = grid.cols.length, cols = `cols-${Math.min(n, 7)}`;
  const shown = (b) => !picks.length || !only || hitOf(b);
  const head = h("div", { class: "sg-head " + cols }, h("span", { class: "sg-corner" }),
    grid.cols.map((c, i) => {
      const all = grid.rows.flatMap((r) => r.cells[c.id]), info = colInfo(all), hits = all.filter(hitOf).length;
      return h("div", { class: `sg-col k${i % 6}` }, h("span", { class: "sg-col-name", lang: "ja" }, c.label),
        h("span", { class: "sg-col-info", lang: "ja" }, [info.halls.join("・") + (info.moreHalls ? " 等" : ""), info.slots.join(" / ")].filter(Boolean).join("　")),
        picks.length ? h("span", { class: "sg-col-hit" }, `命中 ${hits}/${all.length}`) : null);
    }));
  const usual = Object.fromEntries(grid.cols.map((c) => [c.id, new Set(colInfo(grid.rows.flatMap((r) => r.cells[c.id])).slots)]));
  const body = grid.rows.map((r) => {
    const any = grid.cols.some((c) => r.cells[c.id].some(shown));
    if (!any) return null;
    return h("section", { class: "sg-row " + cols }, h("h3", { class: "sg-month" }, ymLabel(r.ym)),
      grid.cols.map((c, i) => h("div", { class: `sg-cell k${i % 6}` }, r.cells[c.id].filter(shown).map((b) => seasonBlock(b, orch, c, ctx, usual[c.id])))));
  }).filter(Boolean);
  return h("div", { class: "sg" }, head, body.length ? body : h("p", { class: "empty" }, "没有命中的节目。"));
}
async function viewSeason(root, r) {
  const all = await loadAll(24, EMPTY_FLT()), items = inKanto(all), { R } = browseOf(all), now = nowMs();
  const S = state.season || (state.season = { q: "", picks: loadPicks(), only: true });
  // a saved interest whose id the loaded data no longer has is found again by its written name; one that is not found stays as a chip the person can remove
  const known = Object.fromEntries(BROWSE_DIMS.map((d) => [d, indexOf(all, d)]));
  const entryText = (dim, e) => (dim === "work" && e.sub ? `${e.sub}／${e.label}` : e.label);  // a piece is named with its composer: "交響曲 第4番" alone is many pieces
  S.picks = S.picks.map((x) => { const list = known[x.dim]; if (list.some((e) => e.id === x.id)) return x; const e = list.find((y) => bfold(entryText(x.dim, y)) === bfold(x.label)); return e ? { ...x, id: e.id } : x; });
  // one orchestra at a time: the address's, else the one chosen last time, else the first (a well-shaped id that is none of the seven falls through to the same rule)
  const orch = pickOrch(r.arg, store.get(ORCH_KEY), SEVEN_ORDER), shownOrchs = [orch];
  if (SEVEN_ORDER.includes(r.arg)) store.set(ORCH_KEY, r.arg);
  // only the newest season that has any card is shown (an older one, such as the running 2026-27, is not offered at all; a year in an old link is ignored). An orchestra with nothing in it gets the empty line, never an older season
  const years = [...new Set(items.flatMap((it) => itemOrchs(it, SEVEN_ORDER).map((o) => { const at = placeOf(it); return at ? seasonOf(o, at) : null; })).filter((y) => y != null))].sort();
  const year = years.length ? years[years.length - 1] : curYear();
  const grids = Object.fromEntries(shownOrchs.map((o) => [o, seasonGrid(items.filter((it) => itemOrchs(it, SEVEN_ORDER).includes(o)), o, year)]));
  const scope = [...new Map(shownOrchs.flatMap((o) => grids[o].items).map((it) => [it.concert_id, it])).values()];
  const hitCache = new Map();
  const hitsOf = (it) => { let v = hitCache.get(it.concert_id); if (!v) hitCache.set(it.concert_id, v = S.picks.filter((x) => entriesOf(it, x.dim, R).some((e) => e.id === x.id))); return v; };
  const hitOf = (b) => b.items.some((it) => hitsOf(it).length);
  const ctx = { R, picks: S.picks, only: S.only, hitOf };
  const go = (o) => { store.set(ORCH_KEY, o); history.replaceState(history.state, "", seasonHref(o)); render(); };
  const redraw = () => { store.set(PICK_KEY, JSON.stringify(S.picks)); render(); };
  const page = h("div", { class: "page season" },
    h("div", { class: "head" }, h("div", { class: "title-row" }, h("h1", { class: "page-title", tabindex: "-1" }, "乐季"), h("span", { class: "season-badge" }, seasonName(year))),
      h("div", { class: "chip-row", role: "group", "aria-label": "按乐团" },
        SEVEN_ORDER.map((o) => h("button", { type: "button", class: "chip tokiwa", "aria-pressed": String(orch === o), onclick: () => { if (orch !== o) go(o); } }, orchName(o))))));
  // ---- the interest filter: one box, four kinds; the chosen ones are chips; a block that hits ANY of them is marked ----
  const input = h("input", { type: "search", class: "search-input", placeholder: "搜名字、曲目", autocomplete: "off", enterkeyhint: "search", "aria-label": "搜索指挥、演奏家、作曲家、曲目", value: S.q });
  const sugg = h("div", { class: "sugg" });
  const scoped = Object.fromEntries(BROWSE_DIMS.map((d) => [d, buildIndex(scope, d, R)]));
  const isPicked = (dim, id) => S.picks.some((x) => x.dim === dim && x.id === id);
  const flip = (dim, e) => { S.picks = isPicked(dim, e.id) ? S.picks.filter((x) => !(x.dim === dim && x.id === e.id)) : [...S.picks, { dim, id: e.id, label: entryText(dim, e) }].slice(-40); };
  const toggle = (dim, e) => { flip(dim, e); S.q = ""; redraw(); };
  const entryChip = (dim, e) => h("button", { type: "button", class: "chip small", "aria-pressed": String(isPicked(dim, e.id)), onclick: () => toggle(dim, e) }, h("span", { lang: "ja" }, entryText(dim, e)), h("span", { class: "n" }, String(e.n)));
  const paintSugg = () => {
    const t = bfold(S.q);
    if (!t) { sugg.replaceChildren(); return; }
    const groups = BROWSE_DIMS.map((d) => [d, scoped[d].filter((e) => entryHay(e, d).includes(t)).slice(0, 8)]).filter(([, l]) => l.length);
    sugg.replaceChildren(...(groups.length ? groups.map(([d, l]) => h("div", { class: "sugg-group" }, h("span", { class: "sugg-k" }, BROWSE_TITLE[d]), h("div", { class: "chips" }, l.map((e) => entryChip(d, e))))) : [h("p", { class: "muted small" }, `没找到“${S.q}”，试试日文写法`)]));
  };
  input.addEventListener("input", () => { S.q = input.value; paintSugg(); });  // only the suggestions change while typing, so the caret stays where it is
  paintSugg();
  const total = grids[orch].rows.flatMap((x) => Object.values(x.cells).flat()).filter(hitOf).length;
  // ---- 全部名单: a button that opens a sheet with the four lists. A tap in the sheet picks / unpicks (kept in S.picks and on the chip itself); the page behind is redrawn once, when the sheet closes, so the sheet is never rebuilt under the finger ----
  // The interests are the person's, not the orchestra's: they stay when another orchestra is chosen, and simply hit nothing there
  const NAME_TABS = ["conductor", "performer", "composer", "work"], namesTotal = NAME_TABS.reduce((a, d) => a + scoped[d].length, 0);
  let nameTab = "conductor", touched = false;
  const tabsEl = h("div", { class: "sheet-tabs", role: "group", "aria-label": "名单种类" });
  const narrow = h("input", { type: "search", class: "search-input", placeholder: "在这份名单里找", autocomplete: "off", enterkeyhint: "search", "aria-label": "在这份名单里找" });
  const listEl = h("div", { class: "chips" });
  const doneBtn = h("button", { type: "button", class: "btn primary" }), clearBtn = h("button", { type: "button", class: "btn" }, "清空");
  const paintFoot = () => { doneBtn.textContent = S.picks.length ? `完成 · 已选 ${S.picks.length}` : "完成"; clearBtn.hidden = !S.picks.length; };
  const paintNames = () => {
    tabsEl.replaceChildren(...NAME_TABS.map((d) => h("button", { type: "button", "aria-pressed": String(d === nameTab), onclick: () => { nameTab = d; narrow.value = ""; paintNames(); } }, BROWSE_TITLE[d], h("span", { class: "n" }, String(scoped[d].length)))));
    const t = bfold(narrow.value), hits = scoped[nameTab].filter((e) => !t || entryHay(e, nameTab).includes(t));
    listEl.replaceChildren(...(hits.length ? hits.slice(0, 300).map((e) => {
      const chip = h("button", { type: "button", class: "chip small", "aria-pressed": String(isPicked(nameTab, e.id)) }, h("span", { lang: "ja" }, entryText(nameTab, e)), h("span", { class: "n" }, String(e.n)));
      const dim = nameTab;
      chip.addEventListener("click", () => { flip(dim, e); touched = true; chip.setAttribute("aria-pressed", String(isPicked(dim, e.id))); paintFoot(); });
      return chip;
    }) : [h("p", { class: "muted" }, t ? `没找到“${narrow.value}”，试试日文写法` : "这个乐团这一季还没有这一类的名字")]));
  };
  narrow.addEventListener("input", paintNames);
  clearBtn.addEventListener("click", () => { S.picks = []; touched = true; paintNames(); paintFoot(); });
  const namesSheet = makeSheet({ title: "全部名单", sub: `${orchName(orch)} · ${seasonName(year)}`,
    body: [tabsEl, h("form", { class: "search-form sheet-narrow", role: "search", onsubmit: (e) => e.preventDefault() }, narrow), listEl],
    footer: [clearBtn, doneBtn], onClose: () => { if (touched) redraw(); } });
  doneBtn.addEventListener("click", () => namesSheet.close());
  paintNames(); paintFoot();
  page.append(h("section", { class: "section season-filter" },
    h("div", { class: "sf-row" }, h("form", { class: "search-form", role: "search", onsubmit: (e) => e.preventDefault() }, input),
      h("button", { type: "button", class: "chip names-btn", disabled: !namesTotal, "aria-haspopup": "dialog", onclick: () => namesSheet.open() }, icon("list", { size: 18 }), "全部名单")), sugg,
    S.picks.length ? h("div", { class: "chips picks" }, S.picks.map((x) => h("button", { type: "button", class: "chip small on", "aria-label": `去掉 ${BROWSE_TITLE[x.dim]} ${x.label}`, onclick: () => toggle(x.dim, x) }, h("span", { class: "n" }, BROWSE_TITLE[x.dim]), h("span", { lang: "ja" }, x.label), icon("x", { size: 14 })))) : null,
    S.picks.length ? h("div", { class: "row" }, h("button", { type: "button", class: "chip small", "aria-pressed": String(S.only), onclick: () => { S.only = !S.only; render(); } }, "只看命中"),
      h("button", { type: "button", class: "chip small", onclick: () => { S.picks = []; redraw(); } }, "清空"),
      h("span", { class: "muted small", role: "status" }, total ? `命中 ${total} 个节目` : "这个乐团没有命中的节目")) : null, namesSheet.el));
  // ---- 购票日程: one row on the page, the whole list in a sheet (both the sales to come and the ones that have started, in full) ----
  // (the member guide below stays folded unless an orchestra has no programme yet)
  const events = saleEvents(MEMBERS(), shownOrchs, now), { soon, done, next } = saleSummary(events);
  if (events.length) {
    const rows = (list) => h("ul", { class: "sale-list" }, list.map((s) => saleRow(s, false, true)));  // in a sheet there is room for the one-line note that says who the sale is for
    const saleSheet = makeSheet({ title: "购票日程", sub: `${orchName(orch)} · 官网 ${MEMBERS().checked.slice(5).replace("-", "/")} 确认`,
      body: [h("h3", { class: "sheet-sec" }, `还没开始 ${soon.length} 条`), soon.length ? rows(soon) : h("p", { class: "muted" }, "没有还没开始的发售日"),
        done.length ? [h("h3", { class: "sheet-sec" }, `已开始 ${done.length} 条`), rows(done)] : null] });
    page.append(h("section", { class: "section sale-sec" },
      h("button", { type: "button", class: "sale-entry", "aria-haspopup": "dialog", onclick: () => saleSheet.open() },
        h("span", { class: "se-main" }, h("span", { class: "se-title" }, "购票日程"),
          h("span", { class: "se-line" }, next ? `最近　${fmt.ymd(next.d)}　${next.text}${soon.length > 1 ? `　· 共 ${soon.length} 条未开始` : ""}` : `没有还没开始的发售日${done.length ? `　· 已开始 ${done.length} 条` : ""}`)),
        icon("chevron-right", { size: 20 })), saleSheet.el));
  }
  // ---- one section per orchestra ----
  for (const o of shownOrchs) {
    const g = grids[o], n = g.items.length, blocks = g.rows.reduce((a, x) => a + Object.values(x.cells).flat().length, 0);
    const sec = h("section", { class: "section orch-sec" }, h("div", { class: "section-head" }, h("h2", { class: "section-title" }, orchName(o), h("span", { class: "count-n" }, n ? `　${seasonName(year)} · ${blocks} 个节目` : `　${seasonName(year)}`)),
      n ? h("a", { class: "section-link", href: `#list/orchestra/${o}/${year}` }, "全部公演") : null));  // that season's cards only: the plain list is the next 12 months of every season
    if (n) sec.append(seasonGridEl(o, g, ctx));
    else sec.append(h("p", { class: "empty-line" }, `暂无 ${seasonName(year)} 乐季的节目（仅首都圈）`));
    if (n && g.undated.length) sec.append(h("p", { class: "muted small" }, "另有日期未定的公演：", g.undated.map((it, i) => [i ? "、" : null, h("a", { href: "#concert/" + it.concert_id, lang: "ja" }, it.title_ja)])));
    const panel = memberPanel(o, !n);
    if (panel) sec.append(panel);
    page.append(sec);
  }
  page.append(footnote());
  root.append(page);
  return { title: `乐季 ${seasonName(year)}` };
}

// ---------- shell ----------
// <route-rules>
// the list routes: #list/presenter, #list/piano, #list/orchestra and #list/orchestra/<orchestra id>. Pure: tests/js/route.test.mjs evaluates only this block.
const LIST_KINDS = ["presenter", "piano", "orchestra"];
// #list/orchestra/<id>/<season start year> is one orchestra's programmes of one season (the season page's 全部公演 link, ADR-0020); a year of the wrong shape is simply not there
function listRoute(arg, sub, season) {
  if (!arg || !LIST_KINDS.includes(arg)) return null;  // includes(), not an object lookup: "toString" or "constructor" must not pass
  if (arg !== "orchestra" || !sub || !/^[a-z][a-z0-9_-]{1,40}$/.test(sub)) return { name: "list", arg };
  return season && /^20\d\d$/.test(season) ? { name: "list", arg, sub, season: Number(season) } : { name: "list", arg, sub };
}
// #browse/<kind> is the index of conductors, soloists, composers or pieces; #browse/<kind>/<id> is one of them (ADR-0010).
// The id is a spelling or a reviewed key, never an API path, so it only has to be short and free of control characters; anything else shows the index
const BROWSE_DIMS = ["conductor", "performer", "composer", "work"];
function browseRoute(arg, sub) {
  if (!arg || !BROWSE_DIMS.includes(arg)) return null;
  return sub && sub.length <= 200 && !/[\u0000-\u001f\u007f]/.test(sub) ? { name: "browse", arg, sub } : { name: "browse", arg };
}
// #season, #season/<orchestra id | all> and #season/<orchestra id | all>/<season year> (ADR-0020): the chosen orchestra and season live in the address, like the list routes.
// An id or year of the wrong shape is simply not chosen (arg / sub null), so the page shows its default
function seasonRoute(arg, sub) {
  return { name: "season", arg: arg && arg !== "all" && /^[a-z][a-z0-9_-]{1,40}$/.test(arg) ? arg : null, sub: sub && /^20\d\d$/.test(sub) ? Number(sub) : null };
}
// </route-rules>
function parseRoute() {
  const raw = (location.hash || "").replace(/^#\/?/, ""), [path] = raw.split("?"), parts = path.split("/"), name = parts[0] || "discover";
  let arg = null, sub = null, third = null;
  try { arg = parts[1] ? decodeURIComponent(parts[1]) : null; sub = parts[2] ? decodeURIComponent(parts[2]) : null; third = parts[3] ? decodeURIComponent(parts[3]) : null; } catch { arg = sub = third = null; }  // a malformed hash is just an unknown route
  if (name === "concert" && arg && /^[\w-]{6,80}$/.test(arg)) return { name, arg };  // the id goes into an API path: no slashes, dots or percent signs
  if (name === "list") { const route = listRoute(arg, sub, third); if (route) return route; }
  if (name === "browse") { const route = browseRoute(arg, sub); if (route) return route; }  // a malformed % in the hash made arg null above: that is the discover page, like any unknown route
  if (name === "season") return seasonRoute(arg, sub);
  if (name === "lead" && arg && /^lead-[0-9a-f]{20}$/.test(arg)) return { name, arg };  // a lead id is never a concert id
  if (name === "leads") return { name };
  if (name === "sources") return { name };
  if (TABS.some(([k]) => k === name)) return { name };
  return { name: "discover" };
}
const routeKey = () => (location.hash || "").replace(/^#\/?/, "") || "discover";
// back: the browser's history when this page was reached from inside the app, otherwise the discover page (a deep link has no history to go back to)
function goBack() { if (state.navCount > 0) history.back(); else location.hash = "#discover"; }
const goBackOr = (fallback) => () => { if (state.navCount > 0) history.back(); else location.hash = fallback; };  // a page that was opened from somewhere other than the discover page: its deep link goes back there
const VIEWS = { discover: viewDiscover, season: viewSeason, list: viewList, browse: viewBrowse, leads: viewLeads, lead: viewLead, search: viewSearch, calendar: viewCalendar, mine: viewMine, concert: viewDetail, review: viewReview, sources: viewSources };
let renderSeq = 0, lastRoute = null, rendered = false;
// the controls of a page are rebuilt on every render: remember the focused one by its tag and label, then focus its twin afterwards
const labelOf = (el) => el.getAttribute("aria-label") || el.textContent.trim();
function focusKey(view) {
  const el = document.activeElement;
  if (!el || el === view || !view.contains(el)) return null;
  const same = [...view.querySelectorAll(el.tagName)].filter((x) => labelOf(x) === labelOf(el));
  return { tag: el.tagName, label: labelOf(el), n: Math.max(0, same.indexOf(el)) };
}
function refocus(view, k) {
  const same = [...view.querySelectorAll(k.tag)].filter((x) => labelOf(x) === k.label), el = same[k.n] || same[0];
  if (el && !el.disabled) el.focus({ preventScroll: true });
}
async function render() {
  const view = $("#view"), r = parseRoute(), seq = ++renderSeq, tab = r.name === "list" && r.season != null ? "season" : ["concert", "list", "browse", "lead", "leads"].includes(r.name) ? "discover" : r.name;  // a season's own list belongs to the 乐季 tab
  // replaceChildren takes nodes, not arrays: an array would be turned into text
  $("#nav").replaceChildren(h("a", { class: "brand", href: "#discover", "aria-label": "Classical Radar" }, brandMark(), h("span", { "aria-hidden": "true" }, "classical radar")),
    ...TABS.map(([k, t, ic]) => h("a", { class: "nav-item", href: "#" + k, "aria-current": k === tab ? "page" : false }, icon(ic, { size: 24 }), h("span", {}, t))),
    ...(token && !DEMO ? [h("div", { class: "nav-foot" }, h("button", { type: "button", class: "btn", onclick: logout }, "退出"))] : []));
  const frag = document.createDocumentFragment(), key = routeKey(), changed = key !== lastRoute, y = window.scrollY, fk = changed ? null : focusKey(view);
  let meta = null;
  if (changed) state.calPick = false;  // the month picker never stays open across a visit: coming back to the calendar starts with it closed
  if (DEMO && DEMO.mode !== "site") frag.append(h("div", { class: "banner" }, `演示快照 · ${DEMO.snapshot} · 收藏和状态只存在本机`));
  if (!token) loginView(frag);
  else { try { meta = await VIEWS[r.name](frag, r); } catch (e) { if (token) frag.append(h("div", { class: "page" }, h("div", { class: "banner" }, e.message), r.name === "discover" ? null : h("a", { class: "button-secondary", href: "#discover" }, "回到发现"))); } }
  if (seq !== renderSeq) return;  // a newer navigation started while this one was loading
  view.replaceChildren(frag);
  document.title = (meta && meta.title ? meta.title + " · " : "") + "Classical Radar";
  if (!changed) { window.scrollTo(0, y); if (fk) refocus(view, fk); return; }  // same page re-rendered (a filter changed): keep scroll and focus
  lastRoute = key;
  // coming back from a concert page to the list it was opened from: same scroll position, focus on the same card.
  // The record survives the detail page itself and is dropped by any other route, so it can never apply to a later visit.
  const back = state.restore && state.restore.route === key ? state.restore : null;
  if (r.name !== "concert" && r.name !== "browse") state.restore = null;  // a browse page sits between a list and a concert page: the list's spot is kept for the way back
  window.scrollTo(0, back ? back.scrollY : 0);
  const target = back && back.cid ? view.querySelector(`[data-cid="${CSS.escape(back.cid)}"]`) : view.querySelector("h1[tabindex]");
  if (target && rendered) target.focus({ preventScroll: true });  // not on the very first load, so the page does not steal focus
  rendered = true;
}
function loginView(root) {
  const input = h("input", { type: "password", placeholder: "访问令牌 (CLASSICAL_RADAR_TOKEN)", autocomplete: "current-password", "aria-label": "访问令牌", class: "grow" });
  const go = guard(async () => { const t = input.value.trim(); const r = await fetch(API + "/discover/coverage", { headers: { Authorization: "Bearer " + t } }); if (!r.ok) throw new Error("令牌无效"); token = t; store.set("cr_token", token); render(); });  // only a verified token is kept
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  root.append(h("div", { class: "page" }, h("h1", { class: "page-title", tabindex: "-1" }, "Classical Radar"), h("p", { class: "lede muted" }, "输入启动服务时设置的访问令牌"), h("div", { class: "row" }, input, h("button", { type: "button", class: "btn primary", onclick: go }, "进入"))));
}
// remember which card was opened and where the list was scrolled, so that "back" lands on the same card
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("[data-cid]");
  if (a && !e.defaultPrevented) state.restore = { route: routeKey(), scrollY: window.scrollY, cid: a.getAttribute("data-cid") };
});
window.addEventListener("hashchange", () => { state.navCount++; render(); });
render();
