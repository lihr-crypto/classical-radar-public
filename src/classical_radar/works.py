"""Programme and performer normalisation (ADR-0001 / 00_DECISIONS 0.3 item 2).

Deliberately small: no world work catalogue. ``composer_key`` comes from a hand-maintained alias table (kana / kanji / Latin spellings) and
is ``None`` for anyone not listed - those items are still found by full-text matching on ``raw_text``. ``work_key`` is produced only for
unambiguous generic forms (symphony / concerto / sonata / quartet + number); everything else is ``None``. Nothing here guesses a person:
artists are stored by displayed name, never merged by similarity (03_CONTRACTS 3.2).
"""
from __future__ import annotations

import re
import unicodedata

# key: display, alias, alias ...  (first item after the key is the canonical display used in facets)
_COMPOSERS = """
bach: バッハ, J.S.バッハ, ヨハン・ゼバスティアン・バッハ, Bach, J.S. Bach, Johann Sebastian Bach
handel: ヘンデル, ヘンデル, Handel
vivaldi: ヴィヴァルディ, ビバルディ, Vivaldi
haydn: ハイドン, Haydn
mozart: モーツァルト, モーツアルト, Mozart
beethoven: ベートーヴェン, ベートーベン, Beethoven
schubert: シューベルト, Schubert
weber: ウェーバー, Weber
rossini: ロッシーニ, Rossini
mendelssohn: メンデルスゾーン, Mendelssohn
schumann: シューマン, Schumann
chopin: ショパン, Chopin
liszt: リスト, Liszt
berlioz: ベルリオーズ, Berlioz
wagner: ワーグナー, ワーグナ, Wagner
verdi: ヴェルディ, ベルディ, Verdi
franck: フランク, Franck
bruckner: ブルックナー, Bruckner
brahms: ブラームス, Brahms
smetana: スメタナ, Smetana
dvorak: ドヴォルザーク, ドヴォルジャーク, ドボルザーク, ドヴォルジャーク, Dvorak, Dvořák
bizet: ビゼー, Bizet
tchaikovsky: チャイコフスキー, チャイコフスキイ, Tchaikovsky
saint-saens: サン＝サーンス, サン=サーンス, サン・サーンス, サン・サーンス, Saint-Saens, Saint-Saëns
mussorgsky: ムソルグスキー, ムソルグスキイ, Mussorgsky
rimsky-korsakov: リムスキー＝コルサコフ, リムスキー=コルサコフ, リムスキー・コルサコフ, Rimsky-Korsakov
massenet: マスネ, マスネー, Massenet
grieg: グリーグ, Grieg
faure: フォーレ, Fauré, Faure
puccini: プッチーニ, Puccini
mahler: マーラー, Mahler
r-strauss: R.シュトラウス, リヒャルト・シュトラウス, リヒャルト＝シュトラウス, Richard Strauss, R. Strauss
j-strauss-ii: J.シュトラウス2世, ヨハン・シュトラウス2世, ヨハン・シュトラウスII世, J.シュトラウスII, Johann Strauss II
j-strauss-i: J.シュトラウス1世, ヨハン・シュトラウス1世, Johann Strauss I
elgar: エルガー, Elgar
debussy: ドビュッシー, Debussy
sibelius: シベリウス, Sibelius
rachmaninoff: ラフマニノフ, ラフマニノフ, Rachmaninoff, Rachmaninov
ravel: ラヴェル, ラベル, Ravel
holst: ホルスト, Holst
bartok: バルトーク, Bartók, Bartok
stravinsky: ストラヴィンスキー, ストラヴィンスキイ, ストラビンスキー, Stravinsky
prokofiev: プロコフィエフ, プロコフィエフ, Prokofiev
shostakovich: ショスタコーヴィチ, ショスタコーヴィッチ, ショスタコービチ, Shostakovich
britten: ブリテン, Britten
gershwin: ガーシュウィン, ガーシュイン, Gershwin
copland: コープランド, Copland
barber: バーバー, Barber
bernstein: バーンスタイン, Bernstein
korngold: コルンゴルト, Korngold
schoenberg: シェーンベルク, シェーンベルグ, Schoenberg, Schönberg
berg: ベルク, Berg
webern: ウェーベルン, Webern
messiaen: メシアン, Messiaen
janacek: ヤナーチェク, ヤナーチェック, Janacek, Janáček
kodaly: コダーイ, Kodály, Kodaly
respighi: レスピーギ, Respighi
rodrigo: ロドリーゴ, Rodrigo
falla: ファリャ, Falla
albeniz: アルベニス, Albéniz, Albeniz
granados: グラナドス, Granados
ginastera: ヒナステラ, Ginastera
piazzolla: ピアソラ, Piazzolla
paganini: パガニーニ, Paganini
sarasate: サラサーテ, Sarasate
wieniawski: ヴィエニャフスキ, Wieniawski
vieuxtemps: ヴュータン, ヴィユータン, Vieuxtemps
scriabin: スクリャービン, スクリャービン, Scriabin
medtner: メトネル, メトネル, Medtner
alkan: アルカン, Alkan
ysaye: イザイ, Ysaÿe, Ysaye
chausson: ショーソン, Chausson
poulenc: プーランク, Poulenc
satie: サティ, Satie
dukas: デュカス, Dukas
lalo: ラロ, Lalo
glinka: グリンカ, Glinka
borodin: ボロディン, Borodin
glazunov: グラズノフ, Glazunov
khachaturian: ハチャトゥリアン, ハチャトゥリャン, Khachaturian
nielsen: ニールセン, Nielsen
walton: ウォルトン, Walton
vaughan-williams: ヴォーン・ウィリアムズ, ヴォーン＝ウィリアムズ, ボーン・ウィリアムズ, Vaughan Williams
mascagni: マスカーニ, Mascagni
leoncavallo: レオンカヴァッロ, Leoncavallo
donizetti: ドニゼッティ, Donizetti
bellini: ベッリーニ, ベルリーニ, Bellini
offenbach: オッフェンバック, Offenbach
delibes: ドリーブ, Delibes
adam: アダン, Adam
khachaturyan: ハチャトリアン, Khachaturyan
takemitsu: 武満徹, 武満 徹, Takemitsu
hisaishi: 久石譲, 久石 譲, Hisaishi
sakamoto: 坂本龍一, 坂本 龍一, Sakamoto
ifukube: 伊福部昭, 伊福部 昭, Ifukube
akutagawa: 芥川也寸志, 芥川 也寸志, Akutagawa
toyama: 外山雄三, 外山 雄三, Toyama
mayuzumi: 黛敏郎, 黛 敏郎, Mayuzumi
dan: 團伊玖磨, 団伊玖磨, 團 伊玖磨, Dan
yamada: 山田耕筰, 山田 耕筰, Yamada
kapustin: カプースチン, Kapustin
milhaud: ミヨー, Milhaud
hindemith: ヒンデミット, Hindemith
reger: レーガー, Reger
zemlinsky: ツェムリンスキー, Zemlinsky
suk: スーク, Suk
josef-strauss: ヨーゼフ・シュトラウス, Josef Strauss
eduard-strauss: エドゥアルト・シュトラウス, Eduard Strauss
joplin: ジョプリン, Joplin
anderson: アンダーソン, ルロイ・アンダーソン, Anderson
williams: J.ウィリアムズ, ジョン・ウィリアムズ, John Williams
zimmer: ハンス・ジマー, ジマー, Hans Zimmer
"""


