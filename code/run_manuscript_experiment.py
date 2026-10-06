# run_manuscript_experiment.py
#
# Controlled manuscript-generation experiment (Experiment 4 of the revised manuscript; Appendix A).
# Answers Reviewer 1 #3/#5 and Reviewer 2 #2/#3: only the hypothesis source varies.
#
#   Conditions (hypothesis source)        writer input (identical format for all conditions)
#   ga     : revised GA (creative_ga.py)   Method / Problem / Goal phrases only - no scores, no
#   random : uniform draw from the same    hint about how the hypothesis was obtained, no code
#            concept set                   or other extra context
#   llm    : proposed by the writer LLM itself, without the concept set
#
#   Held fixed: writer model (one GGUF served by llama.cpp), system prompt, user-prompt template,
#   decoding settings, thinking mode (off), and the writer sampling seed (100 + s for seed s).
#
# Usage (llama-server must be running on LLAMA_SERVER_ENDPOINT):
#   python run_manuscript_experiment.py                 # 10 manuscripts per condition (seeds 1-10)
#   python run_manuscript_experiment.py --hyp-only 30   # additionally: 30 LLM-proposed hypotheses
#                                                       # (no manuscript) for the hypothesis-level
#                                                       # comparison with GA / random search
# Re-running resumes: existing outputs are skipped.

import argparse
import datetime
import json
import os
import re
import sys
import time

import requests

import creative_ga as cg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "controlled")
PROMPTS = os.path.join(HERE, "..", "prompts")
ENDPOINT = os.environ.get("LLAMA_SERVER_ENDPOINT", "http://127.0.0.1:8080/v1/chat/completions")
MODEL_FILE = os.environ.get("WRITER_MODEL_FILE", "NVIDIA-Nemotron-Nano-9B-v2-Japanese-Q8_0.gguf")
DECODING = {"temperature": 0.7, "top_p": 0.95, "max_tokens": 4500,
            "chat_template_kwargs": {"enable_thinking": False}}
CONDITIONS = ["ga", "random", "llm"]
REQUIRED_SECTIONS = ["Abstract", "Introduction", "Related Work", "Proposed Method", "Experimental Design",
                     "Reproducibility", "Discussion", "Limitations", "Conclusion"]


def read(name):
    with open(os.path.join(PROMPTS, name), encoding="utf-8") as f:
        return f.read().strip()


# Fixed section-by-section writing procedure, identical for all conditions. (A single request makes
# the small writer model stop after the Abstract, so every manuscript is written with the same
# sequence of nine requests, each seeing the sections written so far.)
SECTIONS = [("Title and Abstract", "a title line of the form '# <title>' followed by '## Abstract' and an abstract of about 150 words"),
            ("1. Introduction", "about 250 words"),
            ("2. Related Work", "about 200 words, as qualitative background without specific citations"),
            ("3. Proposed Method", "about 350 words, including a mathematical formulation"),
            ("4. Experimental Design", "about 250 words, as a plan for future validation"),
            ("5. Reproducibility", "about 120 words"),
            ("6. Discussion of Applications Across Multiple Domains", "about 200 words"),
            ("7. Limitations", "about 120 words"),
            ("8. Conclusion", "about 100 words")]


def write_manuscript(system, h, seed):
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": f"Hypothesis:\nMethod: {h['method']}\nProblem: {h['problem']}\n"
                                        f"Goal: {h['goal']}\n\nWe will now write the manuscript section by section."}]
    parts, calls, total = [], [], 0.0
    for i, (name, spec) in enumerate(SECTIONS):
        heading = "" if i == 0 else f" Begin with the heading '## {name}'."
        instr = f"Write only the section '{name}': {spec}.{heading}"
        if i == 0:
            msgs[-1]["content"] += "\n\n" + instr
        else:
            msgs.append({"role": "user", "content": instr})
        payload = {"messages": msgs, "seed": seed, **DECODING, "max_tokens": 1200}
        t0 = time.time()
        r = requests.post(ENDPOINT, json=payload, timeout=7200)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        total += time.time() - t0
        msgs.append({"role": "assistant", "content": text})
        parts.append(text)
        calls.append({"section": name, "instruction": instr, "finish_reason": data["choices"][0].get("finish_reason"),
                      "usage": data.get("usage"), "content": text})
    return "\n\n".join(parts), calls, total


def chat(system, user, seed, max_tokens=None):
    payload = {"messages": ([{"role": "system", "content": system}] if system else []) +
                           [{"role": "user", "content": user}], "seed": seed, **DECODING}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    t0 = time.time()
    r = requests.post(ENDPOINT, json=payload, timeout=7200)
    r.raise_for_status()
    data = r.json()
    ch = data["choices"][0]
    return payload, ch["message"]["content"], ch.get("finish_reason"), data, time.time() - t0


