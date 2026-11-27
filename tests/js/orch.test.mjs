// The orchestra filter rules of src/classical_radar/web/app.js (calendar and search share them): only the block between
// the two <orch-rules> comments is evaluated (it must stay free of DOM and globals).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const js = readFileSync(join(root, "src/classical_radar/web/app.js"), "utf8");
const m = js.match(/\/\/ <orch-rules>([\s\S]*?)\/\/ <\/orch-rules>/);
assert.ok(m, "app.js must contain the // <orch-rules> … // </orch-rules> block");
const { SEVEN_ORDER, orchMatch, onlySeven } = new Function(`${m[1]}\nreturn { SEVEN_ORDER, orchMatch, onlySeven };`)();

let n = 0;
const ok = (name, fn) => { fn(); n++; };
const o = (key, display = key) => ({ key, display, origin: "x" });

ok("no selection shows everything, including rows with no known orchestra", () => {
  assert.equal(orchMatch([], new Set()), true);
  assert.equal(orchMatch(undefined, new Set()), true);
});
ok("several selected: a row matches when ANY of them plays (OR), never needs all", () => {
  const sel = new Set(["nhkso", "tmso"]);
  assert.equal(orchMatch([o("nhkso")], sel), true);
  assert.equal(orchMatch([o("tmso"), o("ov-lso")], sel), true);
  assert.equal(orchMatch([o("tso")], sel), false);
});
ok("a row with no known orchestra is hidden while a filter is on", () => {
  assert.equal(orchMatch([], new Set(["nhkso"])), false);
  assert.equal(orchMatch(undefined, new Set(["nhkso"])), false);
});
ok("the chips are exactly the seven, in their fixed order", () => {
  assert.deepEqual(SEVEN_ORDER, ["nhkso", "tmso", "tso", "jpo", "njp", "yomikyo", "tpo"]);
});
ok("a stale key outside the seven is dropped, so a filter never hides every row while no chip is lit", () => {
  const sel = new Set(["ov-bpo", "tmso"]);
  assert.equal(onlySeven(sel), sel, "it cleans the set it was given");
  assert.deepEqual([...sel], ["tmso"]);
  const stale = onlySeven(new Set(["ov-bpo"]));
  assert.equal(stale.size, 0);
  assert.equal(orchMatch([o("nhkso")], stale), true, "with nothing left the filter is off and every row shows");
  assert.deepEqual([...onlySeven(new Set())], []);
});
console.log(`${n} checks passed`);