def n(text: str) -> str:
    """Comparison form: NFKC, case-folded, without whitespace, dots, middle dots, hyphens and equals signs."""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not "\u0300" <= c <= "\u036f")  # fold Latin diacritics (dvořák == dvorak); never the kana dakuten U+3099
    return re.sub(r"[\s.・·\-=＝・]", "", t)


_DISPLAY: dict[str, str] = {}
_ALIAS: dict[str, str] = {}
for _line in _COMPOSERS.strip().splitlines():
    _key, _rest = _line.split(":", 1)
    _names = [x.strip() for x in _rest.split(",") if x.strip()]
    _DISPLAY[_key.strip()] = _names[0]
    for _name in _names:
        _ALIAS.setdefault(n(_name), _key.strip())


def composer_key(text: str | None) -> str | None:
    """Alias lookup on the composer field. A trailing arranger note in parentheses is ignored; unknown names return None."""
    if not text:
        return None
    base = re.sub(r"[（(][^）)]*[）)]", "", unicodedata.normalize("NFKC", text))
    return _ALIAS.get(n(base))


def composer_display(key: str | None, raw: str | None) -> str | None:
    return _DISPLAY.get(key) if key else (re.sub(r"\s+", " ", raw).strip() if raw else None)


_NUM = r"第?\s*(\d{1,3})\s*番"
_FORMS = [  # (regex over the NFKC work text, key suffix). Only unambiguous generic forms.
    (r"交響曲\s*" + _NUM, "symphony-{}"), (r"ピアノ協奏曲\s*" + _NUM, "piano-concerto-{}"), (r"ヴァイオリン協奏曲\s*" + _NUM, "violin-concerto-{}"),
    (r"チェロ協奏曲\s*" + _NUM, "cello-concerto-{}"), (r"ピアノ[・･]?ソナタ\s*" + _NUM, "piano-sonata-{}"), (r"ヴァイオリン[・･]?ソナタ\s*" + _NUM, "violin-sonata-{}"),
    (r"弦楽四重奏曲\s*" + _NUM, "string-quartet-{}"), (r"ピアノ三重奏曲\s*" + _NUM, "piano-trio-{}"),
]
_NOKEY_FORMS = [(r"ピアノ協奏曲(?!\s*第)", "piano-concerto"), (r"ヴァイオリン協奏曲(?!\s*第)", "violin-concerto"), (r"チェロ協奏曲(?!\s*第)", "cello-concerto")]


