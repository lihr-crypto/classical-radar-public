// The browse rules of src/classical_radar/web/app.js (conductors, soloists, composers, pieces; ADR-0010): only the block between the two <browse-rules>
// comments is evaluated (it must stay free of DOM and globals). Fixed cases carry the guarantees; the run over the real data file is an extra check.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const js = readFileSync(join(root, "src/classical_radar/web/app.js"), "utf8");
const m = js.match(/\/\/ <browse-rules>([\s\S]*?)\/\/ <\/browse-rules>/);
assert.ok(m, "app.js must contain the // <browse-rules> … // </browse-rules> block");
const R_ = new Function(`${m[1]}\nreturn { bfold, nameFold, workFold, pageFold, creditless, sameListing, coreOf, isSpecific, COMPOSER_ALIAS, isComposerName, personDim, personHref, composerHref, workHref, programPiece, browseHref, classicalHref, searchTerm, classicalSearchHref, classicalIds, makeResolver, entriesOf, matchesEntity, buildIndex, entryHay, localWorkId, localComposerId };`)();
const { bfold, nameFold, workFold, pageFold, creditless, sameListing, coreOf, isSpecific, COMPOSER_ALIAS, classicalIds, isComposerName, personDim, personHref, composerHref, workHref, programPiece, classicalHref, searchTerm, classicalSearchHref, makeResolver, entriesOf, matchesEntity, buildIndex, entryHay, localWorkId, localComposerId } = R_;

let n = 0;
const failed = [];
const ok = (name, fn) => { try { fn(); n++; } catch (e) { failed.push(`${name}\n    ${String(e.message).split("\n").slice(0, 6).join("\n    ")}`); } };
const piece = (composer, work, composer_key = null, work_key = null) => ({ composer, composer_key, work, work_key });
const card = (id, o = {}) => ({ concert_id: id, conductors: [], soloists: [], pieces: [], ...o });
const idOf = (href) => decodeURIComponent(href.split("/").slice(2).join("/"));

ok("spelling variants of one name fold together: spaces, dots, middle dots, width, case, accents, the dash used for ー", () => {
  const same = [["佐渡裕", "佐渡 裕"], ["J.シュトラウスII世", "J. シュトラウス II世"], ["ダニール・トリフォノフ", "ダニ―ル・トリフォノフ"], ["ダニール・トリフォノフ", "ダニ—ル・トリフォノフ"],
    ["Dvořák", "dvorak"], ["ｂｒａｈｍｓ", "Brahms"], ["ヴィラ=ロボス", "ヴィラ＝ロボス"], ["ジャン･フェリ", "ジャン・フェリ"], ["ガ", "ガ"]];
  for (const [a, b] of same) assert.equal(bfold(a), bfold(b), `${a} / ${b}`);
  assert.equal(bfold(bfold("ダニ―ル・ガ")), bfold("ダニ―ル・ガ"), "folding twice changes nothing");
  assert.equal(bfold("a|b"), "ab", "the pipe is the separator of a piece id and never part of a folded text");
  assert.equal(bfold(null), "");
});
ok("two different spellings are two names: nothing is merged by similarity", () => {
  assert.notEqual(bfold("北村陽"), bfold("北村陽子"));
  assert.notEqual(bfold("小林研一郎"), bfold("小林"));
  assert.notEqual(bfold("シュトラウス"), bfold("J.シュトラウスII世"));
});
ok("a composer field that is a note or a title is neither listed nor linked", () => {
  for (const bad of ["作曲", "振付", "(ロンドン・フィルハーモニー管弦楽団", "（ヴァイオリン独奏", "◎オルガン・プレコンサート 13", "團伊玖磨作曲/木下順二作", "J.シュトラウスII世/ヨーゼフ・シュトラウス", "世界三大ヴァイオリンメドレー(ベートーヴェン", "", "  ", null]) assert.equal(isComposerName(bad), false, String(bad));
  for (const good of ["ベートーヴェン", "J.シュトラウスII世", "J. シュトラウス II世", "ヴィラ=ロボス", "Antonín Dvořák", "藤倉大"]) assert.equal(isComposerName(good), true, good);
});
ok("a role goes to its own page; orchestras, choruses and stray names (role other) are not linked", () => {
  assert.equal(personDim("conductor"), "conductor");
  assert.equal(personDim("recital_headliner"), "performer");
  assert.equal(personDim("concerto_soloist"), "performer");
  for (const bad of ["other", "", null, undefined, "toString", "__proto__", "constructor"]) assert.equal(personDim(bad), null, String(bad));
  assert.equal(personHref("other", "新国立劇場合唱団"), null);
  assert.equal(personHref("conductor", "  "), null);
  assert.equal(personHref("conductor", "佐渡 裕"), "#browse/conductor/" + encodeURIComponent(bfold("佐渡裕")));
});

ok("a keyed and an unkeyed row with the same spelling land on ONE composer page, from either side", () => {
  const items = [card("a", { pieces: [piece("ベートーヴェン", "交響曲第5番", "beethoven", "beethoven:symphony-5")] }), card("b", { pieces: [piece("ベートーヴェン", "弦楽四重奏曲 第14番")] })];
  const R = makeResolver(items);
  assert.equal(R.composerId(items[1].pieces[0]), "beethoven");
  assert.equal(R.canon("composer", localComposerId(items[1].pieces[0])), "beethoven");  // the detail link of the unkeyed row (its own spelling) is canonicalised
  for (const it of items) assert.equal(matchesEntity(it, "composer", localComposerId(items[1].pieces[0]), R), true);
  assert.equal(buildIndex(items, "composer", R).length, 1);
  assert.equal(buildIndex(items, "composer", R)[0].n, 2);
});
ok("one folded spelling that carries two different keys is NOT joined to either (no guessed merge); the unkeyed row keeps its own spelling", () => {
  const items = [card("a", { pieces: [piece("シュトラウス", "x", "r-strauss")] }), card("b", { pieces: [piece("シュトラウス", "y", "j-strauss-ii")] }), card("c", { pieces: [piece("シュトラウス", "z")] })];
  const R = makeResolver(items);
  assert.equal(R.composerId(items[2].pieces[0]), bfold("シュトラウス"));
  const ids = buildIndex(items, "composer", R).map((e) => e.id).sort();
  assert.deepEqual(ids, ["j-strauss-ii", "r-strauss", bfold("シュトラウス")].sort());
  assert.equal(matchesEntity(items[2], "composer", "r-strauss", R), false);
  assert.equal(matchesEntity(items[0], "composer", "r-strauss", R), true);
  // the order the cards arrive in never changes the outcome
  const R2 = makeResolver([...items].reverse());
  assert.equal(R2.composerId(items[2].pieces[0]), bfold("シュトラウス"));
});
ok("an unkeyed piece joins a keyed piece only when composer and title match and the match is unambiguous", () => {
  const keyed = piece("ベートーヴェン", "交響曲 第9番", "beethoven", "beethoven:symphony-9"), same = piece("ベートーヴェン", "交響曲　第9番"), other = piece("ベートーヴェン", "交響曲 第8番");
  const R = makeResolver([card("a", { pieces: [keyed] }), card("b", { pieces: [same, other] })]);
  assert.equal(R.workId(same), "beethoven:symphony-9");
  assert.equal(R.workId(other), "~beethoven|" + bfold("交響曲 第8番"));
  assert.equal(R.canon("work", localWorkId(same)), "beethoven:symphony-9");
  // the same composer+title under two different work keys is ambiguous: the unkeyed row is left alone
  const R2 = makeResolver([card("a", { pieces: [piece("ブラームス", "ハンガリー舞曲", "brahms", "brahms:hd-a")] }), card("b", { pieces: [piece("ブラームス", "ハンガリー舞曲", "brahms", "brahms:hd-b")] }), card("c", { pieces: [piece("ブラームス", "ハンガリー舞曲")] })]);
  assert.equal(R2.workId(piece("ブラームス", "ハンガリー舞曲")), "~brahms|" + pageFold("ハンガリー舞曲"));  // the page id drops the long-vowel mark (ADR-0019)
});
ok("a pipe inside a composer or a title cannot break the piece id", () => {
  const p = piece("A|B", "x|y|z"), R = makeResolver([card("a", { pieces: [p] })]);
  const id = R.workId(p), want = "~" + bfold("A|B") + "|" + bfold("x|y|z");
  assert.equal(id, want);
  assert.equal(R.canon("work", id), id);
  assert.equal(R.canon("work", localWorkId(p)), id);
  assert.equal(matchesEntity(card("a", { pieces: [p] }), "work", id, R), true);
});

