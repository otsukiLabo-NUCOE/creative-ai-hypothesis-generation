# build_knowledge_space.py
#
# Builds the knowledge space K used in the revised experiments (Reviewer 1 #4, Reviewer 2 #1):
# replaces the three hard-coded "simulated" reference papers of the original version with
# several thousand real paper records (title + abstract + submission date) retrieved from the
# public arXiv API (metadata is CC0).
#
# Two temporally disjoint windows are collected:
#   - "past"   : 2020-01-01 .. 2023-12-31  -> the knowledge space the GA is allowed to see
#   - "future" : 2024-07-01 .. 2025-12-31  -> held out; never seen by the GA, used only for the
#                                             temporal-holdout evaluation (Section 4 of the paper)
#
# Two retrieval routes are combined in each window:
#   (a) targeted : one query per concept term in the Method/Problem/Goal vocabulary
#                  (the query-driven acquisition of Equations (5)-(7)), and
#   (b) background: a seeded pseudo-random day per month in cs.AI/cs.LG/cs.CL/cs.NE, so that
#                  the knowledge space is not limited to the vocabulary itself.
#
# Output: ../data/corpus.jsonl  (one record per line, de-duplicated by arXiv id)
#         ../data/corpus_build_log.json (queries issued, counts, timestamps)
#
# Usage:  python build_knowledge_space.py           (takes ~10-15 min; arXiv asks for >=3 s/request)

import json
import os
import random
import time
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from concepts import CONCEPTS

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
CATS = "(cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.NE)"
WINDOWS = {
    "past": ("202001010000", "202312312359"),
    "future": ("202407010000", "202512312359"),
}
TARGETED_PER_TERM = 25
BACKGROUND_PER_MONTH = 40
SLEEP_S = 4.0
SEED = 20261001


def fetch(search_query, max_results, sort_by):
    params = {"search_query": search_query, "start": 0, "max_results": max_results,
              "sortBy": sort_by, "sortOrder": "descending"}
    url = API + "?" + urllib.parse.urlencode(params, safe=":()[]\"*")
    for attempt in range(6):
        time.sleep(SLEEP_S * (1 + attempt))
        try:
            r = requests.get(url, timeout=60)
        except requests.RequestException:
            continue
        if r.status_code == 200 and "Rate exceeded" not in r.text[:200]:
            return parse(r.text)
    print(f"  [skip] gave up on: {search_query}")
    return []


def parse(xml_text):
    out = []
    root = ET.fromstring(xml_text)
    for e in root.findall("a:entry", NS):
        aid = e.findtext("a:id", default="", namespaces=NS).rsplit("/", 1)[-1]
        title = " ".join(e.findtext("a:title", default="", namespaces=NS).split())
        abstract = " ".join(e.findtext("a:summary", default="", namespaces=NS).split())
        published = e.findtext("a:published", default="", namespaces=NS)[:10]
        if aid and title and abstract:
            out.append({"id": aid.split("v")[0] if "v" in aid else aid, "title": title,
                        "abstract": abstract, "date": published})
    return out


def month_iter(start, end):
    y, m = int(start[:4]), int(start[4:6])
    ey, em = int(end[:4]), int(end[4:6])
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    rng = random.Random(SEED)
    records, log = {}, {"started": datetime.datetime.now().isoformat(), "queries": []}
    terms = [t for cat in CONCEPTS.values() for t in cat]

    for window, (lo, hi) in WINDOWS.items():
        date_clause = f"submittedDate:[{lo} TO {hi}]"
        for t in terms:
            q = f'abs:"{t}" AND {CATS} AND {date_clause}'
            got = fetch(q, TARGETED_PER_TERM, "relevance")
            log["queries"].append({"window": window, "route": "targeted", "q": q, "n": len(got)})
            for rec in got:
                rec.update(window=window, route="targeted", query=t)
                records.setdefault(rec["id"], rec)
            print(f"[{window}] targeted '{t}': {len(got)}  (total {len(records)})")
        for y, m in month_iter(lo, hi):
            d = rng.randint(1, 28)
            day = f"{y:04d}{m:02d}{d:02d}"
            q = f"{CATS} AND submittedDate:[{day}0000 TO {day}2359]"
            got = fetch(q, BACKGROUND_PER_MONTH, "submittedDate")
            log["queries"].append({"window": window, "route": "background", "q": q, "n": len(got)})
            for rec in got:
                rec.update(window=window, route="background", query=day)
                records.setdefault(rec["id"], rec)
            print(f"[{window}] background {day}: {len(got)}  (total {len(records)})")

    # guard against window leakage (a paper must fall inside the window it was filed under)
    clean = []
    for r in records.values():
        ymd = r["date"].replace("-", "")
        lo, hi = WINDOWS[r["window"]]
        if lo[:8] <= ymd <= hi[:8]:
            clean.append(r)
    with open(os.path.join(DATA_DIR, "corpus.jsonl"), "w", encoding="utf-8") as f:
        for r in sorted(clean, key=lambda r: (r["window"], r["date"], r["id"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log["finished"] = datetime.datetime.now().isoformat()
    log["n_records"] = {w: sum(1 for r in clean if r["window"] == w) for w in WINDOWS}
    with open(os.path.join(DATA_DIR, "corpus_build_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print("done:", log["n_records"])


if __name__ == "__main__":
    main()