def work_key(ckey: str | None, work: str | None) -> str | None:
    if not ckey or not work:
        return None
    w = unicodedata.normalize("NFKC", work)
    for rx, fmt in _FORMS:
        m = re.search(rx, w)
        if m:
            return f"{ckey}:{fmt.format(int(m.group(1)))}"
    for rx, kind in _NOKEY_FORMS:
        if re.search(rx, w):
            return f"{ckey}:{kind}"
    return None


# ---------------- programme ----------------
_SEP = re.compile(r"[:]")  # after NFKC: "：" -> ":"; NHK's "／" is handled in parse_programme
_NOISE = re.compile(r"^(?:[※＊*●■□◇▲▼◆]|[—―－\-–]+$|休憩|intermission|プレトーク|アフタートーク|アンコール|＊\s*＊|\*\s*\*|\[|［|【第.{1,3}[日部]】|\d{4}年\d{1,2}月\d{1,2}日|ほか$|［第|【(?:新制作|日本初演|世界初演|全曲)】$)", re.I)
_LATIN = re.compile(r"^[A-Za-z0-9\s.,:;'’\-–&()/#♯♭ÀÁÂÄÇÈÉÊËÍÎÏÑÓÔÖÚÜàáâäçèéêëíîïñóôöúüřžšěůČčŠŽ]+$")


_MOVEMENT = re.compile(r"^(?:[IVXivx]{1,5}[.、]|\d{1,2}[.、]|第\d+楽章|[①-⑳]|[Ⅰ-Ⅻ])")


def _is_latin_line(line: str) -> bool:
    return bool(line) and bool(_LATIN.match(line)) and not re.search(r"[぀-ヿ一-鿿]", line)


