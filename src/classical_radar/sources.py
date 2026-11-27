"""The final conversation limits domestic coverage to these seven orchestras."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    detail_pattern: str
    category: str = "domestic_orchestra"
    # Which card leads when a human says two sources list the same concert (ADR-0006): lower wins. 0 = the orchestra's own site,
    # 1 = the presenter that runs the tour/recital, 2 = a regional presenter that also sells it. Only a suggestion for the reviewer.
    card_rank: int = 0

    def is_detail(self, path: str) -> bool:
        return bool(re.search(self.detail_pattern, path))


SOURCES = {
    s.id: s for s in [
        Source("nhkso", "NHK交響楽団", "https://www.nhkso.or.jp/concert/", r"/concert/\d+"),
        Source("tmso", "東京都交響楽団", "https://www.tmso.or.jp/j/concert/", r"/j/concert/detail/detail\.php"),
        Source("tso", "東京交響楽団", "https://tokyosymphony.jp/concert/", r"/concerts?/[^/?]+"),
        Source("jpo", "日本フィルハーモニー交響楽団", "https://japanphil.or.jp/concert/", r"/concert/\d+"),
        Source("njp", "新日本フィルハーモニー交響楽団", "https://www.njp.or.jp/concerts/", r"/concerts/\d+"),
        Source("yomikyo", "読売日本交響楽団", "https://yomikyo.or.jp/concert/", r"/concert/[^/?]+"),
        Source("tpo", "東京フィルハーモニー交響楽団", "https://www.tpo.or.jp/concert/", r"/concert/[^/?]+\.php"),
        Source("japanarts", "ジャパン・アーツ", "https://www.japanarts.co.jp/concert/", r"/concert/[^/?]+", "mixed_presenter", 1),
        Source("kajimoto", "KAJIMOTO", "https://www.kajimotomusic.com/concerts/", r"/concerts/[^/?]+", "mixed_presenter", 1),
        Source("kanagawa_geikyo", "神奈川芸術協会", "https://kanagawa-geikyo.com/concert/", r"/concert/[^/?]+", "mixed_presenter", 2),
    ]
}


# ADR-0001: the user took 東京フィルハーモニー交響楽団 out of the current execution scope. It stays registered (scope
# authority is 00_DECISIONS.md) but no script may fetch it and no coverage claim may include it.
DEFERRED = frozenset({"tpo"})
