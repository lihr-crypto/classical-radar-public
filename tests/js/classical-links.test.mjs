// The shipped Apple Music Classical table (src/classical_radar/web/classical-links.js, ADR-0013) read the way the browser reads it, through the
// pure rule of app.js: every entry must give a real address on the fixed host, and nothing the table does not hold may give one.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const web = join(root, "src/classical_radar/web");
const js = readFileSync(join(web, "app.js"), "utf8");
const m = js.match(/\/\/ <browse-rules>([\s\S]*?)\/\/ <\/browse-rules>/);
assert.ok(m, "app.js must contain the // <browse-rules> … // </browse-rules> block");
const { classicalHref, nameFold, workFold } = new Function(`${m[1]}\nreturn { classicalHref, nameFold, workFold };`)();

const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(readFileSync(join(web, "classical-links.js"), "utf8"), sandbox);  // a plain script: it must run with nothing but `window`
const table = sandbox.window.CR_CLASSICAL;
assert.ok(table && typeof table === "object", "classical-links.js sets window.CR_CLASSICAL");

let n = 0;
const ok = (name, fn) => { fn(); n++; };
const BASE = "https://classical.music.apple.com/jp/";

ok("every composer, piece and person in the table gives an address on the fixed host, and nothing else does", () => {
  let links = 0;
  const check = (dim, id, expected) => {
    const href = classicalHref(dim, id, table);
    assert.equal(href, expected, `${dim}/${id}`);
    const u = new URL(href);
    assert.ok(u.protocol === "https:" && u.hostname === "classical.music.apple.com" && !u.search && !u.hash && !href.includes("search"), href);
    links++;
  };
  for (const [id, v] of Object.entries(table.composers)) check("composer", id, BASE + "artist/" + v);
  for (const [id, v] of Object.entries(table.works)) check("work", id, BASE + "work/" + v);
  for (const [id, v] of Object.entries(table.people)) { check("conductor", id, BASE + "artist/" + v); check("performer", id, BASE + "artist/" + v); }
  assert.equal(links, Object.keys(table.composers).length + Object.keys(table.works).length + 2 * Object.keys(table.people).length);
});
ok("a person's key is the folded name, so every spelling of it finds the same page", () => {
  for (const id of Object.keys(table.people)) assert.equal(nameFold(id), id, id);
});
ok("a titled piece's key is a local id whose title part is already folded", () => {
  let titled = 0;
  for (const id of Object.keys(table.works)) {
    if (!id.startsWith("~")) continue;
    const i = id.indexOf("|");
    assert.ok(i > 1 && i < id.length - 1, id);
    assert.equal(workFold(id.slice(i + 1)), id.slice(i + 1), id);
    assert.ok(Object.prototype.hasOwnProperty.call(table.composers, id.slice(1, i)), `${id}: its composer is in the table`);
    titled++;
  }
  assert.ok(titled > 0, "the table holds titled pieces");
});
ok("a composer's key is never read as a piece, nor a piece's as a composer", () => {
  for (const id of Object.keys(table.composers)) assert.equal(classicalHref("work", id, table), null, id);
  for (const id of Object.keys(table.works)) assert.equal(classicalHref("composer", id, table), null, id);
});
ok("names the table does not hold give no address", () => {
  for (const [dim, id] of [["composer", "nobody"], ["work", "nobody:symphony-1"], ["conductor", "存在しない指揮者"], ["performer", "存在しない演奏家"], ["work", "~x|交響曲第1番"]]) assert.equal(classicalHref(dim, id, table), null);
});

console.log(`${n} classical link checks passed`);
