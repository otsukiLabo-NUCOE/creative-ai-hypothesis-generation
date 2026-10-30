# make_concepts.py — builds the Method / Problem / Goal vocabulary (concepts.py) for a research field
# automatically from OpenAlex.
#   1. Frequent keywords of the field's papers are fetched from OpenAlex (one request).
#   2. Each keyword is assigned to Method, Problem, Goal, or "other" (context words and noise) by its
#      embedding similarity to a few example words per role (same encoder as the model).
#   3. The most frequent keywords of each role are written to concepts.py (the old file is backed up).
#
#   python make_concepts.py --subfield 1404                       # OpenAlex subfield id (1404 = MIS)
#   python make_concepts.py --search "management information systems"
#   python make_concepts.py --subfield 1404 --dry-run              # show the lists without writing
import argparse
import os
import re
import shutil

import numpy as np
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.openalex.org/works"
API_KEY = os.environ.get("OPENALEX_API_KEY")

# a few example words per role; keywords are assigned to the most similar role
EXAMPLES = {
    "Method": ["machine learning", "regression analysis", "simulation", "process mining", "blockchain",
               "decision support system", "survey method", "optimization algorithm", "data analytics",
               "large language model", "text mining", "structural equation modeling"],
    "Problem": ["risk", "fraud", "information overload", "supply chain disruption", "data privacy",
                "cybersecurity threat", "uncertainty", "resistance to change", "customer churn",
                "information asymmetry", "bias", "data quality problems"],
    "Goal": ["firm performance", "customer satisfaction", "competitive advantage", "operational efficiency",
             "cost reduction", "innovation", "trust", "productivity", "sustainability", "decision quality",
             "user satisfaction", "business value"],
    "other": ["small and medium-sized enterprises", "COVID-19 pandemic", "manufacturing companies",
              "banking sector", "higher education", "mediating effect", "case study", "literature review",
              "exam preparation", "developing countries", "theory", "Indonesia"],
}


# words that decide the role directly (checked before the embedding similarity)
CUES = {
    "Problem": ["risk", "uncertainty", "asymmetry", "fraud", "failure", "disruption", "barrier", "overload",
                "churn", "bias", "threat", "attack", "privacy", "breach", "shortage", "waste", "loss", "delay",
                "conflict", "misinformation", "fake", "resistance", "volatility", "vulnerability", "debt",
                "inequality", "poverty", "stress", "burnout", "turnover", "noise", "scarcity", "problem",
                "security", "cyberattack", "overconfidence", "information overload", "obsolescence"],
    "Goal": ["performance", "efficiency", "advantage", "satisfaction", "value", "productivity", "innovation",
             "trust", "loyalty", "sustainability", "agility", "effectiveness", "resilience", "competitiveness",
             "profitability", "growth", "engagement", "reduction", "improvement", "quality of", "well-being",
             "inclusion", "transparency", "accuracy", "acceptance"],
    "Method": ["system", "systems", "analytics", "learning", "mining", "model", "modeling", "modelling",
               "intelligence", "analysis", "algorithm", "blockchain", "simulation", "forecasting", "optimization",
               "planning", "scorecard", "network", "method", "technique", "framework", "game", "regression",
               "survey", "experiment", "platform", "technology", "automation", "visualization", "twin",
               "data", "weighting", "programming", "computing"],
}


def cue_role(keyword):
    words = keyword.lower().replace("-", " ").split()
    last = words[-1] if words else ""
    for role in ("Problem", "Goal", "Method"):          # the head word (last word) decides first
        if any(last == c or last.rstrip("s") == c for c in CUES[role]):
            return role
    text = " " + " ".join(words) + " "
    for role in ("Problem", "Goal", "Method"):
        if any(f" {c} " in text for c in CUES[role]):
            return role
    return None


