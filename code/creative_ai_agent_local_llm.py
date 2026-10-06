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
#
# Usage (llama-server must be running, see README_local_llm_setup_Win11.md):
#   python creative_ai_agent_local_llm.py --seed 1 --source ga
#   python creative_ai_agent_local_llm.py --seed 1 --source random

import argparse
import datetime
import json
import os
import random
import sys

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
    if finish == "length":
        body += ("\n\n> INCOMPLETE - generation stopped at LLM_MAX_TOKENS "
                 f"({LLM_MAX_TOKENS}). Re-run with a larger limit.\n")
    footer = (f"\n\n---\n*Generated by the proposed model ({os.path.basename(__file__)}; "
              f"hypothesis source = {args.source}, seed = {args.seed}) + local LLM writer "
              f"({LLM_MODEL_NAME} via llama.cpp, no web access). GA values: N={facts['novelty_score']}, "
              f"U={facts['utility_score']}, f={facts['overall_score']}. Date: {datetime.date.today()}*\n")
    with open(os.path.join(OUT_DIR, f"{run_id}.md"), "w", encoding="utf-8") as f:
        f.write(body.rstrip() + footer)
    with open(os.path.join(LOG_DIR, f"{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "facts": facts, "request_payload": payload,
                   "finish_reason": finish, "raw_response": raw}, f, ensure_ascii=False, indent=1)
    print(f"written: results/manuscripts/{run_id}.md  (log: results/writer_logs/{run_id}.json)")


if __name__ == "__main__":
    main()
