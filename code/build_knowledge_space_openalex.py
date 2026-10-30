# build_knowledge_space_openalex.py
# Builds data/corpus.jsonl from OpenAlex instead of arXiv (for fields with few arXiv papers,
# e.g. management information systems). Same output format as build_knowledge_space.py.
#   python build_knowledge_space_openalex.py
import datetime
import json
import os
import time

import requests

from concepts import CONCEPTS

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
API = "https://api.openalex.org/works"
API_KEY = os.environ.get("OPENALEX_API_KEY")      # free key: https://openalex.org/settings/api

# OpenAlex fields: 14 Business, Management and Accounting / 17 Computer Science / 18 Decision Sciences
FIELDS = "14|17|18"
WINDOWS = {
    "past": ("2021-01-01", "2025-06-30"),     # papers the GA compares with
    "future": ("2025-07-01", "2025-12-31"),   # held out for evaluation (must not be empty)
}
# papers per vocabulary term and random field-wide papers, per window. The held-out "future" set is kept
# small: the model holds out as many past papers as there are future papers, so a large future set would
# leave fewer papers for the GA to compare with.
PER_TERM = {"past": 50, "future": 5}
BACKGROUND = {"past": 200, "future": 50}   # max 200
SEED = 20261001


def get(params):
    params = {**params, "filter": params["filter"] + ",has_abstract:true,language:en"}
    if API_KEY:
        params["api_key"] = API_KEY
    for attempt in range(5):
        try:
            r = requests.get(API, params=params, timeout=60)
            if r.status_code == 200:
                return r.json().get("results", [])
            if r.status_code == 429 and "budget" in r.text.lower():
                raise SystemExit("OpenAlex: the daily request budget is used up. Set a free API key "
                                 "(https://openalex.org/settings/api) in the environment variable OPENALEX_API_KEY, "
                                 "or try again after midnight UTC. Nothing was written.")
            print(f"  HTTP {r.status_code}: {r.text[:120]}")
        except requests.RequestException as e:
            print("  ", e)
        time.sleep(3 * (attempt + 1))
    return []


def abstract(inv):
    """OpenAlex stores abstracts as an inverted index {word: [positions]}."""
    pos = {i: w for w, idx in (inv or {}).items() for i in idx}
    return " ".join(pos[i] for i in sorted(pos))


def to_record(w, window, route, query):
    return {"id": w["id"].rsplit("/", 1)[-1], "title": " ".join((w.get("title") or "").split()),
            "abstract": abstract(w.get("abstract_inverted_index")), "date": w.get("publication_date", ""),
            "window": window, "route": route, "query": query}


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    terms = [t for cat in CONCEPTS.values() for t in cat]
    records, log = {}, {"source": "OpenAlex", "started": datetime.datetime.now().isoformat(), "queries": []}
    select = "id,title,publication_date,abstract_inverted_index"
    for window, (lo, hi) in WINDOWS.items():
        base = f"from_publication_date:{lo},to_publication_date:{hi},primary_topic.field.id:{FIELDS}"
        for t in terms:
            got = get({"search": f'"{t}"', "filter": base, "per-page": PER_TERM[window], "select": select})
            log["queries"].append({"window": window, "route": "targeted", "q": f'"{t}"', "n": len(got)})
            for w in got:
                r = to_record(w, window, "targeted", t)
                if r["title"] and r["abstract"]:
                    records.setdefault(r["id"], r)
            print(f"[{window}] '{t}': {len(got)}  (total {len(records)})")
            time.sleep(1)
        got = get({"filter": base, "sample": BACKGROUND[window], "seed": SEED, "per-page": BACKGROUND[window],
                   "select": select})
        log["queries"].append({"window": window, "route": "background", "q": "random sample", "n": len(got)})
        for w in got:
            r = to_record(w, window, "background", "sample")
            if r["title"] and r["abstract"]:
                records.setdefault(r["id"], r)
        print(f"[{window}] background sample: {len(got)}  (total {len(records)})")
    with open(os.path.join(DATA_DIR, "corpus.jsonl"), "w", encoding="utf-8") as f:
        for r in sorted(records.values(), key=lambda r: (r["window"], r["date"], r["id"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log["finished"] = datetime.datetime.now().isoformat()
    log["n_records"] = {w: sum(1 for r in records.values() if r["window"] == w) for w in WINDOWS}
    with open(os.path.join(DATA_DIR, "corpus_build_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print("done:", log["n_records"])


if __name__ == "__main__":
    main()