def llm_hypothesis(seed):
    """Condition 'llm': the writer model proposes its own Method/Problem/Goal (same decoding)."""
    prompt = read("controlled_llm_hypothesis_prompt.txt")
    for attempt in range(5):
        payload, text, finish, raw, dt = chat(None, prompt, seed + 1000 * attempt, max_tokens=300)
        m = re.search(r"\{.*?\}", text, re.S)
        if m:
            try:
                h = json.loads(m.group(0))
                if all(isinstance(h.get(k), str) and h[k].strip() for k in ("method", "problem", "goal")):
                    return {k: h[k].strip() for k in ("method", "problem", "goal")}, \
                        {"payload": payload, "raw_text": text, "attempt": attempt}
            except json.JSONDecodeError:
                pass
    raise RuntimeError(f"LLM did not return a valid hypothesis for seed {seed}")


def hypothesis(cond, seed, land):
    if cond == "ga":
        t = cg.run_ga(land, seed).best
        return {"method": land.M[t[0]], "problem": land.P[t[1]], "goal": land.G[t[2]]}, {}
    if cond == "random":
        t = cg.run_random(land, seed, budget=1).best
        return {"method": land.M[t[0]], "problem": land.P[t[1]], "goal": land.G[t[2]]}, {}
    return llm_hypothesis(seed)


def check(text):
    missing = [s for s in REQUIRED_SECTIONS if not re.search(rf"^#+\s*(\d+\.\s*)?{re.escape(s)}", text, re.M | re.I)]
    return {"words": len(text.split()), "missing_sections": missing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--hyp-only", type=int, default=0, help="also propose N LLM hypotheses without manuscripts")
    ap.add_argument("--practice", action="store_true",
                    help="only write the practice manuscript for raters (random hypothesis, seed 99; not analysed)")
    args = ap.parse_args()
    if args.practice:
        emb = cg.Embedder(); ks = cg.KnowledgeSpace.build(emb); land = cg.Landscape(ks, emb)
        h, _ = hypothesis("random", 99, land)
        text, calls, dt = write_manuscript(read("controlled_writer_system_prompt.txt"), h, 199)
        os.makedirs(os.path.join(OUT, "practice"), exist_ok=True)
        open(os.path.join(OUT, "practice", "practice.md"), "w", encoding="utf-8").write(text.strip() + "\n")
        json.dump({"hypothesis": h, "calls": calls}, open(os.path.join(OUT, "practice", "practice_log.json"), "w",
                  encoding="utf-8"), ensure_ascii=False, indent=1)
        print("practice:", h, check(text), f"{dt/60:.1f} min")
        return
    for d in ("manuscripts", "logs", "hypotheses"):
        os.makedirs(os.path.join(OUT, d), exist_ok=True)
    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)
    land = cg.Landscape(ks, emb)
    system = read("controlled_writer_system_prompt.txt")

    for s in range(1, args.seeds + 1):
        for cond in CONDITIONS:                     # interleaved so that partial runs stay balanced
            rid = f"{cond}_seed{s:02d}"
            md = os.path.join(OUT, "manuscripts", rid + ".md")
            if os.path.exists(md):
                continue
            h, hlog = hypothesis(cond, s, land)
            text, calls, dt = write_manuscript(system, h, 100 + s)
            finish = [c["finish_reason"] for c in calls]
            payload = {"decoding": DECODING, "max_tokens_per_section": 1200, "seed": 100 + s,
                       "sections": [c["instruction"] for c in calls]}
            raw = calls
            info = check(text)
            with open(md, "w", encoding="utf-8") as f:
                f.write(text.strip() + "\n")
            with open(os.path.join(OUT, "logs", rid + ".json"), "w", encoding="utf-8") as f:
                json.dump({"run_id": rid, "condition": cond, "seed": s, "writer_seed": 100 + s,
                           "hypothesis": h, "hypothesis_log": hlog, "writer_model_file": MODEL_FILE,
                           "request_payload": payload, "finish_reason": finish, "seconds": round(dt, 1),
                           "check": info, "raw_response": raw, "time": datetime.datetime.now().isoformat()},
                          f, ensure_ascii=False, indent=1)
            print(f"[{datetime.datetime.now():%H:%M}] {rid}: {h['method']} / {h['problem']} / {h['goal']} "
                  f"-> {info['words']} words, finish={finish}, missing={info['missing_sections']}, {dt/60:.1f} min",
                  flush=True)

    for s in range(1, args.hyp_only + 1):
        p = os.path.join(OUT, "hypotheses", f"llm_seed{s:02d}.json")
        if os.path.exists(p):
            continue
        h, hlog = llm_hypothesis(s)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"seed": s, "hypothesis": h, "log": hlog}, f, ensure_ascii=False, indent=1)
        print(f"hypothesis-only llm_seed{s:02d}: {h}", flush=True)


if __name__ == "__main__":
    main()
