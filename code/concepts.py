# concepts.py
#
# Method / Problem / Goal vocabulary (the concept set C of Equation (3)).
# The original version used 7 Methods x 7 Problems x 6 Goals (294 combinations). The revised
# version keeps all of the original terms and extends each set, giving 15 x 15 x 12 = 2,700
# combinations, so that the GA search space is large enough that a 200-evaluation budget covers
# only ~7% of it (otherwise any search method trivially finds the optimum).
# The vocabulary is curated by the author and disclosed here in full (Reviewer 1 #7).

CONCEPTS = {
    "Method": [
        "Transformer", "Diffusion Model", "Reinforcement Learning", "Evolutionary Strategy",
        "Knowledge Graph", "Symbolic AI", "Quantum Annealing", "Graph Neural Network",
        "Contrastive Learning", "Federated Learning", "Retrieval-Augmented Generation",
        "Bayesian Optimization", "Multi-Agent System", "Neural Architecture Search",
        "Causal Inference",
    ],
    "Problem": [
        "Hallucination", "Catastrophic Forgetting", "Data Scarcity", "High Latency", "Bias",
        "Lack of Novelty", "Energy Consumption", "Adversarial Vulnerability", "Distribution Shift",
        "Privacy Leakage", "Reward Hacking", "Long-Context Reasoning", "Label Noise",
        "Miscalibrated Uncertainty", "Opaque Decision Making",
    ],
    "Goal": [
        "Creativity", "Robustness", "Efficiency", "Fairness", "Autonomy", "Explainability",
        "Scalability", "Safety", "Generalization", "Personalization", "Trustworthiness",
        "Sustainability",
    ],
}


def hypothesis_text(m, p, g):
    """Natural-language rendering of h = (m, p, g). The same sentence encoder phi is applied to
    this text and to every paper's title+abstract, so hypotheses and papers live in ONE vector
    space (Reviewer 1 #1)."""
    return f"Using {m} to address {p} in order to improve {g}."


def pair_texts(m, p, g):
    """The three pairwise links evaluated by the utility term (M-P, M-G, P-G)."""
    return (f"{m} for {p}", f"{m} for {g}", f"addressing {p} to improve {g}")