ok("the index counts DISTINCT concerts, writes the most used spelling, and keeps different names apart", () => {
  const items = [
    card("a", { conductors: ["佐渡裕"], soloists: ["北村陽"], pieces: [piece("ラヴェル", "ボレロ"), piece("ラヴェル", "ボレロ")] }),
    card("b", { conductors: ["佐渡 裕"], soloists: ["北村陽子"], pieces: [piece("ラヴェル", "ボレロ")] }),
    card("c", { conductors: ["佐渡裕"], soloists: ["北村陽"], pieces: [piece("◎オルガン・プレコンサート 13", "x"), piece("作曲", "y")] }),
  ];
  const R = makeResolver(items), cond = buildIndex(items, "conductor", R);
  assert.deepEqual(cond.map((e) => [e.label, e.n]), [["佐渡裕", 3]]);
  assert.deepEqual(buildIndex(items, "performer", R).map((e) => [e.label, e.n]).sort(), [["北村陽", 2], ["北村陽子", 1]]);
  const comp = buildIndex(items, "composer", R);
  assert.deepEqual(comp.map((e) => [e.label, e.n]), [["ラヴェル", 2]], "junk composers are left out, a piece listed twice in one programme counts once");
  assert.deepEqual(buildIndex(items, "work", R).map((e) => [e.label, e.sub, e.n]), [["ボレロ", "ラヴェル", 2]]);
});
ok("a page matches exactly: 北村陽 does not list 北村陽子, and a conductor page does not list soloists", () => {
  const a = card("a", { soloists: ["北村陽"], conductors: ["沼尻竜典"] }), b = card("b", { soloists: ["北村陽子"] }), R = makeResolver([a, b]);
  assert.equal(matchesEntity(a, "performer", bfold("北村陽"), R), true);
  assert.equal(matchesEntity(b, "performer", bfold("北村陽"), R), false);
  assert.equal(matchesEntity(a, "conductor", bfold("北村陽"), R), false);
  assert.equal(matchesEntity(a, "performer", "北村 陽", R), true, "a hand-typed address with spaces still folds to the same page");
});
ok("typing in the index finds a composer or a piece by its reviewed key too", () => {
  const items = [card("a", { pieces: [piece("ブラームス", "交響曲 第4番 ホ短調 op.98", "brahms", "brahms:symphony-4"), piece("ラヴェル", "ボレロ")] })], R = makeResolver(items);
  const comp = buildIndex(items, "composer", R), work = buildIndex(items, "work", R);
  assert.equal(entryHay(comp.find((e) => e.id === "brahms"), "composer").includes(bfold("brahms")), true);
  assert.equal(entryHay(work.find((e) => e.id === "brahms:symphony-4"), "work").includes(bfold("brahms")), true);
  assert.equal(entryHay(work.find((e) => e.label === "ボレロ"), "work").includes(bfold("ブラームス")), false, "a work of another composer is not found through his name");
  assert.equal(entryHay(comp.find((e) => e.label === "ラヴェル"), "composer").includes("ravel"), false, "an unkeyed spelling adds nothing but itself");
});

ok("links are built from the roles and are encoded, so no name can add a path segment", () => {
  assert.equal(composerHref(piece("作曲", "x")), null);
  assert.equal(workHref(piece("ベートーヴェン", "   ")), null);
  assert.equal(composerHref(piece("ベートーヴェン", "x", "beethoven")), "#browse/composer/beethoven");
  assert.equal(workHref(piece("ベートーヴェン", "x", "beethoven", "beethoven:symphony-9")), "#browse/work/beethoven%3Asymphony-9");
  const h = workHref(piece("ラヴェル", "a/b?c#d"));
  assert.equal(h.split("/").length, 3, h);
  assert.equal(programPiece({ composer_display: "X", work_display: null, raw_text: "X：曲", composer_key: undefined, work_key: undefined }).work, "X：曲");
});

// A link on the detail page must land on a page that lists that very concert. Checked on fixed cards and, as an extra, on the real data file.
function everyLinkLandsOnAPageThatListsTheConcert(concerts) {
  const items = concerts.map((c) => ({ concert_id: c.id, conductors: c.artists.filter((a) => a.role === "conductor").map((a) => a.name_display), soloists: c.artists.filter((a) => a.role === "recital_headliner" || a.role === "concerto_soloist").map((a) => a.name_display),
    pieces: c.program.map(programPiece) }));
  const R = makeResolver(items);
  let links = 0;
  concerts.forEach((c, i) => {
    const it = items[i];
    for (const a of c.artists) {
      const href = personHref(a.role, a.name_display);
      if (!href) { assert.equal(personDim(a.role), null, `${a.name_display} has no link only when its role is not a person role`); continue; }
      links++;
      assert.equal(matchesEntity(it, href.split("/")[1], idOf(href), R), true, `${c.id}: ${a.name_display}`);
    }
    for (const p of it.pieces) {
      const ch = composerHref(p), wh = workHref(p);
      if (ch) { links++; assert.equal(matchesEntity(it, "composer", idOf(ch), R), true, `${c.id}: composer ${p.composer}`); }
      if (wh) { links++; assert.equal(matchesEntity(it, "work", idOf(wh), R), true, `${c.id}: work ${p.work}`); assert.equal(R.canon("work", idOf(wh)), R.rowsOf(it).find((r) => r.p === p).id, `${c.id}: ${p.work}`); }
      assert.equal(Boolean(ch), isComposerName(p.composer) && Boolean(localComposerId(p)), "a composer link exists exactly when the index lists the composer");
    }
  });
  // every index entry's page lists exactly the concerts the entry counted
  for (const dim of ["conductor", "performer", "composer", "work"]) for (const e of buildIndex(items, dim, R)) {
    const page = items.filter((it) => matchesEntity(it, dim, e.id, R)).length;
    assert.equal(page, e.n, `${dim} ${e.label}: the index says ${e.n}, the page lists ${page}`);
  }
  return links;
}
ok("every detail link lands on a page that lists the concert (fixed cards)", () => {
  const links = everyLinkLandsOnAPageThatListsTheConcert([
    { id: "a", artists: [{ name_display: "佐渡 裕", role: "conductor" }, { name_display: "北村陽", role: "concerto_soloist" }, { name_display: "東響コーラス", role: "other" }],
      program: [{ composer_display: "ベートーヴェン", composer_key: "beethoven", work_display: "交響曲第9番", work_key: "beethoven:symphony-9", raw_text: "" }, { composer_display: "J. シュトラウス II世", composer_key: null, work_display: "皇帝円舞曲", work_key: null, raw_text: "" }] },
    { id: "b", artists: [{ name_display: "佐渡裕", role: "conductor" }], program: [{ composer_display: "ベートーヴェン", composer_key: null, work_display: "交響曲 第9番", work_key: null, raw_text: "" }, { composer_display: "作曲", composer_key: null, work_display: "y", work_key: null, raw_text: "" }, { composer_display: "J.シュトラウスII世", composer_key: "j-strauss-ii", work_display: "皇帝円舞曲", work_key: null, raw_text: "" }] },
  ]);
  assert.ok(links >= 8, String(links));
});
const real = join(root, "site-data/concerts.json");
ok("every detail link lands on a page that lists the concert (the real data file, when present)", () => {
  if (!existsSync(real)) return;
  const links = everyLinkLandsOnAPageThatListsTheConcert(JSON.parse(readFileSync(real, "utf8")).concerts);
  assert.ok(links > 500, String(links));
});

