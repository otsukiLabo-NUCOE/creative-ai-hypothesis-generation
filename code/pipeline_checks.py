# pipeline_checks.py — checks that the steps of the workflow were run in order (v1.0.4).
#
#   step 2  make_concepts.py                  writes concepts.py and data/vocabulary_info.json
#   step 3  build_knowledge_space_openalex.py writes data/corpus.jsonl and data/corpus_build_log.json
#   step 4  top_hypotheses.py / step 6 creative_ai_agent_local_llm.py read both
#
# The checks only warn or ask for confirmation; they never change files.
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
VOCAB_INFO = os.path.join(DATA_DIR, "vocabulary_info.json")

# the vocabulary used in the paper (AI); a concepts.py that still equals it has not been replaced yet
PAPER_VOCABULARY = {
    "Method": ["Transformer", "Diffusion Model", "Reinforcement Learning", "Evolutionary Strategy",
               "Knowledge Graph", "Symbolic AI", "Quantum Annealing", "Graph Neural Network",
               "Contrastive Learning", "Federated Learning", "Retrieval-Augmented Generation",
               "Bayesian Optimization", "Multi-Agent System", "Neural Architecture Search", "Causal Inference"],
    "Problem": ["Hallucination", "Catastrophic Forgetting", "Data Scarcity", "High Latency", "Bias",
                "Lack of Novelty", "Energy Consumption", "Adversarial Vulnerability", "Distribution Shift",
                "Privacy Leakage", "Reward Hacking", "Long-Context Reasoning", "Label Noise",
                "Miscalibrated Uncertainty", "Opaque Decision Making"],
    "Goal": ["Creativity", "Robustness", "Efficiency", "Fairness", "Autonomy", "Explainability", "Scalability",
             "Safety", "Generalization", "Personalization", "Trustworthiness", "Sustainability"],
}

BAR = "!" * 78


def warn(lines):
    print("\n" + BAR + "\n" + "\n".join(lines) + "\n" + BAR + "\n", file=sys.stderr, flush=True)


def confirm(question, force=False):
    """Asks y/N; returns True to continue. Without an interactive console it stops (use --force)."""
    if force:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        print("Stopped. Run again with --force to continue anyway.", file=sys.stderr)
        return False
    try:
        return input(question + " [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def is_paper_vocabulary(concepts):
    return all(sorted(concepts.get(k, [])) == sorted(v) for k, v in PAPER_VOCABULARY.items())


def save_vocabulary_info(info):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(VOCAB_INFO, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)


def load_vocabulary_info():
    if not os.path.exists(VOCAB_INFO):
        return None
    with open(VOCAB_INFO, encoding="utf-8") as f:
        return json.load(f)


def notice_api_key():
    if not os.environ.get("OPENALEX_API_KEY"):
        print("NOTE: OPENALEX_API_KEY is not set. Without a free key (https://openalex.org/settings/api) the daily "
              "request budget is shared by everyone on your network and may run out.", file=sys.stderr, flush=True)


def check_before_building(concepts, fields, force=False):
    """Step 3 guards: the vocabulary has been written (step 2), and FIELDS matches its subfield."""
    if is_paper_vocabulary(concepts):
        warn(["WARNING: concepts.py still contains the default vocabulary of the paper (AI).",
              "  Did you run make_concepts.py only with --dry-run (step 1)? To build a knowledge space for",
              "  your own field, first write the vocabulary (step 2), e.g.:",
              "      python make_concepts.py --subfield 1404"])
        if not confirm("Build the knowledge space with the default AI vocabulary anyway?", force):
            return False
    info = load_vocabulary_info()
    if info and info.get("subfield"):
        field = str(int(str(info["subfield"])) // 100)   # OpenAlex subfield 1404 belongs to field 14
        allowed = [f.strip() for f in str(fields).split("|")]
        if field not in allowed:
            warn([f"WARNING: the vocabulary was made for subfield {info['subfield']} (field {field}),",
                  f"  but FIELDS in build_knowledge_space_openalex.py is \"{fields}\".",
                  "  Papers would be collected from other fields. Change FIELDS at the top of the script, e.g.:",
                  f"      FIELDS = \"{field}\""])
            if not confirm("Collect papers with the current FIELDS anyway?", force):
                return False
    return True
