"""One-shot policy/landing-page inventory, not a scheduler or full-site crawl."""
import json
import argparse
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from classical_radar.network import Reader, robots_allowed
from classical_radar.sources import SOURCES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",choices=sorted(SOURCES),action="append")
    parser.add_argument("--output",type=Path,default=Path("evidence/local-probe.json"))
    args=parser.parse_args()
    reader = Reader(Path("evidence/raw"))
    report = []
    try:
        for s in SOURCES.values():
            if args.source and s.id not in args.source:
                continue
            row = {"source_id": s.id, "name": s.name, "list_url": s.url, "policy_status": "unknown", "scheduled_collection": False}
            host = urlsplit(s.url).hostname
            try:
                robots, meta = reader.get(f"https://{host}/robots.txt", host)
                row["robots"] = {**meta, "allows_list": robots_allowed(robots, meta["status"], s.url)}
                if meta["status"] == 200:
                    row["robots"]["rules"] = robots[:6000]
                if not row["robots"]["allows_list"]:
                    row["blocked"] = "robots excludes list; no list fetch"
                else:
                    html, page = reader.get(s.url, host)
                    soup = BeautifulSoup(html, "html.parser")
                    row["list"] = page
                    row["title"] = soup.title.get_text(" ", strip=True) if soup.title else None
                    links = {}
                    policies = {}
                    for a in soup.select("a[href]"):
                        url = urljoin(page["url"], a["href"])
                        text = a.get_text(" ", strip=True)
                        if urlsplit(url).hostname not in {host, host.removeprefix("www."), "www."+host.removeprefix("www.")}:
                            continue
                        if s.is_detail(urlsplit(url).path):
                            links[url.split("#")[0]] = text[:250]
                        if any(t in text for t in ["利用規約", "著作権", "サイトポリシー", "ご利用", "サイトについて", "プライバシー"]):
                            policies[url] = text
                    row["detail_links"] = [{"url": k, "label": v} for k,v in links.items()]
                    row["policy_links"] = policies
                    row["structured_data_blocks"] = len(soup.select('script[type="application/ld+json"]'))
            except Exception as exc:
                row["error"] = str(exc)
            report.append(row)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
            status = row.get("error") or row.get("blocked") or f"HTTP {row['list']['status']}; detail candidates={len(row['detail_links'])}"
            print(s.id, status, flush=True)
    finally:
        reader.close()


if __name__ == "__main__":
    main()