def fetch_keywords(args):
    flt = f"from_publication_date:{args.date_from},to_publication_date:{args.date_to},language:en"
    if args.subfield:
        flt += f",primary_topic.subfield.id:{args.subfield}"
    params = {"filter": flt, "group_by": "keywords.id", "per-page": 200}
    if args.search:
        params["search"] = args.search
    if API_KEY:
        params["api_key"] = API_KEY
    r = requests.get(API, params=params, timeout=60)
    if r.status_code == 429:
        raise SystemExit("OpenAlex: the daily request budget is used up. Set a free API key "
                         "(https://openalex.org/settings/api) in the environment variable OPENALEX_API_KEY, "
                         "or try again after midnight UTC.")
    r.raise_for_status()
    groups = r.json().get("group_by", [])
    return [(g["key_display_name"], g["count"]) for g in groups if g.get("key_display_name")]


def title_case(s):
    keep = {"and", "of", "for", "in", "to", "on", "the", "a", "with"}
    words = s.split()
    return " ".join(w if (w.isupper() or (i and w in keep)) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subfield", help="OpenAlex subfield id, e.g. 1404 (Management Information Systems)")
    ap.add_argument("--search", help="free-text search instead of / in addition to the subfield")
    ap.add_argument("--from", dest="date_from", default="2021-01-01")
    ap.add_argument("--to", dest="date_to", default="2025-12-31")
    ap.add_argument("--n-method", type=int, default=12)
    ap.add_argument("--n-problem", type=int, default=10)
    ap.add_argument("--n-goal", type=int, default=8)
    ap.add_argument("--margin", type=float, default=0.08,
                    help="minimum lead of the best role (embedding) for keywords without a cue word")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.subfield or args.search):
        ap.error("give --subfield or --search")

    kws = fetch_keywords(args)
    print(f"{len(kws)} keywords fetched from OpenAlex")
    from sentence_transformers import SentenceTransformer
    enc = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    roles = list(EXAMPLES)
    proto = {r: enc.encode(EXAMPLES[r], normalize_embeddings=True) for r in roles}
    Z = enc.encode([k for k, _ in kws], normalize_embeddings=True)
    # role score = mean of the 3 highest similarities to that role's examples
    score = np.stack([np.sort(Z @ proto[r].T, axis=1)[:, -3:].mean(axis=1) for r in roles], axis=1)
    emb_role = [roles[i] for i in score.argmax(axis=1)]
    srt = np.sort(score, axis=1)
    margin = srt[:, -1] - srt[:, -2]
    # a cue word decides the role, unless the embedding says the keyword is a context word or noise;
    # without a cue word, the embedding decides only when it is clearly ahead (otherwise: dropped)
    assign = []
    for (k, _), er, mg in zip(kws, emb_role, margin):
        cr = cue_role(k)
        if er == "other":
            assign.append("other")
        elif cr:
            assign.append(cr)
        else:
            assign.append(er if mg >= args.margin else "other")

    picked = {"Method": [], "Problem": [], "Goal": []}
    limit = {"Method": args.n_method, "Problem": args.n_problem, "Goal": args.n_goal}
    for (k, n), role in zip(kws, assign):          # kws are sorted by frequency
        if role in picked and len(picked[role]) < limit[role] and not re.search(r"\d", k):
            picked[role].append(title_case(k))
    for r, words in picked.items():
        print(f"\n{r} ({len(words)}):")
        for w in words:
            print("  -", w)
    other = [k for (k, _), r in zip(kws, assign) if r == "other"][:15]
    print("\nexcluded as context/noise (first 15):", other)
    if args.dry_run:
        return

    path = os.path.join(HERE, "concepts.py")
    shutil.copy2(path, path + ".bak")
    src = open(path, encoding="utf-8").read()
    s, e = src.index("CONCEPTS = {"), src.index("def hypothesis_text")
    body = "CONCEPTS = {\n" + "".join(
        f'    "{r}": [\n' + "".join(f'        "{w}",\n' for w in words) + "    ],\n" for r, words in picked.items()) + "}\n\n\n"
    open(path, "w", encoding="utf-8").write(src[:s] + body + src[e:])
    n = len(picked["Method"]) * len(picked["Problem"]) * len(picked["Goal"])
    print(f"\nconcepts.py updated ({n} hypotheses); the previous version is saved as concepts.py.bak")


if __name__ == "__main__":
    main()
