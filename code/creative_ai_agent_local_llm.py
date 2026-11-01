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
#   * v1.0.4: the Related Work, the Mathematical Formulation and the Experimental Design are rewritten in
#     separate LLM calls (prompts/related_work_system_prompt.txt, formulation_system_prompt.txt,
#     experimental_design_system_prompt.txt), which replace the usually thin versions of the first call. The
#     Related Work receives the Proposed Method and the references with longer abstracts and reviews every
#     reference by theme, ending with the research gap. The formulation receives the Proposed Method and gives a
#     notation table, one model per component, a Method -> Problem -> Goal model, a decision problem, an
#     algorithm and formal hypotheses; the experimental design receives the Proposed Method and the new
#     formulation and gives a plan to test those hypotheses (design, data, variables, analysis, validity).
#     --no-detail skips them (v1.0.3 behaviour); --detail FILE.md rewrites them in an existing manuscript.
#     The Reproducibility section is written by this script from the recorded settings, not by the LLM.
#
# Usage (llama-server must be running):
#   python creative_ai_agent_local_llm.py --seed 1 --source ga            # with 8 real references
#   python creative_ai_agent_local_llm.py --seed 1 --source ga --refs 0   # as in the paper (no citations)
#   python creative_ai_agent_local_llm.py --seed 1 --source random
#   python creative_ai_agent_local_llm.py --detail ../results/manuscripts/ga_seed03_20261030_173251.md

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
DETAIL_MAX_TOKENS = int(os.environ.get("LLM_DETAIL_MAX_TOKENS", "4000"))
MAX_RETRIES = 2          # extra attempts for a formulation with too few numbered equations

# appended to every manuscript
CITATION_NOTICE = (
    "\n> このAIエージェントで生成した仮説や研究計画の下書きをもとに、論文・学会発表などで研究成果を公表する場合は、"
    "**下記の論文を引用してください。**\n>\n"
    "> Otsuki A. Comparing Genetic Algorithms and LLMs for Research-Hypothesis Generation: Mainstream Convergence of "
    "LLMs, Wider Hypothesis Exploration by Combinatorial Search, and the Limits of Literature-Distance Novelty "
    "Metrics. Informatics. 2026; 13(10):174. https://doi.org/10.3390/informatics13100174\n")


def read_prompt(name):
    with open(os.path.join(PROMPT_DIR, name), encoding="utf-8") as f:
        return f.read().strip()


def build_user_prompt(facts):
    return ("GROUND TRUTH FACTS (JSON):\n" + json.dumps(facts, ensure_ascii=False, indent=2) +
            "\n\nUsing only these facts as your grounding, write the manuscript now.")


# ------------------------------------------------------------------ real references (v1.0.3)
EXCERPT_CHARS = 350
ABSTRACT_CHARS = 1500   # longer abstracts for the Related Work call


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
                     "excerpt": p["abstract"][:EXCERPT_CHARS], "abstract": p["abstract"][:ABSTRACT_CHARS]})
    return refs


def format_reference(n, r):
    a = r["authors"]
    who = (", ".join(a[:3]) + (" et al." if len(a) > 3 else "")) if a else "(authors not available)"
    venue = f" {r['venue']}." if r.get("venue") else ""
    return f"[{n}] {who} ({r['year']}). {r['title']}.{venue} {r['link']}"


def references_prompt(refs, full=False):
    """Numbered reference list for a prompt; full=True gives the longer abstracts (when they were recorded)."""
    def text(r):
        if full and r.get("abstract"):
            return f"Abstract: {r['abstract']}"
        return f"Abstract excerpt: {r['excerpt']}..."
    return "\n\nREFERENCES (cite only these, as [n]):\n" + "\n".join(
        f"[{n}] {r['title']} ({r['year']}). {text(r)}" for n, r in enumerate(refs, 1))


