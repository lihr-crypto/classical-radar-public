"""Replay local, untracked source captures; export factual results, never full pages."""
import json
from pathlib import Path

from bs4 import BeautifulSoup
from classical_radar.parsers import LIST_SELECTORS, parse_list, parse_nhk, parse_presenter_detail


def read(meta):
    return (Path("evidence/raw")/(meta["sha256"]+".html")).read_text()


def save(path, data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")


def minimize(node, allowed_selectors):
    # Keep selector skeleton, but only factual title/date/venue text. Drop essays,
    # images, styles, inline scripts, unrelated links and personal information.
    clone=BeautifulSoup(str(node),"html.parser")
    for bad in clone.select("img,svg,script,style,noscript,iframe"):
        bad.decompose()
    keep=set()
    for selector in allowed_selectors:
        for n in clone.select(selector):
            keep.update(id(x) for x in n.descendants)
    for string in list(clone.find_all(string=True)):
        if id(string) not in keep:
            string.extract()
    for n in clone.find_all(True):
        n.attrs={k:v for k,v in n.attrs.items() if k in {"class","id","href"}}
    return str(clone)


def main():
    probe=json.loads(Path("evidence/probe.json").read_text())
    details=json.loads(Path("evidence/details.json").read_text())
    extra=json.loads(Path("evidence/extra.json").read_text())
    inventory,records,fixture_meta=[],[],[]
    keep={
        "tmso":[".entry-title",".entry-date",".entry-hall"],
        "tso":["h3",".concertslist__contents-date",".concertslist__contents-time",".concertslist__contents-location"],
        "jpo":[".cardPostDetail__ttl",".noteIcon"],
        "njp":[".--title",".--date",".--place"],
        "tpo":["h3",".year",".day",".spot"],
        "japanarts":["h3","dl dt","dl dd"],
        "kajimoto":[".item_header",".item_label"],
        "kanagawa_geikyo":["h1",".published",".concert-place-btn"],
    }
    for row in probe:
        key=row["source_id"]
        if key not in LIST_SELECTORS:
            continue
        page=row["list"]
        out,meta=parse_list(key,read(page),page["url"],page["fetched_at"])
        records.extend(out)
        inventory.append({"source_id":key,**meta,"dated_candidates":sum(bool(x["local_date"]) for x in out),"with_venue":sum(bool(x["venue"]) for x in out),"source_sha256":page["sha256"],"global_coverage_n":None,"global_coverage_N":None})
        soup=BeautifulSoup(read(page),"html.parser")
        nodes=soup.select(LIST_SELECTORS[key])
        # A compact factual fragment can be shared; original responses stay ignored.
        if key=="tpo":
            nodes=[n for n in nodes if n.select_one(".more a")][:2]
        else:
            nodes=nodes[:2]
        fragment="\n".join(minimize(n,keep[key]) for n in nodes)
        path=f"tests/fixtures/{key}-list.html"
        Path(path).write_text(fragment+"\n")
        expected,stats=parse_list(key,fragment,page["url"])
        fixture_meta.append({"source_id":key,"kind":"list","file":path,"url":page["url"],"fetched_at":page["fetched_at"],"source_sha256":page["sha256"],"expected":[{k:x[k] for k in ["title","local_date","local_time","venue"]} for x in expected]})
    nhk=next(x for x in extra if "archive_concert_2026.json" in x["url"])
    halls=next(x for x in details if "hall_all.json" in x.get("url",""))
    nhkdata=json.loads(read(nhk));halldata=json.loads(read(halls))
    nhkout=parse_nhk(nhkdata,halldata,nhk["url"],nhk["fetched_at"])
    records.extend(nhkout)
    inventory.append({"source_id":"nhkso","dom_programmes":len(nhkdata["concerts"]),"unique_candidates":len(nhkout),"dated_candidates":sum(bool(x["local_date"]) for x in nhkout),"with_venue":sum(bool(x["venue"]) for x in nhkout),"scope":"one public 2026-season JSON (includes 2027 dates); no whole-site denominator","source_sha256":nhk["sha256"],"global_coverage_n":None,"global_coverage_N":None})
    fixture_events=[x for x in nhkdata["concerts"] if "2074" in x["title"]]
    save("tests/fixtures/nhkso-list.json",{"concerts":fixture_events})
    save("tests/fixtures/nhkso-halls.json",{"hall_info":{x["hall_id"]:halldata["hall_info"][x["hall_id"]] for x in fixture_events}})
    presenter_samples=[]
    for row in details:
        key=row["source_id"]
        if key not in {"japanarts","kajimoto","yomikyo"} or row.get("status")!=200:
            continue
        out=parse_presenter_detail(key,read(row),row["url"],row["fetched_at"])
        presenter_samples.append({"source_id":key,"source_url":row["url"],"source_sha256":row["sha256"],**out})
        soup=BeautifulSoup(read(row),"html.parser")
        if key=="japanarts":
            nodes=[soup.select_one("h1")]+[n for n in soup.select("div.list-type-3") if n.find("dt",string=lambda t:t and t.strip()=="日時")]
            fragment="\n".join(str(n) for n in nodes)
            fragment=minimize(BeautifulSoup(fragment,"html.parser"),["h1","dl dt","dl dd"])
        elif key=="yomikyo":
            fragment=str(soup.select_one(".concert_info_main"))
        else:
            fragment=str(soup.select_one("h1"))+"<article id='information'>"
            for node in soup.select("#information section.concert_info"):
                fragment+=minimize(node,[".concert_info_dates_date",".concert_info_venue_name"])
            fragment+="</article>"
            for p in soup.select("p.wp-block-paragraph"):
                if "一般発売" in p.get_text() or ("会員" in p.get_text() and "先行" in p.get_text()):
                    fragment+=str(p)
        name=row["url"].strip("/").rsplit("/",1)[-1]
        path=f"tests/fixtures/{key}-{name}-detail.html"
        Path(path).write_text(fragment+"\n")
        fixture_meta.append({"source_id":key,"kind":"detail","file":path,"url":row["url"],"fetched_at":row["fetched_at"],"source_sha256":row["sha256"],"expected":[{k:x[k] for k in ["title","local_date","local_time","venue"]} for x in out["performances"]],"ticket_claim_count":len(out["ticket_claims"])})
    save("tests/fixtures/manifest.json",fixture_meta)
    inventory.append({"source_id":"yomikyo","unique_candidates":2,"dated_candidates":2,"with_venue":2,"scope":"two detail URLs discovered in landing topics; no future month enumeration adapter","global_coverage_n":None,"global_coverage_N":None})
    save("evidence/list-candidates.json",records)
    save("evidence/presenter-samples.json",presenter_samples)
    save("evidence/coverage.json",inventory)
    print(json.dumps(inventory,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
