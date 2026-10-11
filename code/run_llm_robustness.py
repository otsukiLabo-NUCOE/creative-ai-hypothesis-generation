# run_llm_robustness.py — round-2 robustness experiments (Reviewer 1, Comments 2 and 3; pre-specified in
# Revision2/PREREGISTRATION_round2_experiments.md).
#   R2-A: LLM-proposed hypotheses for 2 models x 2 prompts x 2 temperatures (30 seeds each)
#   R2-B: scope-matched selection — the LLM chooses one Method, Problem and Goal from the GA's vocabulary
# llama-server must be serving the model given by --model on LLAMA_SERVER_ENDPOINT.
#   python run_llm_robustness.py --model nemotron
#   python run_llm_robustness.py --model llama8b
# Output: ../results/robustness/<config>/seed##.json (one file per seed; finished seeds are skipped)
import argparse
import json
import os
import re
import time

import requests

from concepts import CONCEPTS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "robustness")
ENDPOINT = os.environ.get("LLAMA_SERVER_ENDPOINT", "http://127.0.0.1:8080/v1/chat/completions")
TOP_P = 0.95
SEEDS = range(1, 31)

FORMAT = ("Express it as three short phrases: a Method (the technique to be used), a Problem (the problem to be "
          "addressed), and a Goal (the property to be improved). Answer only with a JSON object of the form "
          '{"method": "...", "problem": "...", "goal": "..."} and nothing else.')
PROMPTS = {
    # P0: the round-1 prompt, verbatim
    "P0": "Propose one novel and scientifically valid research hypothesis in the field of artificial intelligence, "
          "in particular generative AI. " + FORMAT,
    # P1: the same prompt without the generative-AI restriction
    "P1": "Propose one novel and scientifically valid research hypothesis in the field of artificial intelligence "
          "and machine learning. " + FORMAT,
}
SCOPE = ("Below are three lists of research concepts in artificial intelligence. Choose exactly one Method, one "
         "Problem, and one Goal from these lists so that the combination forms a novel and scientifically valid "
         "research hypothesis (using the Method to address the Problem in order to improve the Goal).\n\n"
         "Methods: " + "; ".join(CONCEPTS["Method"]) + "\n"
         "Problems: " + "; ".join(CONCEPTS["Problem"]) + "\n"
         "Goals: " + "; ".join(CONCEPTS["Goal"]) + "\n\n"
         "Use the items exactly as written. Answer only with a JSON object of the form "
         '{"method": "...", "problem": "...", "goal": "..."} and nothing else.')
MODELS = {"nemotron": "NVIDIA-Nemotron-Nano-9B-v2-Japanese-Q8_0.gguf", "llama8b": "Meta-Llama-3.1-8B-Instruct-Q8_0.gguf"}


def configs(model):
    out = []
    for pr in ("P0", "P1"):
        for temp in (0.7, 1.0):
            if model == "nemotron" and pr == "P0" and temp == 0.7:
                continue                     # identical to the round-1 set (results/controlled/hypotheses)
            out.append((f"{model}_{pr}_t{temp}", PROMPTS[pr], temp, None))
    vocab = {k: {v.lower(): v for v in CONCEPTS[k]} for k in CONCEPTS}
    out.append((f"{model}_scope_t0.7", SCOPE, 0.7, vocab))
    return out


def ask(prompt, temp, seed):
    payload = {"messages": [{"role": "user", "content": prompt}], "seed": seed, "temperature": temp,
               "top_p": TOP_P, "max_tokens": 300, "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.time()
    r = requests.post(ENDPOINT, json=payload, timeout=3600)
    r.raise_for_status()
    return payload, r.json()["choices"][0]["message"]["content"], time.time() - t0


def parse(text, vocab):
    m = re.search(r"\{.*?\}", text, re.S)
    if not m:
        return None
    try:
        h = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not all(isinstance(h.get(k), str) and h[k].strip() for k in ("method", "problem", "goal")):
        return None
    h = {k: h[k].strip() for k in ("method", "problem", "goal")}
    if vocab is not None:                    # scope-matched: exact vocabulary items only
        try:
            h = {"method": vocab["Method"][h["method"].lower()], "problem": vocab["Problem"][h["problem"].lower()],
                 "goal": vocab["Goal"][h["goal"].lower()]}
        except KeyError:
            return None
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=MODELS, required=True)
    a = ap.parse_args()
    for name, prompt, temp, vocab in configs(a.model):
        d = os.path.join(OUT, name)
        os.makedirs(d, exist_ok=True)
        for seed in SEEDS:
            out = os.path.join(d, f"seed{seed:02d}.json")
            if os.path.exists(out):
                continue
            tries = []
            for attempt in range(5):
                payload, text, dt = ask(prompt, temp, seed + 1000 * attempt)
                h = parse(text, vocab)
                tries.append({"attempt": attempt, "raw_text": text, "seconds": round(dt, 1)})
                if h:
                    break
            rec = {"config": name, "model_file": MODELS[a.model], "seed": seed, "hypothesis": h,
                   "payload": payload, "attempts": tries}
            json.dump(rec, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"{name} seed {seed}: {h} ({sum(t['seconds'] for t in tries):.0f}s)", flush=True)


if __name__ == "__main__":
    main()
