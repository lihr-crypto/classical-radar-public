// The list routes of src/classical_radar/web/app.js: only the block between the two <route-rules> comments is evaluated (it must stay free of DOM and globals).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const js = readFileSync(join(root, "src/classical_radar/web/app.js"), "utf8");
const m = js.match(/\/\/ <route-rules>([\s\S]*?)\/\/ <\/route-rules>/);
assert.ok(m, "app.js must contain the // <route-rules> … // </route-rules> block");
const { listRoute, browseRoute, seasonRoute } = new Function(`${m[1]}\nreturn { listRoute, browseRoute, seasonRoute };`)();

let n = 0;
const ok = (name, fn) => { fn(); n++; };

ok("the three lists are routes", () => {
  assert.deepEqual(listRoute("presenter"), { name: "list", arg: "presenter" });
  assert.deepEqual(listRoute("piano", null), { name: "list", arg: "piano" });
  assert.deepEqual(listRoute("orchestra", null), { name: "list", arg: "orchestra" });
});
ok("an orchestra's own list carries its id in the route, so a copied link, a new tab or a reload shows the same page", () => {
  assert.deepEqual(listRoute("orchestra", "nhkso"), { name: "list", arg: "orchestra", sub: "nhkso" });
  assert.deepEqual(listRoute("orchestra", "ov-berlin-phil"), { name: "list", arg: "orchestra", sub: "ov-berlin-phil" });
});
ok("the season page's 全部公演 link names the season: #list/orchestra/<id>/<year>, and a year of the wrong shape is simply not there (ADR-0020)", () => {
  assert.deepEqual(listRoute("orchestra", "nhkso", "2027"), { name: "list", arg: "orchestra", sub: "nhkso", season: 2027 });
  for (const bad of ["", null, undefined, "27", "2027x", "20277", "abcd", "1999", "-2027", "2027.5", "<script>"]) assert.deepEqual(listRoute("orchestra", "nhkso", bad), { name: "list", arg: "orchestra", sub: "nhkso" }, String(bad));
  assert.deepEqual(listRoute("orchestra", null, "2027"), { name: "list", arg: "orchestra" }, "a season needs its orchestra");
  assert.deepEqual(listRoute("orchestra", "N響", "2027"), { name: "list", arg: "orchestra" }, "and an id that is not an id drops it too");
  assert.deepEqual(listRoute("piano", "nhkso", "2027"), { name: "list", arg: "piano" }, "only the orchestra list takes a season");
  assert.equal(listRoute("toString", "nhkso", "2027"), null);
});
ok("a sub-route only exists for the orchestra list", () => {
  assert.deepEqual(listRoute("piano", "nhkso"), { name: "list", arg: "piano" });
  assert.deepEqual(listRoute("presenter", "nhkso"), { name: "list", arg: "presenter" });
});
ok("an id that could not be an organisation id is ignored, and the merged list is shown", () => {
  for (const bad of ["", "N響", "../x", "a b", "NHKSO", "x".repeat(60), "<script>"]) assert.deepEqual(listRoute("orchestra", bad), { name: "list", arg: "orchestra" }, bad);
});
ok("anything that is not one of the three lists is not a list route (prototype names included)", () => {
  for (const bad of [null, undefined, "", "Orchestra", "concert", "toString", "constructor", "__proto__", "hasOwnProperty"]) assert.equal(listRoute(bad, "nhkso"), null, String(bad));
});

ok("the four browse kinds are routes: an index, and one entry of it carried in the address", () => {
  for (const dim of ["conductor", "performer", "composer", "work"]) {
    assert.deepEqual(browseRoute(dim, null), { name: "browse", arg: dim });
    assert.deepEqual(browseRoute(dim, "佐渡裕"), { name: "browse", arg: dim, sub: "佐渡裕" });
  }
  assert.deepEqual(browseRoute("work", "beethoven:symphony-9"), { name: "browse", arg: "work", sub: "beethoven:symphony-9" });
  assert.deepEqual(browseRoute("work", "~beethoven|交響曲第9番"), { name: "browse", arg: "work", sub: "~beethoven|交響曲第9番" });
});
ok("anything that is not one of the four kinds is not a browse route (prototype names included); a missing id from a malformed % address is the index or nothing", () => {
  for (const bad of [null, undefined, "", "Composer", "concert", "orchestra", "toString", "constructor", "__proto__", "hasOwnProperty", "composer/x"]) assert.equal(browseRoute(bad, "x"), null, String(bad));
  assert.deepEqual(browseRoute("composer", null), { name: "browse", arg: "composer" });  // parseRoute turns a malformed % into arg=null, so the route is dropped before it gets here
  assert.deepEqual(browseRoute("composer", ""), { name: "browse", arg: "composer" });
});
ok("an id that is too long or holds a control character shows the index instead of a page", () => {
  for (const bad of ["x".repeat(201), "a\u0000b", "a\nb", "a\u007fb"]) assert.deepEqual(browseRoute("conductor", bad), { name: "browse", arg: "conductor" }, JSON.stringify(bad).slice(0, 20));
  assert.deepEqual(browseRoute("conductor", "x".repeat(200)), { name: "browse", arg: "conductor", sub: "x".repeat(200) });
  assert.deepEqual(browseRoute("composer", "<script>alert(1)</script>"), { name: "browse", arg: "composer", sub: "<script>alert(1)</script>" });  // allowed: it is only ever matched against names and shown as text
});

ok("the season page keeps its orchestra and season in the address; anything of the wrong shape is simply not chosen", () => {
  assert.deepEqual(seasonRoute(null, null), { name: "season", arg: null, sub: null });
  assert.deepEqual(seasonRoute("all", null), { name: "season", arg: null, sub: null });
  assert.deepEqual(seasonRoute("nhkso", null), { name: "season", arg: "nhkso", sub: null });
  assert.deepEqual(seasonRoute("nhkso", "2027"), { name: "season", arg: "nhkso", sub: 2027 });
  assert.deepEqual(seasonRoute("all", "2026"), { name: "season", arg: null, sub: 2026 });
  for (const bad of ["N響", "../x", "a b", "NHKSO", "x".repeat(60), "<script>", "toString", "__proto__"]) assert.equal(seasonRoute(bad, null).arg, null, bad);
  for (const bad of ["27", "20270", "abcd", "2027 ", "-2027", "1999", ""]) assert.equal(seasonRoute("nhkso", bad).sub, null, bad);
});

console.log(`${n} route checks passed`);
