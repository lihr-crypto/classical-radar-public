// The calendar's month moves of src/classical_radar/web/app.js: only the block between the two <cal-nav> comments is evaluated
// (it must stay free of DOM and globals).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const js = readFileSync(join(root, "src/classical_radar/web/app.js"), "utf8");
const m = js.match(/\/\/ <cal-nav>([\s\S]*?)\/\/ <\/cal-nav>/);
assert.ok(m, "app.js must contain the // <cal-nav> … // </cal-nav> block");
const { stepMonth, swipeDir, inEdge } = new Function(`${m[1]}\nreturn { stepMonth, swipeDir, inEdge };`)();

let n = 0;
const ok = (name, fn) => { fn(); n++; };
const first = (y, mo) => new Date(Date.UTC(y, mo - 1, 1));
const key = (d) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;

ok("one step forward and back stays inside the year", () => {
  assert.equal(key(stepMonth(first(2026, 6), 1)), "2026-07-01");
  assert.equal(key(stepMonth(first(2026, 6), -1)), "2026-05-01");
});
ok("December + 1 is January of the next year", () => assert.equal(key(stepMonth(first(2026, 12), 1)), "2027-01-01"));
ok("January - 1 is December of the last year", () => assert.equal(key(stepMonth(first(2026, 1), -1)), "2025-12-01"));
ok("the result is always the 1st, even from a month with 31 days into one with 28", () => {
  assert.equal(key(stepMonth(first(2026, 1), 1)), "2026-02-01");
  assert.equal(key(stepMonth(first(2026, 3), -1)), "2026-02-01");
});
ok("quick taps add up: each step starts from the month the last one reached", () => {
  let cur = first(2026, 11);
  for (const d of [1, 1, 1]) cur = stepMonth(cur, d);  // Nov -> Dec -> Jan -> Feb, never "Dec three times"
  assert.equal(key(cur), "2027-02-01");
  for (const d of [-1, -1]) cur = stepMonth(cur, d);
  assert.equal(key(cur), "2026-12-01");
});
ok("stepping never changes the date it was given", () => {
  const from = first(2026, 4), before = from.getTime();
  stepMonth(from, 5);
  assert.equal(from.getTime(), before);
});
ok("a long sideways flick is a month swipe: left = next, right = previous", () => {
  assert.equal(swipeDir(-90, 5, 200), 1);
  assert.equal(swipeDir(90, -5, 200), -1);
  assert.equal(swipeDir(-48, 0, 600), 1);  // exactly on the thresholds still counts
});
ok("a short move, a mostly vertical move (a scroll) and a slow drag are not swipes", () => {
  assert.equal(swipeDir(-30, 0, 100), 0);
  assert.equal(swipeDir(-60, 80, 200), 0);
  assert.equal(swipeDir(-60, 45, 200), 0);  // 60 < 1.5 * 45: too diagonal
  assert.equal(swipeDir(-120, 0, 900), 0);
  assert.equal(swipeDir(0, 0, 50), 0);
});
ok("a touch that starts within 20px of either screen edge is left to the browser's back swipe", () => {
  assert.equal(inEdge(5, 390), true);
  assert.equal(inEdge(19, 390), true);
  assert.equal(inEdge(371, 390), true);
  assert.equal(inEdge(20, 390), false);
  assert.equal(inEdge(195, 390), false);
});

console.log(`${n} calendar navigation checks passed`);