def parse_programme(lines: list[str], *, pairs: list[tuple[str, str]] | None = None) -> list[dict]:
    """Lines like ``作曲家：作品`` (or ``作曲家／作品``) -> program_item dicts (position 1..n).

    ``pairs`` is for pages that already separate composer and work (KAJIMOTO ``dt``/``dd``). Notes, separators ("—", "＊ ＊ ＊"),
    intermissions and Latin translation lines are not items; movement lists and stage notes that follow a work are appended to that
    item's raw_text so full-text search still sees them. A Latin ``Composer: Work`` line directly after an item supplies a composer
    key when the Japanese spelling is not in the alias table.
    """
    items: list[dict] = []

    def add(comp: str | None, work: str, raw: str):
        ck = composer_key(comp)
        items.append({"position": len(items) + 1, "raw_text": raw[:400], "composer_display": composer_display(ck, comp), "composer_key": ck,
                      "work_display": work.strip()[:300] or None, "work_key": work_key(ck, work)})

    if pairs is not None:
        for comp, work in pairs:
            comp, work = re.sub(r"\s+", " ", comp or "").strip(), re.sub(r"\s+", " ", work or "").strip()
            if comp and work:
                add(comp, work, f"{comp}：{work}")
            elif work and items:  # an arranger/duration note under the previous work
                items[-1]["raw_text"] = (items[-1]["raw_text"] + " " + work)[:400]
        return items
    current: str | None = None  # composer set by a header line ("シューマン：" or "オール・ベートーヴェン・プログラム")
    for raw in lines:
        line = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", raw)).strip() if raw else ""
        if not line:
            continue
        if _is_latin_line(line):
            if items and items[-1]["composer_key"] is None and ":" in line:
                ck = composer_key(line.split(":", 1)[0])
                if ck:
                    items[-1].update(composer_key=ck, composer_display=_DISPLAY[ck], work_key=work_key(ck, items[-1]["work_display"]))
            continue
        if _NOISE.match(line):
            continue
        allp = re.search(r"オール[・･]?(.+?)[・･]?プログラム", line)  # "オール・ベートーヴェン・プログラム" (possibly wrapped in 【】/＜＞)
        if allp and composer_key(allp.group(1)):
            current = allp.group(1)
            continue
        m = _SEP.search(line)
        if not m:  # NHK writes "作曲家／作品"; accept "/" only when the left side looks like a name (no digits, short)
            m = re.search(r"/", line)
            if m and (re.search(r"\d", line[:m.start()]) or m.start() > 25):
                m = None
        if m and re.fullmatch(r"[\d\s:/月日()（）曜祝水木金土・,、~〜-]*", line[:m.start()]):
            m = None  # "19:00 サントリーホール" / "11/25(水)" are schedule lines, not "composer: work"
        if m and 0 < m.start() <= 30:
            left, right = line[:m.start()].strip(), line[m.end():].strip()
            if right:
                add(left, right, line)
                current = None
            else:
                current = left  # header-only line: the works follow on the next lines
            continue
        if _MOVEMENT.match(line) or current is None:
            if items:
                items[-1]["raw_text"] = (items[-1]["raw_text"] + " " + line)[:400]
        else:
            add(current, line, f"{current}：{line}")
    return items


# ---------------- performers ----------------
_ENSEMBLE = re.compile(r"管弦楽団|交響楽団|フィルハーモニ|フィル$|オーケストラ|合唱団|合唱|コーラス|アンサンブル|楽団|Orchestra|Chorus|Philharmonic|Ensemble|Quartet|Quartett|カルテット|四重奏団", re.I)
_CONDUCTOR = re.compile(r"^(?:指揮|音楽監督|常任指揮者|首席指揮者|Conductor)$", re.I)
_OTHER_ROLE = re.compile(r"演出|合唱|管弦楽|オーケストラ|コンサートマスター|コンマス|司会|ナビゲーター|語り|ナレーター|MC|美術|振付|照明|合唱指揮|ピアノ伴奏|チェンバロ|通訳|解説|プレトーク|ゲストコンサートマスター", re.I)
_SOLO_ROLE = re.compile(r"ピアノ|ヴァイオリン|ヴィオラ|チェロ|コントラバス|フルート|オーボエ|クラリネット|ファゴット|ホルン|トランペット|トロンボーン|ハープ|オルガン|ギター|サクソフォン|ソプラノ|メゾ|アルト|テノール|バリトン|バス|カウンターテナー|歌|ヴォーカル|ソリスト|Piano|Violin|Viola|Cello|Flute|Oboe|Clarinet|Horn|Soprano|Tenor|Baritone|Bass|Harp|Organ|Guitar", re.I)


