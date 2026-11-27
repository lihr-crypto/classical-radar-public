"""Orchestra identification for the "by orchestra" view and the overseas-visit category hint.

A concert's orchestras come from (1) the source itself for the seven domestic orchestra sites, and (2) known names found in the title or
in ensemble performer names. Only names in the tables below are recognised; an unlisted ensemble is never guessed to be overseas.
Matching is longest-alias-first on normalised text, so 新日本フィル is never also read as 日本フィル.
"""
from __future__ import annotations

from .works import n

# key: origin | display | aliases...   origin: seven = the fixed domestic list (00_DECISIONS 0.1); jp = other Japanese; overseas
_TABLE = """
nhkso: seven | NHK交響楽団 | N響, NHK Symphony Orchestra
tmso: seven | 東京都交響楽団 | 都響, Tokyo Metropolitan Symphony Orchestra
tso: seven | 東京交響楽団 | 東響, Tokyo Symphony Orchestra
jpo: seven | 日本フィルハーモニー交響楽団 | 日本フィル, Japan Philharmonic Orchestra
njp: seven | 新日本フィルハーモニー交響楽団 | 新日本フィル, New Japan Philharmonic
yomikyo: seven | 読売日本交響楽団 | 読響, Yomiuri Nippon Symphony Orchestra
tpo: seven | 東京フィルハーモニー交響楽団 | 東京フィル, 東フィル, Tokyo Philharmonic
jp-tcpo: jp | 東京シティ・フィルハーモニック管弦楽団 | 東京シティ・フィル
jp-kanagawa-phil: jp | 神奈川フィルハーモニー管弦楽団 | 神奈川フィル
jp-chiba: jp | 千葉交響楽団
jp-ppt: jp | パシフィック・フィルハーモニア東京
jp-sapporo: jp | 札幌交響楽団 | 札響, Sapporo Symphony Orchestra
jp-osaka-phil: jp | 大阪フィルハーモニー交響楽団 | 大阪フィル, Osaka Philharmonic Orchestra
jp-fujisan: jp | 富士山静岡交響楽団
jp-kyushu: jp | 九州交響楽団
jp-kyoto: jp | 京都市交響楽団
jp-oek: jp | オーケストラ・アンサンブル金沢
jp-bcj: jp | バッハ・コレギウム・ジャパン | Bach Collegium Japan
jp-tokyo-chamber: jp | 東京室内管弦楽団
jp-ishida: jp | 石田組
ov-berlin-phil: overseas | ベルリン・フィルハーモニー管弦楽団 | ベルリン・フィル, Berliner Philharmoniker, Berlin Philharmonic
ov-vienna-phil: overseas | ウィーン・フィルハーモニー管弦楽団 | ウィーン・フィル, Wiener Philharmoniker, Vienna Philharmonic
ov-vienna-so: overseas | ウィーン交響楽団 | Wiener Symphoniker
ov-br-so: overseas | バイエルン放送交響楽団 | Symphonieorchester des Bayerischen Rundfunks, Bavarian Radio Symphony Orchestra
ov-munich-phil: overseas | ミュンヘン・フィルハーモニー管弦楽団 | ミュンヘン・フィル, Münchner Philharmoniker
ov-dresden: overseas | シュターツカペレ・ドレスデン | ドレスデン国立歌劇場管弦楽団, Staatskapelle Dresden
ov-gewandhaus: overseas | ゲヴァントハウス管弦楽団 | ライプツィヒ・ゲヴァントハウス管弦楽団, Gewandhausorchester
ov-ndr-elbphil: overseas | NDRエルプフィルハーモニー管弦楽団 | NDRエルプフィル, 北ドイツ放送交響楽団, NDR Elbphilharmonie Orchester
ov-bamberg: overseas | バンベルク交響楽団 | Bamberger Symphoniker
ov-dso-berlin: overseas | ベルリン・ドイツ交響楽団 | Deutsches Symphonie-Orchester Berlin
ov-rsb: overseas | ベルリン放送交響楽団 | Rundfunk-Sinfonieorchester Berlin
ov-hr: overseas | hr交響楽団 | フランクフルト放送交響楽団, hr-Sinfonieorchester
ov-wdr: overseas | ケルンWDR交響楽団 | WDR Sinfonieorchester
ov-mco: overseas | マーラー・チェンバー・オーケストラ | Mahler Chamber Orchestra
ov-coe: overseas | ヨーロッパ室内管弦楽団 | Chamber Orchestra of Europe
ov-concertgebouw: overseas | ロイヤル・コンセルトヘボウ管弦楽団 | コンセルトヘボウ, Royal Concertgebouw Orchestra
ov-rotterdam: overseas | ロッテルダム・フィルハーモニー管弦楽団 | ロッテルダム・フィル, Rotterdam Philharmonic
ov-lso: overseas | ロンドン交響楽団 | London Symphony Orchestra
ov-lpo: overseas | ロンドン・フィルハーモニー管弦楽団 | ロンドン・フィル, London Philharmonic
ov-philharmonia: overseas | フィルハーモニア管弦楽団 | Philharmonia Orchestra
ov-rpo: overseas | ロイヤル・フィルハーモニー管弦楽団 | ロイヤル・フィル, Royal Philharmonic
ov-bbc-so: overseas | BBC交響楽団 | BBC Symphony Orchestra
ov-paris: overseas | パリ管弦楽団 | Orchestre de Paris
ov-onf: overseas | フランス国立管弦楽団 | Orchestre National de France
ov-toulouse: overseas | トゥールーズ・キャピトル国立管弦楽団 | Orchestre National du Capitole de Toulouse
ov-czech-phil: overseas | チェコ・フィルハーモニー管弦楽団 | チェコ・フィル, Czech Philharmonic
ov-prague-so: overseas | プラハ交響楽団 | Prague Symphony Orchestra
ov-budapest-festival: overseas | ブダペスト祝祭管弦楽団 | Budapest Festival Orchestra
ov-warsaw-phil: overseas | ワルシャワ・フィルハーモニー管弦楽団 | ワルシャワ・フィル, Warsaw Philharmonic
ov-ukraine-opera: overseas | ウクライナ国立歌劇場管弦楽団 | National Opera of Ukraine
ov-vienna-strauss: overseas | ウィーン・ヨハン・シュトラウス管弦楽団 | Wiener Johann Strauss Orchester
ov-vienna-waltz-festival: overseas | ウィンナー・ワルツ祝祭オーケストラ
ov-wiener-ring: overseas | ウィーン・リング・アンサンブル | Wiener Ring-Ensemble
ov-europa-galante: overseas | エウローパ・ガランテ | Europa Galante
ov-valencia: overseas | バレンシア管弦楽団 | Orquestra de València
ov-santa-cecilia: overseas | サンタ・チェチーリア国立アカデミー管弦楽団 | Orchestra dell'Accademia Nazionale di Santa Cecilia
ov-scala: overseas | ミラノ・スカラ座フィルハーモニー管弦楽団 | Filarmonica della Scala
ov-tonhalle: overseas | チューリッヒ・トーンハレ管弦楽団 | Tonhalle-Orchester Zürich
ov-osr: overseas | スイス・ロマンド管弦楽団 | Orchestre de la Suisse Romande
ov-lucerne: overseas | ルツェルン祝祭管弦楽団 | Lucerne Festival Orchestra
ov-oslo: overseas | オスロ・フィルハーモニー管弦楽団 | オスロ・フィル, Oslo Philharmonic
ov-helsinki: overseas | ヘルシンキ・フィルハーモニー管弦楽団 | ヘルシンキ・フィル
ov-finnish-rso: overseas | フィンランド放送交響楽団 | Finnish Radio Symphony Orchestra
ov-swedish-rso: overseas | スウェーデン放送交響楽団 | Swedish Radio Symphony Orchestra
ov-st-petersburg: overseas | サンクトペテルブルク・フィルハーモニー交響楽団 | サンクトペテルブルク・フィル
ov-israel-phil: overseas | イスラエル・フィルハーモニー管弦楽団 | イスラエル・フィル, Israel Philharmonic
ov-nyphil: overseas | ニューヨーク・フィルハーモニック | ニューヨーク・フィル, New York Philharmonic
ov-chicago: overseas | シカゴ交響楽団 | Chicago Symphony Orchestra
ov-boston: overseas | ボストン交響楽団 | Boston Symphony Orchestra
ov-philadelphia: overseas | フィラデルフィア管弦楽団 | Philadelphia Orchestra
ov-cleveland: overseas | クリーヴランド管弦楽団 | Cleveland Orchestra
ov-la-phil: overseas | ロサンゼルス・フィルハーモニック | ロサンゼルス・フィル, Los Angeles Philharmonic
ov-sf: overseas | サンフランシスコ交響楽団 | San Francisco Symphony
ov-montreal: overseas | モントリオール交響楽団 | Orchestre symphonique de Montréal
ov-toronto: overseas | トロント交響楽団 | Toronto Symphony Orchestra
ov-sydney: overseas | シドニー交響楽団 | Sydney Symphony Orchestra
ov-hk-phil: overseas | 香港フィルハーモニー管弦楽団 | 香港フィル, Hong Kong Philharmonic
ov-taipei: overseas | 台北市立交響楽団 | Taipei Symphony Orchestra
ov-seoul-phil: overseas | ソウル・フィルハーモニー管弦楽団 | ソウル・フィル, Seoul Philharmonic
ov-kbs: overseas | KBS交響楽団 | KBS Symphony Orchestra
ov-singapore: overseas | シンガポール交響楽団 | Singapore Symphony Orchestra
ov-simon-bolivar: overseas | シモン・ボリバル交響楽団 | Simón Bolívar Symphony Orchestra, Simon Bolivar Symphony Orchestra
ov-polish-amadeus: overseas | ポーランド国立放送アマデウス室内オーケストラ | Amadeus Chamber Orchestra of Polish Radio
ov-belgium-chamber: overseas | ベルギー王立室内管弦楽団 | Royal Chamber Orchestra of Wallonia
ov-concert-des-nations: overseas | ル・コンセール・デ・ナシオン | Le Concert des Nations
ov-cbso: overseas | バーミンガム市交響楽団 | City of Birmingham Symphony Orchestra, CBSO
ov-prague-rso: overseas | プラハ放送交響楽団 | Prague Radio Symphony Orchestra
ov-paris-chamber: overseas | パリ室内管弦楽団 | Orchestre de chambre de Paris
ov-berlin-so: overseas | ベルリン交響楽団 | Berliner Symphoniker
ov-evergreen: overseas | エバーグリーン交響楽団 | 台湾長栄交響楽団, Evergreen Symphony Orchestra
ov-orpheus: overseas | オルフェウス室内管弦楽団 | Orpheus Chamber Orchestra
ov-brussels-phil: overseas | ブリュッセル・フィルハーモニック | Brussels Philharmonic
ov-dkam: overseas | ドイツ・カンマーフィルハーモニー管弦楽団 | ドイツ・カンマーフィル, Deutsche Kammerphilharmonie Bremen
ov-warsaw-national: overseas | ワルシャワ国立フィルハーモニー管弦楽団 | Warsaw National Philharmonic
ov-lucerne-festival-chamber: overseas | ルツェルン・フェスティバル室内管弦楽団 | Lucerne Festival Contemporary Orchestra, Lucerne Festival Strings
ov-gaertnerplatz: overseas | ミュンヘン・ゲルトナープラッツ州立劇場管弦楽団 | Staatstheater am Gärtnerplatz
ov-stuttgart-phil: overseas | シュトゥットガルト・フィルハーモニー管弦楽団 | Stuttgarter Philharmoniker
ov-radio-france-phil: overseas | フランス放送フィルハーモニー管弦楽団 | Orchestre Philharmonique de Radio France
ov-toulouse-capitole: overseas | トゥールーズ・キャピトル管弦楽団 | Orchestre du Capitole de Toulouse
ov-camerata-salzburg: overseas | カメラータ・ザルツブルク | Camerata Salzburg
ov-slovak-phil: overseas | スロヴァキア・フィルハーモニー管弦楽団 | Slovak Philharmonic
ov-dresden-phil: overseas | ドレスデン・フィルハーモニー管弦楽団 | Dresdner Philharmonie
ov-boston-phil-youth: overseas | ボストン・フィルハーモニー・ユース管弦楽団 | Boston Philharmonic Youth Orchestra
ov-verbier: overseas | ヴェルビエ祝祭室内管弦楽団 | Verbier Festival Chamber Orchestra
ov-belgian-national: overseas | ベルギー国立管弦楽団 | Belgian National Orchestra
ov-staatskapelle-berlin: overseas | ベルリン国立歌劇場管弦楽団 | シュターツカペレ・ベルリン, Staatskapelle Berlin
ov-utopia: overseas | ユートピア管弦楽団 | Utopia Orchestra
"""