ok("the Apple Music Classical link is the page of that composer / piece / person, taken from the reviewed table; no table entry = no link", () => {
  const base = "https://classical.music.apple.com/jp/";
  const table = { composers: { brahms: 264688 }, works: { "brahms:symphony-4": "johannes-brahms-1833-pp4" }, people: { 藤岡幸夫: 265293859, "381": "381" } };
  assert.equal(classicalHref("composer", "brahms", table), base + "artist/264688");
  assert.equal(classicalHref("work", "brahms:symphony-4", table), base + "work/johannes-brahms-1833-pp4");
  assert.equal(classicalHref("conductor", "藤岡幸夫", table), base + "artist/265293859");
  assert.equal(classicalHref("performer", "藤岡幸夫", table), base + "artist/265293859", "conductors and soloists share the people table");
  assert.equal(classicalHref("composer", "tchaikovsky", table), null, "a composer the table does not know");
  assert.equal(classicalHref("work", "~brahms|交響曲第4番", table), null, "a piece with no reviewed key can never be in the table");
  assert.equal(classicalHref("conductor", "佐渡裕", table), null);
  assert.equal(classicalHref("work", "brahms", table), null, "a composer id is not looked up among the pieces");
  assert.equal(classicalHref("composer", "brahms", undefined), null, "classical-links.js did not load");
  assert.equal(classicalHref("composer", "brahms", {}), null);
  assert.equal(classicalHref("composer", "brahms", { composers: null }), null);
  assert.equal(classicalHref("composer", "brahms", { composers: "brahms" }), null, "a table of the wrong shape");
  assert.equal(classicalHref("album", "brahms", table), null, "only the four page kinds");
  for (const bad of ["constructor", "__proto__", "toString", "hasOwnProperty"]) {
    for (const dim of ["composer", "work", "conductor", "performer"]) assert.equal(classicalHref(dim, bad, table), null, `${dim}/${bad}`);
  }
  assert.equal(classicalHref("constructor", "brahms", table), null);
  assert.equal(classicalHref("__proto__", "brahms", table), null);
  // a wrong-shaped id never reaches an address, so a bad table entry cannot inject a path, a query or another host
  const evil = { composers: { a: "1/../../x", b: "12?q=1", c: "https://evil.example/1", d: "", e: 0, f: -5, g: "1234567890123", h: 1.5, i: null, j: "007", k: "0" }, works: { a: "A-B", b: "x", c: "ok-slug/../y", d: "a b c", e: "a".repeat(101), f: "slug?x=1", g: "slug#h", h: 7 }, people: { a: "٣٤٥" } };
  for (const k of "abcdefghijk") assert.equal(classicalHref("composer", k, evil), null, `composer ${k}`);
  for (const k of "abcdefgh") assert.equal(classicalHref("work", k, evil), null, `work ${k}`);
  assert.equal(classicalHref("performer", "a", evil), null, "digits of another script");
  assert.equal(classicalHref("composer", "a", { composers: { a: 5 } }), base + "artist/5");
  assert.equal(classicalHref("work", "a", { works: { a: "abc" } }), base + "work/abc", "the shortest slug");
  for (const href of [classicalHref("composer", "brahms", table), classicalHref("work", "brahms:symphony-4", table)]) {
    assert.ok(new URL(href).hostname === "classical.music.apple.com" && new URL(href).protocol === "https:" && !href.includes("search") && !href.includes("?"));
  }
});

ok("a piece without a page of its own opens the Classical app's search screen with composer and title in the q parameter (ADR-0019): the fixed base, one encoded term, nothing else", () => {
  const base = "https://classical.music.apple.com/jp/search?q=";
  assert.equal(classicalSearchHref("狂詩曲「タラス・ブーリバ」"), base + encodeURIComponent("狂詩曲「タラス・ブーリバ」"));
  assert.equal(classicalSearchHref("  交響曲　第5番 \n ハ短調  "), base + encodeURIComponent("交響曲 第5番 ハ短調"), "one line, single spaces");
  assert.equal(searchTerm("a\u0000b\u001fc\u007fd\u2028e"), "a b c d e", "control characters become spaces");
  for (const none of ["", "   ", "\n\t", null, undefined]) assert.equal(classicalSearchHref(none), null, JSON.stringify(none));
  assert.equal([...searchTerm("あ".repeat(250))].length, 100, "at most 100 characters");
  assert.equal([...searchTerm("😀".repeat(150))].length, 100, "cut by characters, never in the middle of a surrogate pair");
  assert.equal(classicalSearchHref("\ud83d"), null, "a lone surrogate cannot be encoded: no link, no crash");
  for (const evil of ["x&y=1", "a#b", "a?b=c", "https://evil.example/", "../../x", "a b/c", "%00"]) {
    const href = classicalSearchHref(evil), u = new URL(href);
    assert.ok(u.protocol === "https:" && u.hostname === "classical.music.apple.com" && u.pathname === "/jp/search" && [...u.searchParams.keys()].join() === "q" && u.hash === "", evil);
    assert.equal(u.searchParams.get("q"), searchTerm(evil), "the term reads back as typed: nothing is injected into the address");
  }
});
ok("an own Apple page is still looked up by the table only; a title with no table entry has no own page (the search button is for that case)", () => {
  const table = { composers: { brahms: 264688 }, works: { "brahms:symphony-4": "johannes-brahms-1833-pp4" } };
  assert.ok(classicalHref("work", ["brahms:symphony-4"], table));
  assert.equal(classicalHref("work", ["brahms:symphony-5", "~brahms|交響曲第5番"], table), null);
  assert.equal(classicalHref("work", ["brahms:symphony-5"], { composers: { brahms: 264688 }, works: {} }), null, "the composer's page is never offered for a piece any more");
});

// ---------- notation folding (ADR-0014) ----------
const allSame = (xs, fold = workFold) => { for (const x of xs) assert.equal(fold(x), fold(xs[0]), `${x} / ${xs[0]}`); };
const allApart = (xs, fold = workFold) => { const seen = new Map(); for (const x of xs) { const f = fold(x); assert.ok(f, x); assert.ok(!seen.has(f), `${x} and ${seen.get(f)} must stay two pieces`); seen.set(f, x); } };

