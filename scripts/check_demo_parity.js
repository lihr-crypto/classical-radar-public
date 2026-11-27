// node check_demo_parity.js DATA.json EXPECTED.json  -- runs demo.js against the same queries as the Python implementation
const fs = require("fs"), vm = require("vm"), path = require("path");
const [dataPath, expPath] = process.argv.slice(2);
const sandbox = { window: {}, localStorage: { getItem: () => null, setItem() {} }, URL, console };
sandbox.window.CR_DEMO_DATA = JSON.parse(fs.readFileSync(dataPath, "utf8"));
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/classical_radar/web/demo.js"), "utf8"), sandbox);
const demo = sandbox.window.CR_DEMO, exp = JSON.parse(fs.readFileSync(expPath, "utf8"));
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
let bad = 0, n = 0;
(async () => {
  for (const q of exp.queries) {
    n++;
    const r = await demo.handle("GET", "/discover?" + q.q);
    const got = { total: r.total, ids: r.items.map((i) => i.concert_id), perf_ids: r.items.map((i) => i.performance_ids), tickets: r.items.map((i) => i.ticket_status), groups: r.items.map((i) => i.region_group), orgs: r.items.map((i) => i.organization_id),
      pieces: r.items.map((i) => i.pieces), soloists: r.items.map((i) => i.soloists), conductors: r.items.map((i) => i.conductors) };  // the browse pages read these three
    for (const k of Object.keys(got)) if (!eq(got[k], q[k])) { bad++; console.log("MISMATCH", k, q.q, JSON.stringify(got[k]).slice(0, 120), "vs", JSON.stringify(q[k]).slice(0, 120)); }
  }
  const f1 = await demo.handle("GET", "/discover/facets"), f2 = await demo.handle("GET", "/discover/facets?composer=ベートーヴェン");
  [f1, f2].forEach((f, i) => { n++; const g = Object.fromEntries(Object.entries(f).filter(([k]) => k !== "filters")); if (!eq(g, exp.facets[i])) { bad++; console.log("MISMATCH facets", i); } });
  const cal = await demo.handle("GET", "/calendar?from=2026-11-01&to=2026-12-31");
  n++; if (!eq(cal.performances.map((p) => p.id), exp.calendar.perf) || !eq(cal.sales.map((s) => s.id), exp.calendar.sales) || !eq(cal.performances.map((p) => p.orchestras.map((o) => o.key)), exp.calendar.orch)) { bad++; console.log("MISMATCH calendar", cal.performances.length, exp.calendar.perf.length, cal.sales.length, exp.calendar.sales.length); }
  console.log(bad ? `PARITY FAILED: ${bad} mismatches in ${n} checks` : `PARITY OK: ${n} checks identical (${exp.queries.map((q) => q.total).join(",")})`);
  process.exit(bad ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
