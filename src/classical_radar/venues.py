"""Venue label -> JIS prefecture code (ADR-0001). Only venues known with certainty are listed.

Order matters: the first matching pattern wins, so a more specific pattern must precede a general one
(e.g. ミューザ川崎 before サントリー, because one Yomikyo note mentions both halls). An unknown venue
returns None and is never guessed; ``official_confirmed`` then needs an explicit prefecture from the reviewer.
"""
import re
import unicodedata

KANTO = {"11", "12", "13", "14"}  # 3.5: 埼玉/千葉/東京/神奈川 form the capital-region bucket

# source-provided prefix such as "東京/ サントリーホール" (KAJIMOTO) is direct evidence
_PREFIX = {"東京": "13", "神奈川": "14", "埼玉": "11", "千葉": "12", "大阪": "27", "愛知": "23", "福岡": "40", "北海道": "01"}

_TABLE = [
    ("14", ["ミューザ川崎", "横浜みなとみらい", "神奈川県立音楽堂", "横浜能楽堂", "茅ヶ崎市民文化会館", "よこすか芸術劇場", "ヨコスカ・ベイサイド・ポケット",
            "昭和音楽大学", "相模女子大学", "カルッツかわさき", "戸塚区民文化センター"]),
    ("13", ["サントリーホール", "東京芸術劇場", "東京オペラシティ", "NHKホール", "すみだトリフォニー", "浜離宮朝日", "日生劇場", "Bunkamura",
            "日本製鉄紀尾井", "ドイツ文化会館", "杉並公会堂", "Hakuju", "ヤマハホール", "第一生命ホール", "ルーテル市ヶ谷", "北とぴあ", "大田区民",
            "ムジカーザ", "町田市民ホール", "J:COMホール八王子", "文京シビックホール", "パルテノン多摩", "ルネこだいら", "S&D秋川キララ",
            "曳舟文化センター", "練馬文化センター", "両国国技館", "銀座王子ホール", "王子ホール", "府中の森芸術劇場", "武蔵野市民文化会館",
            "TOPPANホール", "東京文化会館", "紀尾井ホール", "ハクジュホール", "プリモホールゆとろぎ", "調布市グリーンホール", "サントリー"]),
    ("11", ["ソニックシティ", "所沢市民文化センター", "RaiBoC", "ウェスタ川越"]),
    ("12", ["千葉市民会館", "市川市文化会館", "浦安市文化会館", "森のホール21"]),
    ("01", ["札幌コンサートホールKitara", "Kitara"]),
    ("04", ["仙台銀行ホール"]), ("06", ["山形テルサ"]), ("07", ["白河文化交流館コミネス", "けんしん郡山文化センター"]),
    ("09", ["宇都宮市文化会館", "あしかがフラワーパークプラザ"]), ("10", ["高崎芸術劇場"]), ("08", ["ザ・ヒロサワ・シティ会館", "茨城県民文化センター"]),
    ("15", ["りゅーとぴあ"]), ("18", ["ハーモニーホールふくい"]), ("20", ["岡谷市文化会館"]), ("21", ["土岐市文化プラザ"]),
    ("22", ["アクトシティ浜松", "静岡市清水文化会館", "グランシップ"]), ("23", ["愛知県芸術劇場", "刈谷市総合文化センター"]),
    ("26", ["京都コンサートホール"]), ("27", ["フェスティバルホール", "ザ・シンフォニーホール"]), ("35", ["シンフォニア岩国"]),
    ("37", ["シアターマド"]), ("38", ["愛媛県県民文化会館"]),
    ("40", ["福岡シンフォニーホール", "アクロス福岡", "久留米シティプラザ", "デンカ大牟田", "J:COM北九州芸術劇場"]),
    ("41", ["佐賀市文化会館"]), ("42", ["長崎市民会館"]), ("44", ["iichiko"]), ("45", ["宮崎県立芸術劇場"]), ("46", ["鹿児島県文化センター"]),
]


def _norm(label: str) -> str:
    return re.sub(r"[\s　]", "", unicodedata.normalize("NFKC", label or ""))


def prefecture_code(venue: str | None) -> str | None:
    n = _norm(venue or "")
    if not n:
        return None
    head = re.match(r"^([^/]{2,4})/", n)
    if head and head.group(1) in _PREFIX:
        return _PREFIX[head.group(1)]
    for code, names in _TABLE:
        for name in names:
            if _norm(name) in n:
                return code
    return None
