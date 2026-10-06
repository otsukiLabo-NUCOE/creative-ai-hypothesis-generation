# llm_judge.py
#
# Blinded LLM-as-judge evaluation of the 30 controlled manuscripts (Experiment 4), with the same
# rubric as the human raters (rater manual, Section 4). The judge (Llama-3.1-8B-Instruct, a model
# family different from the writer Nemotron-Nano-9B) sees only the manuscript text under its blinded
# code; it never sees the condition, the hypothesis source, or any generation metadata.
# Each manuscript is judged in 3 independent runs (sampling seeds 1-3) to quantify judge variability.
#
# Usage (judge served by llama-server on JUDGE_ENDPOINT):
#   python llm_judge.py
# Output: ../results/controlled/llm_judge/<code>_run<k>.json, ../results/controlled/llm_judge_ratings.csv
#         (one row per run; column 'rater' = LLM-run<k>, same columns as the human rating CSVs)

import csv
import json
import os
import re
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.join(HERE, "..", "results", "controlled")
OUT = os.path.join(CTRL, "llm_judge")
ENDPOINT = os.environ.get("JUDGE_ENDPOINT", "http://127.0.0.1:8081/v1/chat/completions")
JUDGE_MODEL_FILE = os.environ.get("JUDGE_MODEL_FILE", "Meta-Llama-3.1-8B-Instruct-Q8_0.gguf")
RUNS = [1, 2, 3]
DECODING = {"temperature": 0.7, "top_p": 0.95, "max_tokens": 500}
CRITERIA = ["originality", "soundness", "reproducibility", "significance"]

SYSTEM = "You are an experienced reviewer for an artificial-intelligence research journal. You evaluate research manuscripts strictly and fairly according to the rubric you are given."

RUBRIC = """Evaluate the research manuscript below on four criteria, each as an integer from 1 to 5. A score of 3 corresponds to an average research proposal.

1. Originality: Is the central idea (which method is used, which problem it addresses, which property it improves) new compared with research you know?
   1 = a rephrasing of a well-known existing idea; 2 = almost the same as existing work, little that is new; 3 = a combination of existing elements with some novelty in how they are combined; 4 = a clearly new perspective that is not obvious; 5 = highly novel and non-obvious, could open a new direction.
2. Technical soundness: Are the proposed method, the mathematical formulation, and the reasoning correct and consistent? Is the method actually connected to the problem? Are there errors or logical leaps?
   1 = serious errors, or the method does not address the problem; 2 = noticeable errors or leaps, weak support; 3 = broadly reasonable but with vague points or minor errors; 4 = no major problems, the reasoning holds; 5 = consistent and accurate, convincing to an expert.
3. Reproducibility: Could the method be implemented and the experimental plan be carried out from the text alone (are procedures, settings, and evaluation specified concretely)?
   1 = impossible to know what to do; 2 = the direction is clear but most important parts are missing; 3 = the main parts can be implemented but several important details are missing; 4 = implementable with minor additions; 5 = concrete enough to implement and run as written.
4. Significance: Is the research worth pursuing? How large would its impact be if successful, and how broad is its applicability?
   1 = hardly worth pursuing; 2 = some value but very limited; 3 = some value, useful to researchers in related areas; 4 = valuable to many researchers or application areas; 5 = could have a major impact on the field.

Rules:
- Do not penalize the absence of experimental results or of citations: every manuscript was asked to present experiments only as a plan and to avoid specific citations. Judge whether the plan is sound.
- Judge the content, not the fluency, length, or formatting of the English.
- Specific numbers stated as results are not based on real experiments; do not reward them. Presenting unsupported numbers as results may be reflected in technical soundness.

Also report:
- already_known: "Yes" if the central idea is essentially already published as far as you know, "No" if not, "Unsure" otherwise.
- confidence: an integer from 1 (mostly guessing) to 5 (confident).
- rationale: at most 60 words.

Answer only with a JSON object of the form
{"originality": n, "soundness": n, "reproducibility": n, "significance": n, "already_known": "Yes|No|Unsure", "confidence": n, "rationale": "..."}

MANUSCRIPT (code {code}):
<<<
{text}
>>>"""


def judge(code, text, seed):
    payload = {"messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": RUBRIC.replace("{code}", code).replace("{text}", text)}],
               "seed": seed, **DECODING}
    for attempt in range(4):
        payload["seed"] = seed + 100 * attempt
        t0 = time.time()
        r = requests.post(ENDPOINT, json=payload, timeout=3600)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            d = None
        if d and all(isinstance(d.get(c), (int, float)) and 1 <= d[c] <= 5 for c in CRITERIA):
            return d, {"payload_seed": payload["seed"], "attempt": attempt, "raw": content,
                       "seconds": round(time.time() - t0, 1)}
    raise RuntimeError(f"no valid judgment for {code} run seed {seed}")


def main():
    os.makedirs(OUT, exist_ok=True)
    key = list(csv.DictReader(open(os.path.join(CTRL, "_KEY_do_not_share.csv"), encoding="utf-8")))
    rows = []
    # manuscript-major order: the 3 runs of one manuscript share the same prompt prefix, so the
    # server's prompt cache avoids re-reading the manuscript (results are identical either way)
    for k in key:
        for run in RUNS:
            code = k["code"]
            path = os.path.join(OUT, f"{code}_run{run}.json")
            if not os.path.exists(path):
                text = open(os.path.join(CTRL, "manuscripts", k["original_file"]), encoding="utf-8").read()
                d, log = judge(code, text, run)
                json.dump({"code": code, "run": run, "judge_model_file": JUDGE_MODEL_FILE, "decoding": DECODING,
                           "judgment": d, "log": log}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"{code} run{run}: {[d[c] for c in CRITERIA]} ({log['seconds']}s)", flush=True)
            d = json.load(open(path, encoding="utf-8"))["judgment"]
            rows.append({"rater": f"LLM-run{run}", "code": code, **{c: d[c] for c in CRITERIA},
                         "already known": d.get("already_known", ""), "confidence": d.get("confidence", ""),
                         "comment": d.get("rationale", "")})
    with open(os.path.join(CTRL, "llm_judge_ratings.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("written llm_judge_ratings.csv", len(rows))


if __name__ == "__main__":
    main()
