// The static page backend (demo.js) for tour leads: node leads.test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const lead = (id, extra) => ({ lead_id: "lead-" + id.repeat(20), orchestra_name: "X", orchestra: null, period_raw: "", date_from: null, date_to: null, month_hint: null, cities: [], more_cities: false,
  conductor: null, soloists: null, article_url: "https://okemin.com/x/", performances: [], last_changed_at: "2026-11-12T00:00:00+00:00", covered_by: null, ...extra });
const data = { concerts: [], alias: {}, orchestras: {}, coverage: { sources: [] }, as_of: "2026-11-12T01:00:00+00:00", fixed_as_of: true, snapshot_label: "x",
  leads: { source: { name: "オケミン！", url: "https://okemin.com/" }, as_of: "2026-11-12", leads: [
    lead("a", { date_from: "2027-01-07", date_to: "2027-01-17" }), lead("b", { date_from: "2026-01-01", date_to: "2026-01-05" }),
    lead("c", { month_hint: "2027-11" }), lead("d", { month_hint: "2026-03" }), lead("e", { date_from: "2027-02-01", date_to: "2027-02-02", covered_by: "concert-1" })] } };
const sandbox = { window: { CR_DEMO_DATA: data }, localStorage: { getItem: () => null, setItem() {} }, URL, console };
vm.createContext(sandbox);
vm.runInContext(readFileSync(join(root, "src/classical_radar/web/demo.js"), "utf8"), sandbox);
const get = (path) => sandbox.window.CR_DEMO.handle("GET", path);
let n = 0;
const ok = (cond, name) => { assert.ok(cond, name); n++; };

const page = await get("/leads");
ok(page.items.map((x) => x.lead_id[5]).join("") === "ace", "past leads (a day range and a month) are not listed; ongoing and month-only future ones are");
ok(page.source.name === "オケミン！" && page.notice.includes("未经官方核实"), "credit and the unverified notice");
ok(page.items.find((x) => x.lead_id[5] === "e").covered_by === "concert-1", "the covered flag is passed through");
const one = await get("/leads/" + "lead-" + "a".repeat(20));
ok(one.date_from === "2027-01-07", "one lead by id");
await assert.rejects(() => get("/leads/lead-" + "b".repeat(20)), "a past lead is gone");
await assert.rejects(() => get("/leads/not-a-lead"), "not an id");
await assert.rejects(() => get("/concerts/lead-" + "a".repeat(20)), "a lead id never resolves as a concert");
n += 3;
console.log(`${n} checks passed`);
