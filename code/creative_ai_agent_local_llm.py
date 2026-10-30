# creative_ai_agent_local_llm.py  (revised, Revision 1)
#
# End-to-end pipeline of the proposed model: revised GA (creative_ga.py) -> LLM writing step via a
# local llama.cpp server (OpenAI-compatible API). Used for Condition A of the pilot case study.
#
# Changes from the submitted version:
#   * Uses the revised GA (real arXiv knowledge space, shared sentence-embedding space,
#     literature-grounded utility; see creative_ga.py) instead of the hash-vector GA.
#   * Every stochastic element is seeded and recorded (R1 #3, #7): GA seed (--seed) and the LLM
#     sampling seed (passed to llama.cpp as "seed"), temperature, top_p, max_tokens.
#   * Every call is logged to ../results/writer_logs/<run_id>.json: the exact system prompt, the
#     exact user prompt, the GA output, model name, decoding parameters, finish_reason and the
#     raw response, so that a third party can audit or re-run the writing step.
#   * --source {ga,random} lets the SAME writer, prompt, decoding settings and seed be driven by
#     a GA-selected hypothesis or by a uniformly random one (a controlled comparison in which
#     only the hypothesis-selection method differs; R1 #5, R2 #3).
#   * The prompts are stored verbatim in ../prompts/ (also those used for Conditions B and C).
#   * v1.0.3: --refs K (default 8) grounds the manuscript in REAL papers. The K papers of the knowledge
#     space closest to the hypothesis (and to its pairwise links) are retrieved, their bibliographic data
#     are fetched from OpenAlex (OpenAlex ids) or arXiv (arXiv ids), and the writer may cite ONLY these
#     papers as [n]. The reference list is appended by this script (not written by the LLM), and citation
#     numbers outside the list are reported. --refs 0 reproduces Condition A of the pilot case study
#     (no citations; prompts/condition_A_system_prompt.txt).
#
# Usage (llama-server must be running):
#   python creative_ai_agent_local_llm.py --seed 1 --source ga            # with 8 real references
#   python creative_ai_agent_local_llm.py --seed 1 --source ga --refs 0   # as in the paper (no citations)
#   python creative_ai_agent_local_llm.py --seed 1 --source random

import argparse
import datetime
import json
import os
import random
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np
import requests

import creative_ga as cg

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_DIR = os.path.join(HERE, "..", "prompts")
LOG_DIR = os.path.join(HERE, "..", "results", "writer_logs")
OUT_DIR = os.path.join(HERE, "..", "results", "manuscripts")