def check_citations(body, k):
    """Citation numbers used in the text, and those outside 1..k."""
    used = set()
    body = re.sub(r"\$\$.*?\$\$|\$[^$\n]+\$", " ", body, flags=re.S)   # intervals such as $[0, 1]$ are not citations
    for grp in re.findall(r"\[(\d+(?:\s*[,\u2013-]\s*\d+)*)\]", body):
        for part in re.split(r"\s*,\s*", grp):
            nums = [int(x) for x in re.split(r"\s*[\u2013-]\s*", part) if x]
            used.update(range(nums[0], nums[-1] + 1) if len(nums) == 2 else nums)
    return sorted(used), sorted(n for n in used if n < 1 or n > k)


def call_llm(system_prompt, user_prompt, seed, max_tokens=LLM_MAX_TOKENS):
    payload = {"model": LLM_MODEL_NAME,
               "messages": [{"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}],
               "temperature": LLM_TEMPERATURE, "top_p": LLM_TOP_P,
               "max_tokens": max_tokens, "seed": seed}
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


def strip_reference_section(text):
    """Drop any reference section the writer wrote despite the instruction (the real list is appended)."""
    return re.split(r"\n\s*(?:#+\s*)?(?:\*\*)?(?:\d+\.?\s*)?(?:References|Bibliography|Works Cited)\b[^\n]*",
                    text, maxsplit=1, flags=re.I)[0]


# ------------------------------------------------------------------ detailed sections (v1.0.4)
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.M)
PROPOSED_RE = r"proposed (method|approach|framework)|methodology"
# sections rewritten in separate LLM calls, in this order; each one receives the sections listed in "inputs"
DETAIL_SECTIONS = [
    {"title": "Related Work", "prompt": "related_work_system_prompt.txt",
     "pattern": r"related work|literature review|background",
     "inputs": ["Proposed Method"], "after": r"introduction", "needs_refs": True, "full_abstracts": True},
    {"title": "Mathematical Formulation", "prompt": "formulation_system_prompt.txt",
     "pattern": r"mathematical (formulation|model)|formal (model|formulation)|problem formulation",
     "inputs": ["Proposed Method"], "after": PROPOSED_RE, "min_equations": 6},
    {"title": "Experimental Design", "prompt": "experimental_design_system_prompt.txt",
     "pattern": r"experiment(al)? (design|plan|setup)|evaluation (design|plan)",
     "inputs": ["Proposed Method", "Mathematical Formulation"], "after": r"mathematical formulation"},
]
INPUT_PATTERNS = {"Proposed Method": PROPOSED_RE, "Mathematical Formulation": DETAIL_SECTIONS[1]["pattern"]}


def find_section(body, pattern):
    """(start, end, level) of the first Markdown heading matching pattern, up to the next heading of the
    same or a higher level; None if there is no such heading."""
    heads = list(HEADING_RE.finditer(body))
    for i, h in enumerate(heads):
        if re.search(pattern, h.group(2), re.I):
            level = len(h.group(1))
            end = next((g.start() for g in heads[i + 1:] if len(g.group(1)) <= level), len(body))
            return h.start(), end, level
    return None


def section_text(body, name):
    """Text of an input section; a detailed section nested inside it is left out."""
    sec = find_section(body, INPUT_PATTERNS[name])
    if sec is None:
        return ""
    text = body[sec[0]:sec[1]]
    for spec in DETAIL_SECTIONS:
        if spec["title"] != name:
            inner = find_section(text, spec["pattern"])
            if inner and inner[0] > 0:
                text = text[:inner[0]] + text[inner[1]:]
    return text.strip()


def write_detail_section(body, spec, facts, refs, seed):
    """Replaces one section of body (spec in DETAIL_SECTIONS) with a detailed one written in a separate LLM
    call. Returns (new body, log entry); body is unchanged on failure."""
    title = spec["title"]
    if spec.get("needs_refs") and not refs:
        print(f"{title}: kept as written (no references to review; use --refs K > 0).")
        return body, None
    inputs = {name: section_text(body, name) for name in spec["inputs"]}
    if not inputs["Proposed Method"]:
        print(f"[WARNING] no 'Proposed Method' heading found; {title} was not rewritten.", file=sys.stderr)
        return body, None
    old = find_section(body, spec["pattern"])
    anchor = find_section(body, spec["after"]) or find_section(body, PROPOSED_RE)
    level = old[2] if old else anchor[2]
    sub = "#" * min(level + 1, 6)
    hyp = {k: facts[k] for k in ("method", "problem", "goal", "hypothesis_name") if facts.get(k)}
    user_prompt = ("HYPOTHESIS (JSON):\n" + json.dumps(hyp, ensure_ascii=False, indent=2) +
                   "".join(f"\n\n{name.upper()} SECTION OF THE MANUSCRIPT:\n{text}"
                           for name, text in inputs.items() if text) +
                   (references_prompt(refs, spec.get("full_abstracts")) if refs else "") +
                   f"\n\nWrite the {title} section now. Use '{sub}' for its subheadings.")
    print(f"writing the detailed {title} (separate LLM call) ...")
    # a small model sometimes returns a formulation without real equations: retry with another sampling seed
    # (at most MAX_RETRIES times) and keep the attempt with the most numbered equations
    best, attempts = None, []
    for attempt in range(1 + (MAX_RETRIES if spec.get("min_equations") else 0)):
        try:
            payload, text, finish, raw = call_llm(read_prompt(spec["prompt"]), user_prompt,
                                                  seed + 1000 * attempt, DETAIL_MAX_TOKENS)
        except RuntimeError as e:
            print(f"[WARNING] {title} not rewritten: {e}", file=sys.stderr)
            break
        n_eq = len(re.findall(r"\\tag\{", text))
        attempts.append({"seed": seed + 1000 * attempt, "numbered_equations": n_eq})
        if best is None or n_eq > best[4]:
            best = (payload, text, finish, raw, n_eq)
        if n_eq >= spec.get("min_equations", 0):
            break
        print(f"  only {n_eq} numbered equations; retrying with another seed ...")
    if best is None:
        return body, None
    payload, text, finish, raw, _ = best
    text = strip_reference_section(text).strip()
    # drop a repeated section title at the top
    text = re.sub(r"^(?:#+\s*|\*\*)?(?:\d+\.?\s*)?" + re.escape(title) + r"\b[^\n]*\n+", "", text, flags=re.I)
    if finish == "length":
        text += (f"\n\n> INCOMPLETE - this section stopped at LLM_DETAIL_MAX_TOKENS ({DETAIL_MAX_TOKENS}). "
                 "Re-run with a larger limit.")
    section = "#" * level + f" {title}\n\n" + text + "\n\n"
    if old:
        body = body[:old[0]] + section + body[old[1]:]
    else:
        body = body[:anchor[1]].rstrip() + "\n\n" + section + body[anchor[1]:]
    n_eq = len(re.findall(r"\\tag\{", text))
    print(f"  {title}: {len(text.split())} words, {n_eq} numbered equations, finish_reason={finish}")
    return body, {"section": title, "request_payload": payload, "finish_reason": finish, "raw_response": raw,
                  "numbered_equations": n_eq, "attempts": attempts}


def write_detail_sections(body, facts, refs, seed):
    log = []
    for spec in DETAIL_SECTIONS:
        body, entry = write_detail_section(body, spec, facts, refs, seed)
        if entry:
            log.append(entry)
    return body, log


def and_join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def reproducibility_text(facts, refs, writer, detailed, run_id):
    """Reproducibility section built from the recorded facts only (not written by the LLM, which tended to
    leave placeholders or misstate the search settings)."""
    f = facts
    lines = ["This manuscript is a draft generated automatically by the pipeline described below. Nothing in it "
             "has been validated empirically; the Experimental Design is a plan, not a report of results.", ""]
    if f.get("hypothesis_source") == "ga":
        search = (f"a genetic-algorithm search (`creative_ga.py`; population size {f.get('ga_population_size')}, "
                  f"{f.get('ga_generations')} generations")
        if f.get("ga_population_size") and f.get("ga_generations"):
            search += f", i.e. {f['ga_population_size'] * f['ga_generations']} fitness evaluations"
        search += f", random seed {writer.get('seed')})"
    else:
        search = f"uniformly random selection (random seed {writer.get('seed')}), used as a control condition"
    vocab = f" from a vocabulary of {f['vocabulary_size']} Method × Problem × Goal combinations" \
        if f.get("vocabulary_size") else ""
    lines.append(f"- **Hypothesis selection.** The hypothesis *{f.get('hypothesis_name', '')}* was selected{vocab} "
                 f"by {search}.")
    if f.get("knowledge_space_size"):
        lines.append(f"- **Knowledge space.** Novelty and utility were computed against a knowledge space of "
                     f"{f['knowledge_space_size']} papers (titles and abstracts), embedded with "
                     f"`{f.get('embedding_model')}`.")
    if f.get("novelty_score") is not None:
        lines.append(f"- **Scores.** Novelty N = {f['novelty_score']}, utility U = {f['utility_score']}, overall "
                     f"score f = {f.get('alpha_novelty_weight')}·N + {f.get('beta_utility_weight')}·U = "
                     f"{f['overall_score']}. These values were computed by the search program, not by the "
                     "language model.")
    params = ", ".join(f"{k} = {writer[k]}" for k in ("temperature", "top_p", "max_tokens", "seed")
                       if writer.get(k) is not None)
    lines.append(f"- **Writing.** The text was written by a local language model ({writer.get('model')}, served by "
                 f"llama.cpp; {params}) without web access. The model was not trained or fine-tuned on the "
                 "knowledge space; it received only the facts above"
                 + (" and the reference list." if refs else "."))
    if detailed:
        prompts = [f"`{s['prompt']}`" for s in DETAIL_SECTIONS if s["title"] in detailed]
        lines.append(f"- **Detailed sections.** {and_join(detailed)} {'was' if len(detailed) == 1 else 'were'} "
                     f"rewritten in separate calls of the same model (prompts {and_join(prompts)}).")
    if refs:
        lines.append(f"- **References.** The {len(refs)} references were retrieved automatically from the knowledge "
                     "space (the papers closest to the hypothesis); bibliographic data were taken from OpenAlex or "
                     "arXiv and appended by the script, not written by the language model.")
    lines.append(f"- **Logs and code.** The prompts, decoding parameters, references and raw model responses are "
                 f"logged in `results/writer_logs/{run_id}.json`. Script: `{f.get('generating_script', 'creative_ai_agent_local_llm.py')}` "
                 "(https://github.com/otsukiLabo-NUCOE/creative-ai-hypothesis-generation).")
    return "\n".join(lines)


def replace_reproducibility(body, text):
    """Puts text in place of the writer's Reproducibility section (or after the Experimental Design)."""
    old = find_section(body, r"reproducib")
    if old:
        return body[:old[0]] + "#" * old[2] + " Reproducibility\n\n" + text + "\n\n" + body[old[1]:]
    anchor = find_section(body, DETAIL_SECTIONS[1]["pattern"]) or find_section(body, PROPOSED_RE)
    if anchor is None:
        return body.rstrip() + "\n\n## Reproducibility\n\n" + text + "\n"
    return body[:anchor[1]].rstrip() + "\n\n" + "#" * anchor[2] + " Reproducibility\n\n" + text + "\n\n" + body[anchor[1]:]


def detail_existing(path, seed):
    """Rewrites only the detailed sections of an existing manuscript; saves <name>_detailed.md."""
    body = open(path, encoding="utf-8").read()
    stem = os.path.splitext(os.path.basename(path))[0]
    log_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "..", "writer_logs")
    log_path = os.path.join(log_dir, stem + ".json")
    facts, refs, writer = {}, [], None
    if os.path.exists(log_path):                           # hypothesis and references of the original run
        log = json.load(open(log_path, encoding="utf-8"))
        facts, refs = log.get("facts", {}), log.get("references", [])
        writer = log.get("request_payload")
    else:
        title = re.search(r"^#\s+(.+)$", body, re.M)
        facts = {"hypothesis_name": title.group(1) if title else stem}
    # keep the appended reference list and footer as they are
    cut = re.search(r"\n## References\n|\n---\n\*Generated by", body)
    head, tail = (body[:cut.start()], body[cut.start():]) if cut else (body, "")
    head, entries = write_detail_sections(head, facts, refs, seed)
    if not entries:
        sys.exit(1)
    if writer:                                             # the settings of the original run are known
        head = replace_reproducibility(head, reproducibility_text(
            facts, refs, writer, [e["section"] for e in entries], stem))
    if refs:
        cited, invalid = check_citations(head, len(refs))
        if invalid:
            print(f"[WARNING] citation numbers outside the reference list: {invalid}", file=sys.stderr)
    out = os.path.join(os.path.dirname(os.path.abspath(path)), stem + "_detailed.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(head.rstrip() + "\n" + tail.rstrip() + "\n" + ("" if CITATION_NOTICE.strip() in tail else CITATION_NOTICE))
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, stem + "_detailed.json"), "w", encoding="utf-8") as f:
        json.dump({"source_manuscript": path, "detailed_sections": entries}, f, ensure_ascii=False, indent=1)
    print(f"written: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--source", choices=["ga", "random"], default="ga")
    ap.add_argument("--refs", type=int, default=8,
                    help="number of real references from the knowledge space (0 = no citations, as in the paper)")
    ap.add_argument("--no-detail", action="store_true",
                    help="keep the related work, formulation and experimental design of the first LLM call (v1.0.3 behaviour)")
    ap.add_argument("--detail", metavar="FILE.md",
                    help="only rewrite the Related Work, Mathematical Formulation and Experimental Design of an existing manuscript")
    args = ap.parse_args()
    if args.detail:
        detail_existing(args.detail, args.seed)
        return

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
        body = strip_reference_section(body)
    detailed = []
    if not args.no_detail and finish != "length":
        body, detailed = write_detail_sections(body, facts, refs, args.seed)
    n_m, n_p, n_g = len(land.M), len(land.P), len(land.G)
    body = replace_reproducibility(body, reproducibility_text(
        {**facts, "vocabulary_size": f"{n_m} × {n_p} × {n_g} = {n_m * n_p * n_g}"}, refs, payload,
        [e["section"] for e in detailed], run_id))
    if refs:
        cited, invalid = check_citations(body, len(refs))
        if invalid:
            print(f"[WARNING] citation numbers outside the reference list: {invalid}", file=sys.stderr)
    if finish == "length":
        body += ("\n\n> INCOMPLETE - generation stopped at LLM_MAX_TOKENS "
                 f"({LLM_MAX_TOKENS}). Re-run with a larger limit.\n")
    if refs:
        # one paragraph per reference (single newlines are joined into one line by Markdown viewers)
        body = body.rstrip() + "\n\n## References\n\n" + "\n\n".join(
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
        f.write(body.rstrip() + footer + CITATION_NOTICE)
    with open(os.path.join(LOG_DIR, f"{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "facts": facts, "references": refs, "cited_numbers": cited,
                   "invalid_citation_numbers": invalid, "request_payload": payload,
                   "finish_reason": finish, "raw_response": raw, "detailed_sections": detailed},
                  f, ensure_ascii=False, indent=1)
    print(f"written: results/manuscripts/{run_id}.md  (log: results/writer_logs/{run_id}.json)")


if __name__ == "__main__":
    main()