ok("one piece written with different quote glyphs, opus markers, marks or brackets is ONE title", () => {
  allSame(["組曲《展覧会の絵》", "組曲「展覧会の絵」", "組曲『展覧会の絵』", "組曲〈展覧会の絵〉", "組曲 “展覧会の絵”", "組曲展覧会の絵"]);
  allSame(["幻想交響曲 op.14", "幻想交響曲 作品14", "幻想交響曲 Op. 14", "幻想交響曲 OP.14", "幻想交響曲 op14", "幻想交響曲　作品 14"]);
  allSame(["ボレロ", "「ボレロ」", "ボレロ*", "ボレロ ★", "ボレロ◇", "『ボレロ』※"]);
  allSame(["『リュッケルト歌曲集』(全5曲)", "リュッケルト歌曲集 全5曲", "リュッケルト歌曲集（全５曲）"]);
  allSame(["混声合唱のための「うた」から“小さな空”", "混声合唱のための「うた」から”小さな空”", "混声合唱のための『うた』から「小さな空」"]);
  allSame(["歌劇「蝶々夫人」より “ある晴れた日に”", "歌劇『蝶々夫人』より「ある晴れた日に」"]);
});
ok("what tells two pieces apart is never folded away: numbers, opus and catalogue numbers, keys, parts, the text inside brackets", () => {
  allApart(["幻想交響曲 op.14", "幻想交響曲 op.41", "幻想交響曲"]);
  allApart(["マンフレッド交響曲 ロ短調 op.58", "マンフレッド交響曲 op.58", "マンフレッド交響曲 ホ短調 op.58"]);
  allApart(["ヴォカリーズ", "ヴォカリーズ Op.34-14", "ヴォカリーズ Op.34-12"]);
  allApart(["ロンド ニ長調 K.485", "ロンド ヘ長調 K.494", "ロンド ニ長調 K.486"]);
  allApart(["交響曲第1番", "交響曲第11番", "交響曲第2番"]);
  allApart(["組曲「展覧会の絵」", "組曲「展覧会の絵」(M. ラヴェルによる管弦楽編)", "組曲「展覧会の絵」より プロムナード"]);
  allApart(["バレエ組曲「火の鳥」(1919年版)", "バレエ組曲「火の鳥」", "バレエ組曲「火の鳥」(1919年版)から"]);
  allApart(["幻想序曲「ロメオとジュリエット」", "幻想序曲「ロメオとジュリエット」 他"]);
  allApart(["ピアノ・ソナタ", "ピアノ・ソナタ 第14番", "ピアノ・ソナタ 第14番 嬰ハ短調 Op.27-2「月光」"]);
});
ok("a bracket between two digits stays a separator: op.10(12) is not op.101(2)", () => {
  allApart(["曲 op.10(12)", "曲 op.101(2)", "曲 op.1012"]);
  assert.equal(workFold("曲 op.10(12)"), "曲op10_12");
});
ok("workFold is idempotent, and an address written with the old fold lands on the new one", () => {
  for (const x of ["幻想交響曲 作品14", "組曲《展覧会の絵》", "ボレロ*", "曲 op.10(12)", "Op. 36", "歌劇「蝶々夫人」より “ある晴れた日に”", "ロンド ニ長調 K. 485", "", "  "]) assert.equal(workFold(workFold(x)), workFold(x), x);
  const R = makeResolver([card("a", { pieces: [piece("ベルリオーズ", "幻想交響曲 op.14", "berlioz"), piece("ラヴェル", "ボレロ", "ravel"), piece("ムソルグスキー", "組曲《展覧会の絵》", "mussorgsky")] })]);
  assert.equal(R.canon("work", "~berlioz|幻想交響曲作品14"), "~berlioz|幻想交響曲", "作品14 written before ADR-0014: the page id is the title without its opus (ADR-0019)");
  assert.equal(R.canon("work", "~berlioz|幻想交響曲op14"), "~berlioz|幻想交響曲", "the ADR-0014 address of the same piece");
  assert.equal(R.canon("work", "~ravel|「ボレロ」"), "~ravel|ボレロ");
  assert.equal(R.canon("work", "~ravel|ボレロ*"), "~ravel|ボレロ");
  assert.equal(R.canon("work", "~mussorgsky|組曲《展覧会の絵》"), "~mussorgsky|組曲展覧会の絵");
  assert.equal(R.canon("work", "beethoven:symphony-9"), "beethoven:symphony-9", "a reviewed work key is used as it is");
  assert.equal(R.canon("conductor", "藤岡幸夫"), "藤岡幸夫");
  assert.equal(R.canon("performer", "カミラ・ニールンド◇"), "カミラニールンド", "an address carrying a mark");
});
ok("names: a stray mark is no part of a person, but nothing else about names changes (still exact, never by similarity)", () => {
  assert.equal(nameFold("カミラ・ニールンド◇"), nameFold("カミラ・ニールンド"));
  assert.equal(nameFold("森麻季★"), nameFold("森麻季"));
  assert.equal(nameFold("クラウス・フロリアン・フォークト◆"), nameFold("クラウス・フロリアン・フォークト"));
  assert.notEqual(nameFold("北村陽"), nameFold("北村陽子"));
  assert.notEqual(nameFold("山田和樹"), nameFold("山田一雄"));
  assert.equal(nameFold("佐渡 裕"), bfold("佐渡 裕"), "no mark: exactly bfold");
  assert.equal(personHref("conductor", "カミラ・ニールンド◇"), personHref("conductor", "カミラ・ニールンド"));
  const items = [card("a", { soloists: ["カミラ・ニールンド◇"] }), card("b", { soloists: ["カミラ・ニールンド"] })], R = makeResolver(items);
  const idx = buildIndex(items, "performer", R);
  assert.equal(idx.length, 1);
  assert.equal(idx[0].n, 2);
});
ok("the browse index counts one entry for variants of a piece, labelled with the spelling written most often", () => {
  const items = [
    card("a", { pieces: [piece("ラヴェル", "ボレロ", "ravel")] }), card("b", { pieces: [piece("ラヴェル", "ボレロ", "ravel")] }), card("c", { pieces: [piece("ラヴェル", "「ボレロ」", "ravel")] }), card("d", { pieces: [piece("ラヴェル", "ボレロ*", "ravel")] }),
    card("e", { pieces: [piece("ラヴェル", "亡き王女のためのパヴァーヌ", "ravel")] }),
  ];
  const R = makeResolver(items), idx = buildIndex(items, "work", R);
  assert.deepEqual(idx.map((e) => [e.label, e.n]), [["ボレロ", 4], ["亡き王女のためのパヴァーヌ", 1]]);
  const id = idx[0].id;
  assert.equal(items.filter((it) => matchesEntity(it, "work", id, R)).length, 4, "its page lists all four concerts");
});
ok("a mark a scraped line carries is not shown in the name or title of an index entry", () => {
  const items = [card("a", { soloists: ["カミラ・ニールンド◇"], pieces: [piece("ラヴェル", "ボレロ ★", "ravel")] }), card("b", { soloists: ["森麻季★"] })];
  const R = makeResolver(items);
  assert.deepEqual(buildIndex(items, "performer", R).map((e) => e.label).sort(), ["カミラ・ニールンド", "森麻季"]);
  const w = buildIndex(items, "work", R);
  assert.equal(w[0].label, "ボレロ");
  assert.equal(w[0].id, "~ravel|ボレロ", "and the id never had it");
});
ok("the browse page tries every id the reviewed table might know: its own, the address, and the local id of each joined row; ids that disagree give no link", () => {
  const items = [card("a", { pieces: [piece("ブラームス", "交響曲第4番 ホ短調 作品98", "brahms", "brahms:symphony-4"), piece("ブラームス", "交響曲第4番 ホ短調 作品98", "brahms", null), piece("ラヴェル", "「ボレロ」", "ravel"), piece("ラヴェル", "ボレロ*", "ravel")] })];
  const R = makeResolver(items), base = "https://classical.music.apple.com/jp/work/";
  const ids = classicalIds("work", "brahms:symphony-4", "brahms:symphony-4", items, R);
  assert.deepEqual([...ids].sort(), ["brahms:symphony-4", "~brahms|交響曲第4番ホ短調op98"].sort(), "the row without a key was joined to the key: both its ids are tried");
  assert.equal(classicalHref("work", ids, { works: { "brahms:symphony-4": "johannes-brahms-1833-pp4" } }), base + "johannes-brahms-1833-pp4");
  assert.equal(classicalHref("work", ids, { works: { "~brahms|交響曲第4番ホ短調op98": "johannes-brahms-1833-pp4" } }), base + "johannes-brahms-1833-pp4", "the table knows only the local id");
  assert.equal(classicalHref("work", ids, { works: { "brahms:symphony-4": "johannes-brahms-1833-pp4", "~brahms|交響曲第4番ホ短調op98": "johannes-brahms-1833-pp4" } }), base + "johannes-brahms-1833-pp4", "two ids, one answer");
  assert.equal(classicalHref("work", ids, { works: { "brahms:symphony-4": "johannes-brahms-1833-pp4", "~brahms|交響曲第4番ホ短調op98": "johannes-brahms-1833-pp3" } }), null, "two ids, two answers: no button");
  const bolero = R.workId(items[0].pieces[2]);
  assert.deepEqual(classicalIds("work", bolero, "~ravel|「ボレロ」", items, R), [bolero, "~ravel|「ボレロ」"], "the id written in the address is tried too (the local ids of the two spellings fold to the same id)");
  assert.deepEqual(classicalIds("work", "~x|y", "~x|y", [], R), ["~x|y"], "nothing matched: the page id and the address still count");
  assert.deepEqual(classicalIds("conductor", "藤岡幸夫", "藤岡幸夫", items, R), ["藤岡幸夫"]);
  assert.deepEqual(classicalIds("composer", "ravel", "ravel", items, R), ["ravel"]);
  const junk = [card("z", { pieces: [piece("(編曲者)", "曲", "brahms", null)] })];
  assert.deepEqual(classicalIds("composer", "brahms", "brahms", junk, makeResolver(junk)), ["brahms"], "a junk composer field adds nothing");
});
ok("on the real data: variants merge, no keyed join is lost, and every entry is still one page that lists its own concerts", () => {
  if (!existsSync(real)) return;
  const items = JSON.parse(readFileSync(real, "utf8")).concerts.map((c) => card(c.id, { pieces: c.program.map((p) => ({ composer: p.composer_display || "", composer_key: p.composer_key || null, work: p.work_display || p.raw_text || "", work_key: p.work_key || null })) }));
  const R = makeResolver(items), idx = buildIndex(items, "work", R);
  // the same joins computed with the old fold: a piece that was joined to a key by its (composer, title) must still be
  const joins = (fold) => { const m = new Map(), bad = new Set(), cid = (p) => p.composer_key || nameFold(p.composer);
    for (const it of items) for (const p of it.pieces) if (isComposerName(p.composer) && p.work_key && fold(p.work)) { const k = cid(p) + "|" + fold(p.work); if (bad.has(k)) continue; if (m.has(k) && m.get(k) !== p.work_key) { m.delete(k); bad.add(k); } else m.set(k, p.work_key); }
    return { m, bad }; };
  const before = joins(bfold), after = joins(workFold);
  assert.ok(after.bad.size <= before.bad.size + 2, `the fold must not make ambiguity grow: ${before.bad.size} -> ${after.bad.size}`);
  for (const it of items) for (const p of it.pieces) if (isComposerName(p.composer) && !p.work_key && workFold(p.work)) {
    const old = before.m.get((p.composer_key || nameFold(p.composer)) + "|" + bfold(p.work));
    if (old) assert.equal(R.workId(p), old, `${p.work} was joined to ${old}`);
  }
  assert.equal(new Set(idx.map((e) => e.id)).size, idx.length);
  const seen = new Set();
  for (const e of idx) { const k = e.cid + "|" + workFold(e.label); assert.ok(e.id.startsWith("~") ? !seen.has(k) : true, `two entries for ${k}`); if (e.id.startsWith("~")) seen.add(k); }
  assert.ok(idx.length < 1059 && idx.length > 900, `entries: ${idx.length}`);
  for (const e of idx) { assert.equal(R.canon("work", e.id), e.id, `${e.label}: the page id of an entry is its own page`); assert.equal(items.filter((it) => matchesEntity(it, "work", e.id, R)).length, e.n, e.label); }
  for (const dim of ["composer", "conductor", "performer"]) for (const e of buildIndex(items, dim, R)) assert.equal(R.canon(dim, e.id), e.id, `${dim} ${e.label}`);
});


