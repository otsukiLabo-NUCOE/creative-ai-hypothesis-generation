# prepare_hypothesis_eval.py
#
# Experiment 5 (blinded human evaluation of hypotheses; replaces the manuscript-level human rating).
# 30 triplets, each with one hypothesis from each source, shown in a uniform format with the source
# hidden; 2 raters rank the three hypotheses of every triplet by USEFULNESS (best / worst).
#
#   python prepare_hypothesis_eval.py select    -> hypotheses.csv (30 GA distinct, 30 uniform, 30 LLM)
#   python prepare_hypothesis_eval.py render    -> renders every hypothesis with the writer LLM into the
#                                                   same format (needs llama-server with Nemotron on :8080)
#   python prepare_hypothesis_eval.py package   -> triplets, rater booklets + answer-sheet order files
#
# Uniform presentation: every hypothesis (whatever its source) is rewritten by the SAME writer model with
# the SAME prompt and decoding settings into (i) a one-sentence hypothesis and (ii) a 2-3 sentence
# description, with hard length limits, so that format and length do not reveal the source.

import csv
import glob
import json
import os
import random
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "hypothesis_eval")
PKG = os.path.join(HERE, "..", "rater_package_hypotheses")
ENDPOINT = os.environ.get("LLAMA_SERVER_ENDPOINT", "http://127.0.0.1:8080/v1/chat/completions")
SEED = 4591240
N = 30

RENDER_PROMPT = """You will be given a research hypothesis in artificial intelligence, consisting of a Method, a Problem, and a Goal.
Rewrite it for a reader who is a researcher but not necessarily an AI specialist, in exactly this format:

Hypothesis: <ONE sentence of 20 to 30 words stating concretely what is done with the method, for which problem, to achieve which goal>
Description: <two or three sentences, 50 to 70 words in total, explaining the mechanism and why it could work>

Rules: the hypothesis sentence must have between 20 and 30 words: if the input is short, make it concrete by stating how the method would be applied; if the input is long, condense it to its core idea; begin the hypothesis sentence directly with the method (never with "This study", "This approach", "We", or similar); use plain, neutral language and at most one technical term per noun phrase; do not exaggerate; do not invent results, numbers, datasets, or citations; do not mention how the hypothesis was obtained; output only the two lines.

Method: {M}
Problem: {P}
Goal: {G}"""