def _clean_name(name: str) -> str:
    name = re.sub(r"[［\[][^］\]]*[］\]]", "", name)  # [桂冠名誉指揮者]
    name = re.sub(r"\s*[（(](?:ゲスト|客演|特別出演|賛助出演)[^）)]*[）)]\s*$", "", name)
    name = re.sub(r"[※*＊†‡]+", "", name)
    name = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip(" 、,/:：=＝")
    return re.sub(r"(?<=[\u30a0-\u30ff])=(?=[\u30a0-\u30ff])", "＝", name)  # フランソワ＝グザヴィエ: NFKC turned the double hyphen into "="


def parse_artist(line: str) -> dict | None:
    """One performer line -> {name_display, role_label, kind} or None.

    Accepts ``指揮：名前`` / ``指揮 : 名前`` / ``指揮＝名前`` (role first), ``名前（ヴァイオリン）`` / ``名前 Latin (ピアノ, Piano)`` (role in brackets), and bare ensemble names.
    ``kind`` is conductor | soloist | other; the caller decides recital_headliner vs concerto_soloist.
    """
    raw = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", line or "")).strip()
    raw = re.sub(r"【[^】]*】", "", raw).strip()  # 【11/25出演】 date qualifiers
    if not raw or raw in ("ほか", ": ほか", "他") or re.match(r"^(?:プロフィール|Profile)$", raw) or _is_latin_line(raw) and not re.search(r"\(", raw):
        return None
    m = re.match(r"^([^:=/]{1,24})\s*[:=]\s*(.+)$", raw)
    if m:  # ROLE : NAME
        label, name = m.group(1).strip(), _clean_name(m.group(2))
        if not name or name in ("ほか", "他"):
            return None
        if _CONDUCTOR.match(label):
            return {"name_display": name, "role_label": label, "kind": "conductor"}
        if _OTHER_ROLE.search(label) and not _SOLO_ROLE.search(label):
            return {"name_display": name, "role_label": label, "kind": "other"}
        if _SOLO_ROLE.search(label):
            return {"name_display": name, "role_label": label, "kind": "soloist"}
        return {"name_display": name, "role_label": label, "kind": "other"}
    m = re.match(r"^(.+?)\s*[（(]\s*([^()（）]+?)\s*[)）]\s*$", raw)  # NAME (ROLE[, English])
    if m:
        name, role = _clean_name(re.sub(r"\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.\-' ]*,?$", "", m.group(1))), m.group(2).split(",")[0].strip()
        if _CONDUCTOR.match(role) or role == "指揮":
            return {"name_display": name, "role_label": role, "kind": "conductor"}
        if _SOLO_ROLE.search(role):
            return {"name_display": name, "role_label": role, "kind": "soloist"}
        return {"name_display": name, "role_label": role, "kind": "other"}
    name = _clean_name(re.sub(r"(?<=[^\x00-\x7f])\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.\-' ]*$", "", raw))
    if name and _ENSEMBLE.search(name):
        return {"name_display": name, "role_label": "", "kind": "other"}
    return None


def build_artists(parsed: list[dict], *, category_hint: str | None = None) -> list[dict]:
    """parsed -> concert_artist dicts with contract roles.

    recital_headliner: exactly one soloist, no conductor, no ensemble (a personal recital). concerto_soloist: soloist(s) next to a
    conductor or ensemble. Anything else (duos, quartets, vocal + piano accompaniment ...) is 'other' - never guessed up to a headliner.
    """
    seen, rows = set(), []
    for p in parsed:
        key = (p["name_display"], p["kind"])
        if p and key not in seen:
            seen.add(key)
            rows.append(p)
    soloists = [r for r in rows if r["kind"] == "soloist"]
    has_conductor = any(r["kind"] == "conductor" for r in rows)
    has_ensemble = any(r["kind"] == "other" and _ENSEMBLE.search(r["name_display"]) for r in rows)
    out = []
    for r in rows:
        if r["kind"] == "conductor":
            role = "conductor"
        elif r["kind"] == "soloist":
            if len(soloists) == 1 and not has_conductor and not has_ensemble:
                role = "recital_headliner"
            elif has_conductor or has_ensemble:
                role = "concerto_soloist"
            else:
                role = "other"
        else:
            role = "other"
        out.append({"name_display": r["name_display"], "role": role, "role_label": r.get("role_label") or None})
    return out