# Chinese names, only to find an orchestra by typing in the orchestra filter and to recognise it in Chinese text (the sources are Japanese)
_ZH = {
    "nhkso": "NHK交响乐团, N响", "tmso": "东京都交响乐团, 都响", "tso": "东京交响乐团, 东响", "jpo": "日本爱乐, 日本爱乐乐团", "njp": "新日本爱乐, 新日本爱乐乐团",
    "yomikyo": "读卖日本交响乐团, 读响", "tpo": "东京爱乐, 东京爱乐乐团", "jp-tcpo": "东京都市爱乐", "jp-kanagawa-phil": "神奈川爱乐", "jp-sapporo": "札幌交响乐团",
    "jp-osaka-phil": "大阪爱乐", "jp-kyoto": "京都市交响乐团", "jp-oek": "金泽管弦乐团", "jp-bcj": "巴赫学院日本",
    "ov-berlin-phil": "柏林爱乐, 柏林爱乐乐团", "ov-vienna-phil": "维也纳爱乐, 维也纳爱乐乐团", "ov-vienna-so": "维也纳交响乐团", "ov-br-so": "巴伐利亚广播交响乐团",
    "ov-munich-phil": "慕尼黑爱乐", "ov-dresden": "德累斯顿国家管弦乐团, 德累斯顿乐团", "ov-gewandhaus": "莱比锡布商大厦管弦乐团, 布商大厦", "ov-ndr-elbphil": "北德广播易北爱乐乐团, 汉堡易北爱乐",
    "ov-bamberg": "班贝格交响乐团", "ov-dso-berlin": "柏林德意志交响乐团", "ov-rsb": "柏林广播交响乐团", "ov-hr": "黑森广播交响乐团, 法兰克福广播交响乐团",
    "ov-wdr": "科隆西德广播交响乐团", "ov-mco": "马勒室内乐团", "ov-coe": "欧洲室内乐团", "ov-concertgebouw": "皇家音乐厅管弦乐团, 阿姆斯特丹皇家音乐厅",
    "ov-rotterdam": "鹿特丹爱乐", "ov-lso": "伦敦交响乐团", "ov-lpo": "伦敦爱乐, 伦敦爱乐乐团", "ov-philharmonia": "爱乐管弦乐团, 伦敦爱乐管弦乐团", "ov-rpo": "皇家爱乐乐团",
    "ov-bbc-so": "BBC交响乐团", "ov-paris": "巴黎管弦乐团", "ov-onf": "法国国家管弦乐团", "ov-toulouse": "图卢兹国立管弦乐团", "ov-czech-phil": "捷克爱乐, 捷克爱乐乐团",
    "ov-prague-so": "布拉格交响乐团", "ov-budapest-festival": "布达佩斯节日管弦乐团", "ov-warsaw-phil": "华沙爱乐", "ov-ukraine-opera": "乌克兰国家歌剧院管弦乐团",
    "ov-vienna-strauss": "维也纳约翰·施特劳斯管弦乐团", "ov-vienna-waltz-festival": "维也纳华尔兹庆典管弦乐团", "ov-wiener-ring": "维也纳环形重奏团", "ov-europa-galante": "欧罗巴加兰特",
    "ov-valencia": "瓦伦西亚管弦乐团", "ov-santa-cecilia": "圣切契利亚学院管弦乐团", "ov-scala": "斯卡拉爱乐, 米兰斯卡拉歌剧院爱乐乐团", "ov-tonhalle": "苏黎世音乐厅管弦乐团",
    "ov-osr": "瑞士罗曼德管弦乐团", "ov-lucerne": "琉森节日管弦乐团", "ov-oslo": "奥斯陆爱乐", "ov-helsinki": "赫尔辛基爱乐", "ov-finnish-rso": "芬兰广播交响乐团",
    "ov-swedish-rso": "瑞典广播交响乐团", "ov-st-petersburg": "圣彼得堡爱乐", "ov-israel-phil": "以色列爱乐", "ov-nyphil": "纽约爱乐", "ov-chicago": "芝加哥交响乐团",
    "ov-boston": "波士顿交响乐团", "ov-philadelphia": "费城管弦乐团", "ov-cleveland": "克利夫兰管弦乐团", "ov-la-phil": "洛杉矶爱乐", "ov-sf": "旧金山交响乐团",
    "ov-montreal": "蒙特利尔交响乐团", "ov-toronto": "多伦多交响乐团", "ov-sydney": "悉尼交响乐团", "ov-hk-phil": "香港管弦乐团, 港乐", "ov-taipei": "台北市立交响乐团",
    "ov-seoul-phil": "首尔爱乐", "ov-kbs": "KBS交响乐团", "ov-singapore": "新加坡交响乐团",
    "ov-simon-bolivar": "西蒙·玻利瓦尔交响乐团", "ov-polish-amadeus": "波兰国家广播阿马德乌斯室内乐团", "ov-belgium-chamber": "比利时皇家室内乐团", "ov-concert-des-nations": "万国音乐会乐团",
    "ov-cbso": "伯明翰市交响乐团", "ov-prague-rso": "布拉格广播交响乐团", "ov-paris-chamber": "巴黎室内乐团", "ov-berlin-so": "柏林交响乐团", "ov-evergreen": "长荣交响乐团",
    "ov-orpheus": "奥菲斯室内乐团", "ov-brussels-phil": "布鲁塞尔爱乐", "ov-dkam": "德国室内爱乐乐团, 不来梅室内爱乐", "ov-warsaw-national": "华沙国家爱乐乐团",
    "ov-lucerne-festival-chamber": "琉森音乐节室内乐团", "ov-gaertnerplatz": "慕尼黑加特纳广场州立剧院管弦乐团", "ov-stuttgart-phil": "斯图加特爱乐",
    "ov-radio-france-phil": "法国广播爱乐乐团", "ov-toulouse-capitole": "图卢兹国会大厦管弦乐团", "ov-camerata-salzburg": "萨尔茨堡室内乐团", "ov-slovak-phil": "斯洛伐克爱乐",
    "ov-dresden-phil": "德累斯顿爱乐", "ov-boston-phil-youth": "波士顿爱乐青年管弦乐团", "ov-verbier": "韦尔比耶音乐节室内乐团", "ov-belgian-national": "比利时国家管弦乐团",
    "ov-staatskapelle-berlin": "柏林国家歌剧院管弦乐团, 柏林国立歌剧院乐团", "ov-utopia": "乌托邦管弦乐团",
}

