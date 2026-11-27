// The ids the browse pages use, computed by the APP'S OWN rules (src/classical_radar/web/app.js, the <browse-rules> block), so the Apple id table
// (scripts/resolve_classical_links.py, ADR-0014) can never drift from the page ids. Usage: node scripts/browse_entities.mjs [site-data/concerts.json]
// Prints JSON: works / composers / people, each {id, n (concerts), ...}. The ids are LOCAL ids (what a programme row or a name carries by itself), not
// the resolver's, so they do not change when other concerts join or leave the loaded list.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const js = readFileSync(join(root, "src/classical_radar/web/app.js"), "utf8");
const m = js.match(/\/\/ <browse-rules>([\s\S]*?)\/\/ <\/browse-rules>/);
if (!m) throw new Error("app.js has no <browse-rules> block");
const { nameFold, isComposerName, personDim, localComposerId, localWorkId, programPiece } = new Function(`${m[1]}\nreturn { nameFold, isComposerName, personDim, localComposerId, localWorkId, programPiece };`)();

const data = JSON.parse(readFileSync(process.argv[2] || join(root, "site-data/concerts.json"), "utf8"));
const works = new Map(), composers = new Map(), people = new Map();
// "ムソルグスキー(ラヴェル編):組曲「展覧会の絵」": the arranger sits in the composer part of the raw line, which the work text no longer carries. Such a row is somebody's version of
// the piece, not the piece itself. A bracket that only gives years or an anniversary ("ベートーヴェン(1770-1827):", "(生誕250年)") is no arranger. An entity is `arranged` when EVERY one of its
// rows is such a line (one arranged line among the originals does not take the piece's page away; the dump says how many rows and how many were arranged, the review looks at the mixed ones).
// Not seen: an arranger written outside brackets ("ムソルグスキー/ラヴェル編:"), other brackets, or no colon: those are still left to the person who reads the proposal.
const ARRANGER_NOTE = /^[^:：/／]*?\s*[（(]([^）)]+)[）)]\s*[:：]/;
const NOT_AN_ARRANGER = /^[\d\s\-–~〜.,年生没歿頃c]+$|生誕|没後|周年|記念|生没/;
const arrangerLine = (raw) => { const m = ARRANGER_NOTE.exec(raw.normalize("NFKC")); return !!m && !NOT_AN_ARRANGER.test(m[1].trim()); };
const add = (map, id, concert, init, text, arranged) => {
  let e = map.get(id);
  if (!e) map.set(id, (e = { id, concerts: new Set(), texts: new Map(), rows: 0, arrangedRows: 0, ...init }));
  e.concerts.add(concert);
  if (text) e.texts.set(text, (e.texts.get(text) || 0) + 1);
  e.rows++;
  if (arranged) e.arrangedRows++;
};
for (const c of data.concerts) {
  for (const row of c.program || []) {
    const p = programPiece(row);
    if (!isComposerName(p.composer)) continue;
    add(composers, localComposerId(p), c.id, { keyed: !!p.composer_key }, p.composer);
    const wid = localWorkId(p);
    if (wid) add(works, wid, c.id, { cid: localComposerId(p), keyed: !!p.work_key, composer_key: p.composer_key }, p.work, arrangerLine(row.raw_text || ""));
  }
  for (const a of c.artists || []) {
    if (!personDim(a.role)) continue;
    const id = nameFold(a.name_display);
    if (id) add(people, id, c.id, {}, a.name_display);
  }
}
const out = (map) => [...map.values()].map(({ rows, arrangedRows, ...e }) => ({ ...e, rows, arranged_rows: arrangedRows, arranged: arrangedRows > 0 && arrangedRows === rows, n: e.concerts.size, concerts: undefined, texts: [...e.texts].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([t]) => t) }))
  .sort((a, b) => b.n - a.n || (a.id < b.id ? -1 : 1));
console.log(JSON.stringify({ works: out(works), composers: out(composers), people: out(people) }));