LLM_ENDPOINT = os.environ.get("LLAMA_SERVER_ENDPOINT", "http://127.0.0.1:8080/v1/chat/completions")
LLM_MODEL_NAME = os.environ.get("LLAMA_SERVER_MODEL_NAME", "gpt-oss-120b")
LLM_TIMEOUT_S = int(os.environ.get("LLM_TIMEOUT_S", "7200"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "6000"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
LLM_TOP_P = float(os.environ.get("LLM_TOP_P", "1.0"))


def read_prompt(name):
    with open(os.path.join(PROMPT_DIR, name), encoding="utf-8") as f:
        return f.read().strip()


def build_user_prompt(facts):
    return ("GROUND TRUTH FACTS (JSON):\n" + json.dumps(facts, ensure_ascii=False, indent=2) +
            "\n\nUsing only these facts as your grounding, write the manuscript now.")


# ------------------------------------------------------------------ real references (v1.0.3)
EXCERPT_CHARS = 350


def select_references(land, ks, emb, t, k):
    """The k papers of the search partition closest to the hypothesis sentence and to its three
    pairwise links (taken in turn, without duplicates)."""
    from concepts import pair_texts
    m, p, g = land.M[t[0]], land.P[t[1]], land.G[t[2]]
    queries = [land.Z[land.flat(t)]] + list(emb.encode(list(pair_texts(m, p, g))))
    ranked = [np.argsort(-(ks.V_search @ q)) for q in queries]
    chosen, depth = [], 0
    while len(chosen) < k and depth < len(ks.search):
        for order in ranked:
            i = int(order[depth])
            if i not in chosen and len(chosen) < k:
                chosen.append(i)
        depth += 1
    return [ks.search[i] for i in chosen]


def fetch_bibliography(papers):
    """Authors, year, venue and link for each paper (OpenAlex ids start with 'W', otherwise arXiv ids).
    Falls back to title, date and id when the lookup fails."""
    info = {}
    oa = [p["id"] for p in papers if p["id"].startswith("W")]
    ax = [p["id"] for p in papers if not p["id"].startswith("W")]
    if oa:
        params = {"filter": "openalex_id:" + "|".join(oa), "per-page": len(oa),
                  "select": "id,doi,title,publication_year,authorships,primary_location"}
        if os.environ.get("OPENALEX_API_KEY"):
            params["api_key"] = os.environ["OPENALEX_API_KEY"]
        try:
            r = requests.get("https://api.openalex.org/works", params=params, timeout=60)
            for w in (r.json().get("results", []) if r.status_code == 200 else []):
                src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
                info[w["id"].rsplit("/", 1)[-1]] = {
                    "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
                    "year": w.get("publication_year"), "venue": src,
                    "link": w.get("doi") or w["id"]}
        except (requests.RequestException, ValueError):
            pass
    if ax:
        try:
            r = requests.get("http://export.arxiv.org/api/query",
                             params={"id_list": ",".join(ax), "max_results": len(ax)}, timeout=60)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for e in ET.fromstring(r.text).findall("a:entry", ns):
                aid = e.findtext("a:id", default="", namespaces=ns).rsplit("/", 1)[-1].split("v")[0]
                info[aid] = {"authors": [x.findtext("a:name", default="", namespaces=ns)
                                         for x in e.findall("a:author", ns)],
                             "year": e.findtext("a:published", default="", namespaces=ns)[:4],
                             "venue": "arXiv", "link": f"https://arxiv.org/abs/{aid}"}
        except (requests.RequestException, ET.ParseError):
            pass
    refs = []
    for p in papers:
        d = info.get(p["id"], {})
        refs.append({"id": p["id"], "title": p["title"], "year": d.get("year") or p.get("date", "")[:4],
                     "authors": d.get("authors", []), "venue": d.get("venue"),
                     "link": d.get("link") or (f"https://openalex.org/{p['id']}" if p["id"].startswith("W")
                                               else f"https://arxiv.org/abs/{p['id']}"),
                     "excerpt": p["abstract"][:EXCERPT_CHARS]})
    return refs


def format_reference(n, r):
    a = r["authors"]
    who = (", ".join(a[:3]) + (" et al." if len(a) > 3 else "")) if a else "(authors not available)"
    venue = f" {r['venue']}." if r.get("venue") else ""
    return f"[{n}] {who} ({r['year']}). {r['title']}.{venue} {r['link']}"


def references_prompt(refs):
    return "\n\nREFERENCES (cite only these, as [n]):\n" + "\n".join(
        f"[{n}] {r['title']} ({r['year']}). Abstract excerpt: {r['excerpt']}..." for n, r in enumerate(refs, 1))


def check_citations(body, k):
    """Citation numbers used in the text, and those outside 1..k."""
    used = set()
    for grp in re.findall(r"\[(\d+(?:\s*[,\u2013-]\s*\d+)*)\]", body):
        for part in re.split(r"\s*,\s*", grp):
            nums = [int(x) for x in re.split(r"\s*[\u2013-]\s*", part) if x]
            used.update(range(nums[0], nums[-1] + 1) if len(nums) == 2 else nums)
    return sorted(used), sorted(n for n in used if n < 1 or n > k)


def call_llm(system_prompt, user_prompt, seed):
    payload = {"model": LLM_MODEL_NAME,
               "messages": [{"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}],
               "temperature": LLM_TEMPERATURE, "top_p": LLM_TOP_P,
               "max_tokens": LLM_MAX_TOKENS, "seed": seed}
    try:
        r = requests.post(LLM_ENDPOINT, json=payload, timeout=LLM_TIMEOUT_S)
        r.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Could not reach llama.cpp server at {LLM_ENDPOINT} ({e})")
    except requests.exceptions.Timeout:
        raise RuntimeError(f"No response within {LLM_TIMEOUT_S}s; raise LLM_TIMEOUT_S.")
    data = r.json()
    choice = data["choices"][0]
    return payload, choice["message"]["content"], choice.get("finish_reason"), data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--source", choices=["ga", "random"], default="ga")
    ap.add_argument("--refs", type=int, default=8,
                    help="number of real references from the knowledge space (0 = no citations, as in the paper)")
    args = ap.parse_args()

    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)
    land = cg.Landscape(ks, emb)
    B = cg.run_ga(land, args.seed) if args.source == "ga" else cg.run_random(land, args.seed, budget=1)
    t = B.best
    facts = {
        "method": land.M[t[0]], "problem": land.P[t[1]], "goal": land.G[t[2]],
        "hypothesis_name": land.name(t),
        "novelty_score": round(float(land.N[t]), 3), "utility_score": round(float(land.U[t]), 3),
        "overall_score": round(float(land.F[t]), 3),
        "alpha_novelty_weight": cg.ALPHA_NOVELTY, "beta_utility_weight": cg.BETA_UTILITY,
        "hypothesis_source": args.source,
        "ga_generations": cg.GENERATION_COUNT if args.source == "ga" else None,
        "ga_population_size": cg.POPULATION_SIZE if args.source == "ga" else None,
        "knowledge_space_size": len(ks.search),
        "embedding_model": cg.EMBED_MODEL,
        "generating_script": os.path.basename(__file__),
    }
    refs = []
    if args.refs > 0:
        refs = fetch_bibliography(select_references(land, ks, emb, t, args.refs))
        system_prompt = read_prompt("writer_with_references_system_prompt.txt")
        user_prompt = build_user_prompt(facts) + references_prompt(refs)
    else:
        system_prompt = read_prompt("condition_A_system_prompt.txt")
        user_prompt = build_user_prompt(facts)
    print(f"[{args.source}, seed={args.seed}] {facts['hypothesis_name']}  "
          f"(N={facts['novelty_score']}, U={facts['utility_score']}, f={facts['overall_score']})")

    run_id = f"{args.source}_seed{args.seed:02d}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        payload, body, finish, raw = call_llm(system_prompt, user_prompt, args.seed)
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    cited, invalid = [], []
    if refs:
        # drop any reference section the writer wrote despite the instruction; the real list is appended below
        body = re.split(r"\n\s*(?:#+\s*)?(?:\*\*)?(?:\d+\.?\s*)?(?:References|Bibliography|Works Cited)\b[^\n]*",
                        body, maxsplit=1, flags=re.I)[0]
        cited, invalid = check_citations(body, len(refs))
        if invalid:
            print(f"[WARNING] citation numbers outside the reference list: {invalid}", file=sys.stderr)
    if finish == "length":
        body += ("\n\n> INCOMPLETE - generation stopped at LLM_MAX_TOKENS "
                 f"({LLM_MAX_TOKENS}). Re-run with a larger limit.\n")
    if refs:
        body = body.rstrip() + "\n\n## References\n\n" + "\n".join(
            format_reference(n, r) for n, r in enumerate(refs, 1))
        body += ("\n\n*References were retrieved automatically from the knowledge space (the papers closest to the "
                 "hypothesis) and are the only sources the writer was allowed to cite. Check that each citation "
                 "supports the statement it is attached to.*")
        if invalid:
            body += f"\n\n> WARNING: the text cites numbers that are not in the list: {invalid}. Remove them.\n"
    footer = (f"\n\n---\n*Generated by the proposed model ({os.path.basename(__file__)}; "
              f"hypothesis source = {args.source}, seed = {args.seed}) + local LLM writer "
              f"({LLM_MODEL_NAME} via llama.cpp, no web access). GA values: N={facts['novelty_score']}, "
              f"U={facts['utility_score']}, f={facts['overall_score']}. Date: {datetime.date.today()}*\n")
    with open(os.path.join(OUT_DIR, f"{run_id}.md"), "w", encoding="utf-8") as f:
        f.write(body.rstrip() + footer)
    with open(os.path.join(LOG_DIR, f"{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "facts": facts, "references": refs, "cited_numbers": cited,
                   "invalid_citation_numbers": invalid, "request_payload": payload,
                   "finish_reason": finish, "raw_response": raw}, f, ensure_ascii=False, indent=1)
    print(f"written: results/manuscripts/{run_id}.md  (log: results/writer_logs/{run_id}.json)")


if __name__ == "__main__":
    main()