ORCHESTRAS: dict[str, dict] = {}
_ALIASES: list[tuple[str, str]] = []  # (normalised alias, key), longest first
for _line in _TABLE.strip().splitlines():
    _key, _rest = _line.split(":", 1)
    _parts = [x.strip() for x in _rest.split("|")]
    _origin, _display = _parts[0], _parts[1]
    _names = [_display] + ([x.strip() for x in _parts[2].split(",")] if len(_parts) > 2 else [])
    _names += [x.strip() for x in _ZH.get(_key.strip(), "").split(",") if x.strip()]
    # "names": what a person might type to find it (short names, English, Chinese); the display name itself is searched too
    ORCHESTRAS[_key.strip()] = {"key": _key.strip(), "display": _display, "origin": _origin, "names": " ".join(_names[1:])}
    for _name in _names:
        if n(_name):
            _ALIASES.append((n(_name), _key.strip()))
_ALIASES.sort(key=lambda x: -len(x[0]))
SEVEN = [k for k, v in ORCHESTRAS.items() if v["origin"] == "seven"]


_MEMBER = ("の", "首席", "団員", "メンバー", "奏者", "コンサートマスター", "ソロ", "出身", "元")


def detect(texts: list[str]) -> list[str]:
    """Known orchestra keys mentioned in ``texts`` (longest alias first; matched spans are consumed).

    An alias followed by a member/possessive marker ("ウィーン・フィルの至宝", "ベルリン・フィル首席") names a person's affiliation,
    not the orchestra on stage, and is skipped.
    """
    found: list[str] = []
    for text in texts:
        t = n(text)
        for alias, key in _ALIASES:
            start = t.find(alias)
            while start != -1:
                after = t[start + len(alias):]
                if not after.startswith(_MEMBER) and key not in found:
                    found.append(key)
                t = t[:start] + "\x00" + after
                start = t.find(alias)
    return found


def concert_orchestras(source_id: str, title: str, artist_names: list[str]) -> list[str]:
    """The seven orchestra sites list their own concerts: their orchestra is the source; other orchestras only via performer names."""
    keys = [source_id] if source_id in SEVEN else []
    texts = list(artist_names or []) if source_id in SEVEN else [title or ""] + list(artist_names or [])
    for k in detect(texts):
        if k not in keys:
            keys.append(k)
    return keys


def suggest_category(source_id: str, title: str, artist_names: list[str], poc_hint: str) -> str:
    """Category hint for a candidate (a human still confirms): piano recital > overseas visit > one of the seven > other."""
    if poc_hint == "piano_recital":
        return "piano_recital"
    keys = concert_orchestras(source_id, title, artist_names)
    if any(ORCHESTRAS[k]["origin"] == "overseas" for k in keys):
        return "overseas_orchestra_visit"
    if source_id in SEVEN or any(ORCHESTRAS[k]["origin"] == "seven" for k in keys):
        return "domestic_orchestra"
    return "other"