def select():
    import creative_ga as cg
    import pandas as pd
    os.makedirs(OUT, exist_ok=True)
    emb = cg.Embedder(); ks = cg.KnowledgeSpace.build(emb); land = cg.Landscape(ks, emb)
    rows, seen, s = [], set(), 0
    while len([r for r in rows if r["source"] == "ga"]) < N:          # GA: first N distinct results
        s += 1
        t = cg.run_ga(land, s).best
        h = (land.M[t[0]], land.P[t[1]], land.G[t[2]])
        if h not in seen:
            seen.add(h)
            rows.append({"source": "ga", "seed": s, "method": h[0], "problem": h[1], "goal": h[2]})
    runs = pd.read_csv(os.path.join(HERE, "..", "results", "runs.csv"))
    uni = runs[runs.method == "Uniform(no search)"]
    for _, r in uni.iterrows():                                        # uniform draw, same concept set
        rows.append({"source": "random", "seed": int(r.seed), "method": r.M, "problem": r.P, "goal": r.G})
    for p in sorted(glob.glob(os.path.join(HERE, "..", "results", "controlled", "hypotheses", "llm_seed*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        rows.append({"source": "llm", "seed": d["seed"], **d["hypothesis"]})
    for i, r in enumerate(rows, 1):
        r["hid"] = f"H{i:03d}"
    with open(os.path.join(OUT, "hypotheses.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["hid", "source", "seed", "method", "problem", "goal"])
        w.writeheader(); w.writerows(rows)
    print({k: sum(r["source"] == k for r in rows) for k in ("ga", "random", "llm")}, "GA seeds used:", s)


SHORTEN_PROMPT = """Shorten the following sentence to AT MOST 28 words while keeping its meaning. Begin directly with the method; do not start with "This study", "This approach", or "We". Use plain language. Output only the shortened sentence.

Sentence: {S}"""


def llm(prompt, seed, max_tokens):
    payload = {"messages": [{"role": "user", "content": prompt}], "seed": seed, "temperature": 0.7, "top_p": 0.95,
               "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    return payload, requests.post(ENDPOINT, json=payload, timeout=1800).json()["choices"][0]["message"]["content"]


def render():
    """Same procedure for every hypothesis regardless of source: render; if the hypothesis sentence is
    longer than 30 words, apply the same shortening prompt (up to 3 times)."""
    rows = list(csv.DictReader(open(os.path.join(OUT, "hypotheses.csv"), encoding="utf-8")))
    os.makedirs(os.path.join(OUT, "rendered"), exist_ok=True)
    for r in rows:
        path = os.path.join(OUT, "rendered", r["hid"] + ".json")
        if os.path.exists(path):
            continue
        prompt = RENDER_PROMPT.replace("{M}", r["method"]).replace("{P}", r["problem"]).replace("{G}", r["goal"])
        t0 = time.time()
        hyp = desc = None
        for attempt in range(6):
            payload, text = llm(prompt, 11 + 1000 * attempt, 250)
            mh = re.search(r"Hypothesis:\s*(.+)", text)
            md = re.search(r"Description:\s*(.+)", text, re.S)
            if mh and md:
                hyp, desc = mh.group(1).strip(), " ".join(md.group(1).split())
                if 45 <= len(desc.split()) <= 80:
                    break
        shortened = []
        for k in range(3):
            if len(hyp.split()) <= 30:
                break
            _, s = llm(SHORTEN_PROMPT.replace("{S}", hyp), 21 + k, 80)
            s = " ".join(s.strip().strip('"').split())
            shortened.append(s)
            if len(s.split()) < len(hyp.split()):
                hyp = s
        json.dump({"hid": r["hid"], "hypothesis": hyp, "description": desc, "attempt": attempt, "raw": text,
                   "shortening_steps": shortened, "payload": payload, "seconds": round(time.time() - t0, 1)},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{r['hid']} ({r['source']}): {len(hyp.split())}+{len(desc.split())} words, attempt {attempt}, "
              f"shortened x{len(shortened)}", flush=True)


def normalize_case(text):
    """Same rule for every item: write the concept-vocabulary terms (Title Case in the GA/random inputs) in
    ordinary lowercase, keeping the first letter of a sentence capitalised and the proper adjective 'Bayesian',
    so that capitalisation does not reveal the source."""
    from concepts import CONCEPTS
    terms = sorted({t for v in CONCEPTS.values() for t in v}, key=len, reverse=True)
    for term in terms:
        low = term.lower().replace("bayesian", "Bayesian")
        text = re.sub(re.escape(term), low, text)
    sentences = re.split(r"(?<=[.!?])(\s+)", text.strip())
    return "".join(s[:1].upper() + s[1:] if s.strip() else s for s in sentences)


def package():
    rows = {r["hid"]: r for r in csv.DictReader(open(os.path.join(OUT, "hypotheses.csv"), encoding="utf-8"))
            if not r["hid"].startswith("P")}
    rend = {h: json.load(open(os.path.join(OUT, "rendered", h + ".json"), encoding="utf-8")) for h in rows}
    for d in rend.values():
        d["hypothesis"], d["description"] = normalize_case(d["hypothesis"]), normalize_case(d["description"])
    rng = random.Random(SEED)
    by = {k: [h for h, r in rows.items() if r["source"] == k] for k in ("ga", "random", "llm")}
    for k in by:
        rng.shuffle(by[k])
    triplets = []
    for i in range(N):
        items = [by["ga"][i], by["random"][i], by["llm"][i]]
        rng.shuffle(items)                                   # random A/B/C position
        triplets.append({"tid": f"T{i + 1:02d}", "A": items[0], "B": items[1], "C": items[2]})
    with open(os.path.join(OUT, "_TRIPLET_KEY_do_not_share.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tid", "A", "B", "C", "source_A", "source_B", "source_C"])
        for t in triplets:
            w.writerow([t["tid"], t["A"], t["B"], t["C"]] + [rows[t[x]]["source"] for x in "ABC"])
    json.dump({"triplets": triplets, "text": {h: {"hypothesis": rend[h]["hypothesis"],
                                                 "description": rend[h]["description"]} for h in rows}},
              open(os.path.join(OUT, "triplets.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in (1, 2):                                         # rater-specific triplet order
        order = [t["tid"] for t in triplets]
        random.Random(SEED + r).shuffle(order)
        with open(os.path.join(OUT, f"order_R{r}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["position", "tid"])
            for i, tid in enumerate(order, 1):
                w.writerow([i, tid])
    # the same 30 sets for the LLM judge on the desktop PC (identified only by set ID and letter)
    sets = [{"tid": t["tid"], "items": {x: {"hypothesis": rend[t[x]]["hypothesis"],
                                             "description": rend[t[x]]["description"]} for x in "ABC"}}
            for t in triplets]
    desk = os.path.join(HERE, "..", "desktop_judge_package", "hypothesis_sets.json")
    json.dump(sets, open(desk, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lens = {k: sum(len((rend[h]["hypothesis"] + " " + rend[h]["description"]).split()) for h in by[k]) / N for k in by}
    print("triplets written; mean words per item:", {k: round(v, 1) for k, v in lens.items()})


def practice():
    """One practice triplet (not analysed): the next distinct GA result, one uniform draw, one more LLM
    proposal, appended to hypotheses.csv as P01-P03 and rendered with the same procedure."""
    import creative_ga as cg
    from run_manuscript_experiment import llm_hypothesis
    rows = list(csv.DictReader(open(os.path.join(OUT, "hypotheses.csv"), encoding="utf-8")))
    if any(r["hid"].startswith("P") for r in rows):
        return
    emb = cg.Embedder(); ks = cg.KnowledgeSpace.build(emb); land = cg.Landscape(ks, emb)
    seen = {(r["method"], r["problem"], r["goal"]) for r in rows}
    s = max(int(r["seed"]) for r in rows if r["source"] == "ga")
    while True:
        s += 1
        t = cg.run_ga(land, s).best
        h = (land.M[t[0]], land.P[t[1]], land.G[t[2]])
        if h not in seen:
            break
    rng = random.Random(777)
    u = (rng.choice(land.M), rng.choice(land.P), rng.choice(land.G))
    lh, _ = llm_hypothesis(31)
    extra = [{"hid": "P01", "source": "ga", "seed": s, "method": h[0], "problem": h[1], "goal": h[2]},
             {"hid": "P02", "source": "random", "seed": 777, "method": u[0], "problem": u[1], "goal": u[2]},
             {"hid": "P03", "source": "llm", "seed": 31, **lh}]
    with open(os.path.join(OUT, "hypotheses.csv"), "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=["hid", "source", "seed", "method", "problem", "goal"]).writerows(extra)
    render()


def booklets():
    """Rater booklets (docx): practice triplet + 30 triplets in the rater-specific order."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
    tj = json.load(open(os.path.join(OUT, "triplets.json"), encoding="utf-8"))
    text = tj["text"]
    trip = {t["tid"]: t for t in tj["triplets"]}
    prac = {"tid": "P0", "A": "P02", "B": "P03", "C": "P01"}
    for h in ("P01", "P02", "P03"):
        d = json.load(open(os.path.join(OUT, "rendered", h + ".json"), encoding="utf-8"))
        text[h] = {"hypothesis": normalize_case(d["hypothesis"]), "description": normalize_case(d["description"])}

    def shade(cell, fill):
        tcPr = cell._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), fill)
        tcPr.append(sh)

    raters = [int(x) for x in sys.argv[2:]] or [1, 2]
    for r in raters:
        op = os.path.join(OUT, f"order_R{r}.csv")
        if not os.path.exists(op):              # additional rater: new rater-specific order, same method
            tids = [t["tid"] for t in tj["triplets"]]
            random.Random(SEED + r).shuffle(tids)
            with open(op, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["position", "tid"])
                for i, tid in enumerate(tids, 1):
                    w.writerow([i, tid])
        order = [row["tid"] for row in csv.DictReader(open(op, encoding="utf-8"))]
        doc = Document()
        sec = doc.sections[0]
        sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
        for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
            setattr(sec, side, Cm(2.0))
        st = doc.styles["Normal"]; st.font.name = "Times New Roman"; st.font.size = Pt(10.5)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), "游ゴシック")
        t = doc.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = t.add_run(f"Hypothesis booklet — Rater R{r}"); rr.bold = True; rr.font.size = Pt(15)
        doc.add_paragraph("各組の3つの仮説（A・B・C）を読み、有用性と新しさのそれぞれについて、最も高いものと最も低いものを評価シートに記入してください。"
                          "Read the three hypotheses (A, B, C) of each set and record, for usefulness and for novelty, the highest and the lowest one.")
        sets = [("練習 Practice", prac)] + [(f"No. {i}", trip[tid]) for i, tid in enumerate(order, 1)]
        for k, (label, tr) in enumerate(sets):
            if k:
                doc.add_page_break() if k % 2 == 1 else None
            h = doc.add_paragraph(); hr = h.add_run(f"{label}　（組ID: {tr['tid']}）"); hr.bold = True; hr.font.size = Pt(12)
            tb = doc.add_table(rows=3, cols=2); tb.style = "Table Grid"
            for j, lab in enumerate("ABC"):
                c0, c1 = tb.cell(j, 0), tb.cell(j, 1)
                c0.width, c1.width = Cm(1.2), Cm(15.8)
                c0.text = ""; x = c0.paragraphs[0].add_run(lab); x.bold = True; x.font.size = Pt(14)
                c0.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                shade(c0, "D9D9D9")
                c1.text = ""
                p1 = c1.paragraphs[0]; a = p1.add_run("Hypothesis: "); a.bold = True
                p1.add_run(text[tr[lab]]["hypothesis"])
                p2 = c1.add_paragraph(); b = p2.add_run("Description: "); b.bold = True
                p2.add_run(text[tr[lab]]["description"])
            doc.add_paragraph()
        os.makedirs(os.path.join(PKG, f"R{r}"), exist_ok=True)
        doc.save(os.path.join(PKG, f"R{r}", f"仮説冊子_R{r}.docx"))
        print(f"booklet R{r}: practice + {len(order)} sets")


if __name__ == "__main__":
    {"select": select, "render": render, "package": package, "practice": practice,
     "booklets": booklets}[sys.argv[1]]()