// ---------- composers and pieces written two ways (ADR-0019) ----------
const entryOf = (items, dim, label) => { const R = makeResolver(items); return { R, idx: buildIndex(items, dim, R), hit: buildIndex(items, dim, R).filter((e) => e.label === label) }; };
const ids = (items, dim) => buildIndex(items, dim, makeResolver(items)).map((e) => e.id);

ok("a composer written with initials, a generation or an arranger credit is the same entry as the plain name", () => {
  const items = [
    card("a", { pieces: [piece("チャイコフスキー", "交響曲 第5番", "tchaikovsky", "tchaikovsky:symphony-5"), piece("モーツァルト", "交響曲 第40番", "mozart", "mozart:symphony-40"), piece("リスト", "ラ・カンパネラ", "liszt"), piece("ブラームス", "交響曲 第1番", "brahms", "brahms:symphony-1")] }),
    card("b", { pieces: [piece("P. チャイコフスキー", "くるみ割り人形"), piece("P.I.チャイコフスキー", "白鳥の湖"), piece("W.A.モーツァルト(オスピタル編)", "フィガロ序曲"), piece("F.リスト", "愛の夢"), piece("J.ブラームス (阪田知樹 編曲)", "ハンガリー舞曲")] }),
  ];
  const R = makeResolver(items), idx = buildIndex(items, "composer", R);
  assert.deepEqual(idx.map((e) => [e.id, e.n]).sort(), [["brahms", 2], ["liszt", 2], ["mozart", 2], ["tchaikovsky", 2]]);
  for (const e of idx) assert.ok(!/[.(（]/.test(e.label), `no initials or credit in the shown name: ${e.label}`);
  for (const p of items[1].pieces) assert.ok(!p.composer_key && R.composerId(p) && !R.composerId(p).includes("("), p.composer);
  assert.equal(R.canon("composer", localComposerId(items[1].pieces[2])), "mozart", "the detail link of the credited row");
  assert.equal(R.composerText(items[1].pieces[4]), "J.ブラームス", "the credit is not shown as part of the name");
  assert.ok(classicalIds("composer", "mozart", "mozart", items, R).includes(localComposerId(items[1].pieces[2])), "the Apple table is asked with the stored spelling too");
  assert.equal(entriesOf(items[1], "composer", R).length, 5);
});
ok("without any keyed row loaded the reviewed list still holds; a cut-off bracket is dropped only when a known name is left", () => {
  const only = [card("a", { pieces: [piece("W.A.モーツァルト(オスピタル編)", "x"), piece("ラヴェル(志村和音", "y"), piece("映像と共に(チャップリン名作集", "z")] })], R = makeResolver(only);
  assert.equal(R.composerId(only[0].pieces[0]), "mozart");
  assert.equal(R.composerId(only[0].pieces[1]), bfold("ラヴェル(志村和音"), "nobody says ラヴェル is a known name here");
  assert.equal(R.composerId(only[0].pieces[2]), bfold("映像と共に(チャップリン名作集"), "a title cut off by a bracket is not a composer and is not cut");
  const withKey = [...only, card("b", { pieces: [piece("ラヴェル", "ボレロ", "ravel")] })], R2 = makeResolver(withKey);
  assert.equal(R2.composerId(withKey[0].pieces[1]), "ravel");
  assert.equal(R2.composerText(withKey[0].pieces[1]), "ラヴェル");
  assert.equal(R2.composerId(withKey[0].pieces[2]), bfold("映像と共に(チャップリン名作集"));
});
ok("Johann Strauss II written five ways is one composer; a bare family name and other look-alikes stay apart", () => {
  const items = [card("a", { pieces: [piece("J.シュトラウス2世", "ワルツ", "j-strauss-ii")] }), card("b", { pieces: [piece("J. シュトラウス II世", "a"), piece("J.シュトラウスⅡ世", "b"), piece("ヨハン・シュトラウスII", "c"), piece("シュトラウスII", "d"), piece("シュトラウスII世", "e")] }),
    card("c", { pieces: [piece("J.シュトラウスI世", "f"), piece("シュトラウスI世", "g"), piece("J.シュトラウス1世", "h", "j-strauss-i")] })];
  const R = makeResolver(items);
  assert.deepEqual([...new Set(items[1].pieces.map((p) => R.composerId(p)))], ["j-strauss-ii"]);
  assert.deepEqual([...new Set(items[2].pieces.map((p) => R.composerId(p)))], ["j-strauss-i"]);
  const apart = [["シュトラウス", "シュトラウスII"], ["ロウ", "ロー"], ["ファニー・メンデルスゾーン=ヘンゼル", "メンデルスゾーン"], ["アダムズ", "ジョン・アダムズ"], ["ノルドグレン", "P.H.ノルドグレン"], ["バッハ", "C.P.E.バッハ"]];
  for (const [a, b] of apart) { const x = [card("a", { pieces: [piece(a, "x"), piece(b, "y")] })]; assert.equal(new Set(ids(x, "composer")).size, 2, `${a} / ${b} are two entries`); }
  assert.equal(new Set(ids([card("a", { pieces: [piece("バッハ=ブゾーニ", "x"), piece("J.S.バッハ=J.ブラームス", "y"), piece("J.S.バッハ", "z", "bach")] })], "composer")).size, 1, "a transcription credit is the original composer");
  assert.equal(new Set(ids([card("a", { pieces: [piece("グノー=リスト編", "x"), piece("グノー", "y"), piece("エンニオ・モリコーネ", "p"), piece("モリコーネ", "q")] })], "composer")).size, 2);
});
ok("every alias target is a composer key or a spelling; no alias is a bare family name; no key is a typo (the Python table is checked in test_ui.py)", () => {
  for (const [from, to] of Object.entries(COMPOSER_ALIAS)) {
    assert.ok(/^[a-z][a-z0-9-]*$/.test(to) || /[^\x00-\x7f]/.test(to), `${from} -> ${to}`);
    assert.ok(nameFold(from) !== nameFold(to), `${from} is its own target`);
  }
  for (const bare of ["シュトラウス", "バッハ", "アダムズ", "ロウ", "ノルドグレン", "ウィリアムズ"]) assert.ok(!(bare in COMPOSER_ALIAS), bare);
});
ok("an arranger credit is not part of a composer name, and a name made of it alone is still not a composer", () => {
  assert.equal(creditless("米津玄師(加羽沢美濃編曲)"), "米津玄師");
  assert.equal(creditless("バラキレフ(カゼッラ編曲)"), "バラキレフ");
  assert.equal(creditless("ブラームス（シェーンベルク編）"), "ブラームス");
  assert.equal(creditless("coba(小林沙羅作詞)"), "coba(小林沙羅作詞)", "a lyricist is not an arranger");
  assert.equal(isComposerName("A.ドヴォルジャーク (阪田知樹 編曲)"), true);
  assert.equal(isComposerName("(阪田知樹 編曲)"), false);
});

ok("a long-vowel mark does not make a second piece", () => {
  for (const [a, b] of [["ラプソディー・イン・ブルー", "ラプソディ・イン・ブルー"], ["アルト・サクソフォーン協奏曲", "アルト・サクソフォン協奏曲"]]) {
    const items = [card("a", { pieces: [piece("ガーシュウィン", a, "gershwin")] }), card("b", { pieces: [piece("ガーシュウィン", b, "gershwin")] })];
    assert.equal(buildIndex(items, "work", makeResolver(items)).length, 1, `${a} / ${b}`);
  }
  assert.equal(pageFold("ラプソディー"), "ラプソディ");
  assert.notEqual(workFold("ラプソディー"), pageFold("ラプソディー"), "the local id (the Apple table's) keeps the mark");
});
ok("an English title after the Japanese line of the same piece is that piece, when an opus / catalogue number or a piece number of the same genre says so", () => {
  const items = [
    card("a", { pieces: [piece("ベートーヴェン", "交響曲第9番ニ短調『合唱付き』op.125", "beethoven", "beethoven:symphony-9"), piece("ベートーヴェン", 'Symphony No.9 in D minor, op. 125 “Choral”', "beethoven")] }),
    card("b", { pieces: [piece("ブルックナー", "交響曲第4番 変ホ長調「ロマンティック」 WAB 104"), piece("ブルックナー", 'Symphony No. 4 in E-Flat Major, WAB 104, "Romantic"')] }),
    card("c", { pieces: [piece("マーラー", "交響曲第1番 ニ長調 「巨人」", "mahler", "mahler:symphony-1"), piece("マーラー", 'Symphony No. 1 in D major, "Titan"', "mahler")] }),
  ];
  const R = makeResolver(items), idx = buildIndex(items, "work", R);
  assert.equal(idx.length, 3);
  assert.ok(idx.every((e) => !/[A-Za-z]{4}/.test(e.label)), "no English label");
  for (const it of items) assert.equal(entriesOf(it, "work", R).length, 1, it.concert_id);
  for (const it of items) for (const p of it.pieces) assert.equal(matchesEntity(it, "work", R.canon("work", localWorkId(p)), R), true, `${it.concert_id}: the detail link of ${p.work} lands on a page that lists the concert`);
  const ru = R.rowsOf(items[0]);
  assert.deepEqual(ru.map((r) => r.tr), [false, true]);
  assert.equal(ru[1].id, "beethoven:symphony-9");
});
ok("an English title is its own piece when nothing shows it is a translation", () => {
  const cases = [
    [piece("グリンカ", "歌劇『ルスランとリュドミラ』序曲"), piece("グリンカ", '"Ruslan and Lyudmila" Overture')],
    [piece("藤倉大", "ラディアンス"), piece("藤倉大", "Radiance for orchestra")],
    [piece("ベートーヴェン", "ピアノ協奏曲第1番 op.15", "beethoven"), piece("ベートーヴェン", "Symphony No. 1 in C major, op. 21", "beethoven")],
    [piece("ベートーヴェン", "ピアノ協奏曲第1番", "beethoven"), piece("ベートーヴェン", "Symphony No. 1", "beethoven")],
    [piece("モーツァルト", "交響曲第40番", "mozart"), piece("ブラームス", "Symphony No. 40", "brahms")],
  ];
  for (const [jp, en] of cases) { const items = [card("a", { pieces: [jp, en] })]; assert.equal(buildIndex(items, "work", makeResolver(items)).length, 2, en.work); }
  // the same English spelling that is a translation in one concert and a piece of its own in another is a piece of its own everywhere: one address cannot be two pages
  const mixed = [card("a", { pieces: [piece("ベートーヴェン", "交響曲第9番 op.125", "beethoven"), piece("ベートーヴェン", "Symphony No.9, op.125", "beethoven")] }), card("b", { pieces: [piece("ベートーヴェン", "ピアノ協奏曲第1番", "beethoven"), piece("ベートーヴェン", "Symphony No.9, op.125", "beethoven")] })];
  const R = makeResolver(mixed);
  for (const it of mixed) for (const p of it.pieces) assert.equal(matchesEntity(it, "work", R.canon("work", localWorkId(p)), R), true, `${it.concert_id}: ${p.work}`);
});
ok("a performer credit of the concert's own artists is not part of the title; other brackets are", () => {
  const items = [card("a", { soloists: ["諏訪内晶子"], conductors: ["ミハイル・プレトニョフ"], pieces: [piece("フランク", "ヴァイオリン・ソナタ イ長調(諏訪内、プレトニョフ)")] }), card("b", { pieces: [piece("フランク", "ヴァイオリン・ソナタ イ長調")] }),
    card("c", { soloists: ["徳永二男、石田泰尚"], pieces: [piece("リムスキー=コルサコフ", "シェエラザード(コンサートマスター:石田泰尚)"), piece("リムスキー=コルサコフ", "シェエラザード")] }), card("d", { soloists: ["桑原志織"], pieces: [piece("ベートーヴェン", "ピアノ協奏曲第5番 (ピアノ:桑原志織)"), piece("ベートーヴェン", "ピアノ協奏曲第5番 (ピアノ:誰か)")] })];
  const R = makeResolver(items);
  assert.equal(buildIndex(items.slice(0, 2), "work", makeResolver(items.slice(0, 2))).length, 1);
  assert.equal(R.rowsOf(items[0])[0].title, "ヴァイオリン・ソナタ イ長調");
  assert.equal(R.rowsOf(items[2])[0].title, "シェエラザード", "a role word before the colon is not a name: the concertmaster is, because the soloist list has him");
  assert.equal(R.rowsOf(items[3])[0].title, "ピアノ協奏曲第5番");
  assert.equal(R.rowsOf(items[3])[1].title, "ピアノ協奏曲第5番 (ピアノ:誰か)", "a name that is not among the concert's artists keeps the bracket");
  const one = [card("a", { soloists: ["A"], pieces: [piece("フランク", "ソナタ(A)")] })];
  assert.equal(makeResolver(one).rowsOf(one[0])[0].title, "ソナタ(A)", "a one-letter name proves nothing");
  const years = [card("a", { soloists: ["小林"], pieces: [piece("武満徹", "ハウ・スロー・ザ・ウィンド(1991)")] })];
  assert.equal(makeResolver(years).rowsOf(years[0])[0].title, "ハウ・スロー・ザ・ウィンド(1991)", "a year is not an artist");
});
ok("one piece written with and without its opus, catalogue number or key is one entry; two numbers are two pieces", () => {
  const merged = [
    ["ブラームス", ["大学祝典序曲 op.80", "大学祝典序曲", "大学祝典序曲 ハ短調 op.80"]], ["R.シュトラウス", ["交響詩「英雄の生涯」op.40", "交響詩「英雄の生涯」"]], ["エルガー", ["行進曲「威風堂々」第1番 op.39", "行進曲「威風堂々」第1番"]],
    ["シューベルト", ["幻想曲「さすらい人」D760", "幻想曲「さすらい人」D760 Op.15"]], ["リスト", ["スペイン狂詩曲 S.254", "スペイン狂詩曲 S.254 R.90"]], ["ドヴォルザーク", ["序曲《謝肉祭》op.92", "序曲《謝肉祭》 op.92, B.169"]],
    ["武満徹", ["ハウ・スロー・ザ・ウィンド(1991)", "ハウ・スロー・ザ・ウィンド"]], ["モーツァルト", ["歌劇「フィガロの結婚」序曲", "『 フィガロの結婚』序曲", "歌劇《フィガロの結婚》序曲 K.492"]], ["レスピーギ", ["交響詩「ローマの噴水」", "ローマの噴水"]],
    ["チャイコフスキー", ["組曲「くるみ割り人形」Op.71a", "バレエ組曲『くるみ割り人形』op. 71a"]], ["チャイコフスキー", ["ロココ風の主題による変奏曲 op.33", "ロココ風の主題による変奏曲 イ長調 op.33"]], ["プッチーニ", ["交響的前奏曲", "交響的前奏曲 イ長調"]],
  ];
  for (const [composer, titles] of merged) {
    const items = titles.map((t, i) => card("c" + i, { pieces: [piece(composer, t)] })), R = makeResolver(items), idx = buildIndex(items, "work", R);
    assert.equal(idx.length, 1, titles.join(" / "));
    assert.equal(idx[0].n, titles.length);
    for (const t of titles) assert.equal(R.canon("work", localWorkId(piece(composer, t))), idx[0].id, `the detail link of ${t}`);
  }
  const apart = [
    ["モーツァルト", ["ロンド ニ長調 K.485", "ロンド ヘ長調 K.494", "ロンド"]], ["ラフマニノフ", ["12の歌曲 Op.14", "12の歌曲 Op.21", "12の歌曲"]], ["ドヴォルザーク", ["スラブ舞曲 op.46", "スラブ舞曲 op.72", "スラブ舞曲"]],
    ["バッハ", ["前奏曲 ハ長調 BWV531", "前奏曲 ホ短調 BWV548より"]], ["ショパン", ["舟歌 op.60", "舟歌"]], ["ショパン", ["夜想曲 第2番", "夜想曲 op.9 no.2"]], ["ベートーヴェン", ["ピアノ・ソナタ 第19番 op.49-1", "ピアノ・ソナタ 第19番 op.49-2"]],
    ["プッチーニ", ["歌劇「ラ・ボエーム」より 冷たい手を", "歌劇「ラ・ボエーム」"]], ["チャイコフスキー", ["バレエ「くるみ割り人形」op.71", "組曲「くるみ割り人形」op.71a"]], ["シベリウス", ["交響曲第5番(1915)", "交響曲第5番(1919)"]], ["モーツァルト", ["歌劇「フィガロの結婚」序曲", "歌劇「フィガロの結婚」"]], ["ブラームス", ["悲劇的序曲 ニ短調 op.81", "悲劇的序曲 ハ短調 op.81"]],
  ];
  for (const [composer, titles] of apart) { const items = titles.map((t, i) => card("c" + i, { pieces: [piece(composer, t)] })); assert.equal(buildIndex(items, "work", makeResolver(items)).length, titles.length, titles.join(" / ")); }
});
ok("which titles are specific enough to be one piece without their numbers", () => {
  for (const c of ["大学祝典序曲", "英雄の生涯", "威風堂々第1番", "交響的前奏曲", "ロココ風の主題による変奏曲", "さすらい人"]) assert.equal(isSpecific(c), true, c);
  for (const c of ["序曲", "ロンド", "ソナタ第19番", "夜想曲no2", "ピアノ協奏曲第1番", "12の歌曲", "ヴァイオリンとピアノのためのソナタ", "舟歌", ""]) assert.equal(isSpecific(c), false, c);
  assert.deepEqual(coreOf("交響曲op491"), { core: "交響曲", opus: "491", cat: "", key: "", year: "" }, "an opus keeps its sub-number: nothing of it is left in the title");
  assert.deepEqual(coreOf("幻想曲さすらい人d760op15"), { core: "幻想曲さすらい人", opus: "15", cat: "d760", key: "", year: "" });
  assert.deepEqual(coreOf("序曲ハ短調"), { core: "序曲", opus: "", cat: "", key: "ハ短調", year: "" });
  assert.deepEqual(coreOf("スペイン狂詩曲s254r90"), { core: "スペイン狂詩曲", opus: "", cat: "s254", key: "", year: "" }, "two catalogue numbers: both go, the first is the one compared");
  assert.deepEqual(coreOf("序曲謝肉祭op92,b169"), { core: "序曲謝肉祭", opus: "92", cat: "b169", key: "", year: "" });
  assert.deepEqual(coreOf("ハウスローザウィンド1991"), { core: "ハウスローザウィンド", opus: "", cat: "", key: "", year: "1991" });
  assert.deepEqual(coreOf("歌劇フィガロの結婚序曲k492"), { core: "フィガロの結婚序曲", opus: "", cat: "k492", key: "", year: "" });
  assert.deepEqual(coreOf("組曲くるみ割り人形op71a"), { core: "組曲くるみ割り人形", opus: "71a", cat: "", key: "", year: "" }, "op.71a (the suite) is not op.71 (the ballet)");
  assert.deepEqual(coreOf("ロンド変ロ長調k485"), { core: "ロンド", opus: "", cat: "k485", key: "変ロ長調", year: "" });
});
ok("an address written with any spelling of a merged piece finds the page, also after the family splits", () => {
  const items = [card("a", { pieces: [piece("ブラームス", "大学祝典序曲 op.80", "brahms")] }), card("b", { pieces: [piece("ブラームス", "大学祝典序曲", "brahms")] }), card("c", { pieces: [piece("ブラームス", "大学祝典序曲 ハ短調 op.80", "brahms")] })];
  const R = makeResolver(items), id = buildIndex(items, "work", R)[0].id;
  for (const old of ["~brahms|大学祝典序曲op80", "~brahms|大学祝典序曲", "~brahms|大学祝典序曲ハ短調op80", "~brahms|「大学祝典序曲」*"]) assert.equal(R.canon("work", old), id, old);
  // a second opus appears (24 months): the family splits into pieces; the stored address of the plain spelling still opens a page that lists concerts
  const more = [...items, card("d", { pieces: [piece("ブラームス", "大学祝典序曲 op.99", "brahms")] })], R2 = makeResolver(more);
  for (const old of ["~brahms|大学祝典序曲", "~brahms|大学祝典序曲op80", "~brahms|大学祝典序曲op99"]) assert.ok(more.some((it) => matchesEntity(it, "work", R2.canon("work", old), R2)), old);
  const noPlain = more.filter((it) => it.concert_id !== "b"), R3 = makeResolver(noPlain);
  assert.ok(noPlain.some((it) => matchesEntity(it, "work", R3.canon("work", id), R3)), "the merged core address, with no plain spelling left");
});
ok("a merged page keeps its Apple link: the table is asked with the local id of every row; two rows that point to two pages are no link", () => {
  const items = [card("a", { pieces: [piece("ブラームス", "大学祝典序曲 op.80"), piece("ブラームス", "大学祝典序曲")] }), card("b", { pieces: [piece("ブラームス", "大学祝典序曲 ハ短調 op.80")] })];
  const R = makeResolver(items), e = buildIndex(items, "work", R)[0];
  assert.equal(buildIndex(items, "work", R).length, 1);
  const own = (slug) => ({ works: { [localWorkId(items[0].pieces[0])]: slug } });
  assert.equal(classicalHref("work", classicalIds("work", e.id, e.id, items, R), own("johannes-brahms-1833-pp9")), "https://classical.music.apple.com/jp/work/johannes-brahms-1833-pp9");
  assert.equal(classicalHref("work", classicalIds("work", e.id, e.id, items, R), { works: { [localWorkId(items[0].pieces[0])]: "aaa", [localWorkId(items[1].pieces[1 - 1])]: "aaa" } }) !== null, true, "two rows, one page: one link");
  assert.equal(classicalHref("work", classicalIds("work", e.id, e.id, items, R), { works: { [localWorkId(items[0].pieces[0])]: "aaa", [localWorkId(items[0].pieces[1])]: "bbb" } }), null, "two different pages: no link, never the wrong one");
});

ok("a family of spellings joins the keyed piece that is written as its plain title, and every page id is its own page", () => {
  const keyed = [card("a", { pieces: [piece("ブラームス", "大学祝典序曲", "brahms", "brahms:academic-festival")] }), card("b", { pieces: [piece("ブラームス", "大学祝典序曲 op.80", "brahms")] }), card("c", { pieces: [piece("ブラームス", "大学祝典序曲 ハ短調 op.80", "brahms")] })];
  const R = makeResolver(keyed), idx = buildIndex(keyed, "work", R);
  assert.deepEqual(idx.map((e) => [e.id, e.n]), [["brahms:academic-festival", 3]]);
  for (const it of keyed) for (const p of it.pieces) assert.equal(matchesEntity(it, "work", R.canon("work", localWorkId(p)), R), true, p.work);
  // a family that cannot join (two opus numbers) never takes the keyed piece's id, and each page id stays itself
  const split = [...keyed, card("d", { pieces: [piece("ブラームス", "大学祝典序曲 op.99", "brahms")] })], R2 = makeResolver(split);
  for (const e of buildIndex(split, "work", R2)) assert.equal(R2.canon("work", e.id), e.id, e.id);
  assert.equal(buildIndex(split, "work", R2).length, 4, "the keyed piece, and each spelling of the conflicted family on its own (as before ADR-0019)");
  const loose = [card("a", { pieces: [piece("ブラームス", "大学祝典序曲 op.80", "brahms")] }), card("b", { pieces: [piece("ブラームス", "大学祝典序曲", "brahms")] })], R3 = makeResolver(loose);
  for (const e of buildIndex(loose, "work", R3)) assert.equal(R3.canon("work", e.id), e.id, e.id);
});
ok("a lone surrogate in a title gives no search address (and so no button)", () => {
  assert.equal(classicalSearchHref("曲\ud83d"), null);
  assert.ok(searchTerm("曲\ud83d").length > 0);
});

if (failed.length) { console.error(failed.length + " FAILED:\n- " + failed.join("\n- ")); process.exit(1); }
console.log(`${n} browse checks passed`);
