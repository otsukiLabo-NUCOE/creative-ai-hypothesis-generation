# creative_ga.py
#
# Revised implementation of the proposed model (Sections 3.1-3.4 of the revised manuscript).
#
# What changed relative to the originally submitted version (creative_ai_agent_local_llm.py),
# and which reviewer comment each change answers:
#
#   * Knowledge space  (R1 #4, R2 #1): three hard-coded "simulated" papers  ->  several thousand
#     real arXiv records (build_knowledge_space.py), split into a SEARCH set that the GA sees
#     and held-out EVALUATION sets that it never sees.
#
#   * Representation   (R1 #1): random.seed(text) 5-d hash "fingerprints" (no semantic content,
#     and incompatible with the hand-written semantic hypothesis vectors of Table 3)  ->  ONE
#     sentence encoder phi (all-MiniLM-L6-v2, 384-d, L2-normalised) applied to BOTH paper
#     title+abstract AND the natural-language rendering of every hypothesis, so that distances
#     between hypotheses and papers are computed in a single, shared semantic space.
#
#   * Utility          (R1 #2): three hand-written keyword rules (Table 6, e.g. "Quantum" AND
#     "Latency" -> +0.4), which were ALSO reused by the manuscript evaluator (circularity)  ->
#     a literature-grounded link-support score: each pairwise link (M-P, M-G, P-G) is scored by
#     how closely it is attested in the SEARCH corpus. No hand-written rule remains.
#
#   * Fitness          : the original code used f = 0.6 N + 0.4 U while the manuscript wrote
#     f = N + U (Eq. 21) and a different re-evaluation C(h') in Sec. 3.4. These are now one and
#     the same function, f(h) = C(h) = alpha N(h) + beta U(h), alpha = 0.6, beta = 0.4.
#
#   * Reproducibility  (R1 #3, #7): every stochastic component draws from an explicit
#     random.Random(seed); every fitness evaluation is counted; each run returns a full log.
#
# Novelty and utility here are SEARCH-TIME signals only. Everything reported as an outcome in
# the paper is computed by evaluation.py on data the GA never sees (temporal hold-out), so the
# outcome measure is not the objective that was optimised (R1 #2).

import json
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from concepts import CONCEPTS, hypothesis_text, pair_texts

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

ALPHA_NOVELTY = 0.6
BETA_UTILITY = 0.4
GENERATION_COUNT = 20
POPULATION_SIZE = 10
N_ELITE = 2
PARENT_POOL = 5
MUTATION_RATE = 0.3
EVAL_BUDGET = GENERATION_COUNT * POPULATION_SIZE   # 200 fitness evaluations per run
SPLIT_SEED = 12345                                  # fixed split of the past corpus


# ==========================================
# 1. Knowledge space K
# ==========================================

def load_corpus(path=os.path.join(DATA_DIR, "corpus.jsonl")) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class Embedder:
    """phi: text -> R^384 (unit norm). Embeddings are cached on disk keyed by a hash of the
    text list so repeated experiments are fast and bit-identical."""

    def __init__(self, model_name=EMBED_MODEL):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts: List[str], cache_name: Optional[str] = None) -> np.ndarray:
        if cache_name:
            os.makedirs(CACHE_DIR, exist_ok=True)
            import hashlib
            h = hashlib.sha1(("\n".join(texts) + self.model_name).encode("utf-8")).hexdigest()[:12]
            p = os.path.join(CACHE_DIR, f"{cache_name}_{h}.npy")
            if os.path.exists(p):
                return np.load(p)
        v = self.model.encode(texts, batch_size=64, normalize_embeddings=True,
                              show_progress_bar=False, convert_to_numpy=True).astype(np.float32)
        if cache_name:
            np.save(p, v)
        return v


@dataclass
class KnowledgeSpace:
    """K = (C, P): concept set C (concepts.py) and paper collection P with embedding matrix V
    (Eq. 8). The past corpus is split once (fixed seed) into
        search    : the only papers the GA may use (novelty and utility during search)
        eval_past : held-out past papers, size-matched to the future set
    and the future corpus (2024-07..2025-12) is never touched during search."""
    concepts: Dict[str, List[str]]
    search: List[dict]
    eval_past: List[dict]
    future: List[dict]
    V_search: np.ndarray = None
    V_eval_past: np.ndarray = None
    V_future: np.ndarray = None

    @staticmethod
    def paper_text(p):
        return f"{p['title']}. {p['abstract']}"

    @classmethod
    def build(cls, embedder: Embedder, corpus: Optional[List[dict]] = None):
        corpus = corpus or load_corpus()
        past = [p for p in corpus if p["window"] == "past"]
        future = [p for p in corpus if p["window"] == "future"]
        rng = random.Random(SPLIT_SEED)
        past = sorted(past, key=lambda p: p["id"])
        rng.shuffle(past)
        n_eval = min(len(future), len(past) // 2)
        eval_past, search = past[:n_eval], past[n_eval:]
        # size-match the future set to eval_past (max-similarity statistics depend on set size)
        future = sorted(future, key=lambda p: p["id"])
        rng.shuffle(future)
        future = future[:n_eval]
        ks = cls(CONCEPTS, search, eval_past, future)
        ks.V_search = embedder.encode([cls.paper_text(p) for p in search], "search")
        ks.V_eval_past = embedder.encode([cls.paper_text(p) for p in eval_past], "evalpast")
        ks.V_future = embedder.encode([cls.paper_text(p) for p in future], "future")
        return ks


# ==========================================
# 2. Hypotheses and the (pre-computed) fitness landscape
# ==========================================

Triple = Tuple[int, int, int]   # indices into Method / Problem / Goal


class Landscape:
    """Pre-computes phi(h) for all |M|x|P|x|G| hypotheses and phi(pair) for every pairwise link,
    so that a fitness evaluation is a table lookup. This does NOT give the search methods any
    information: they still only observe f(h) for the hypotheses they choose to evaluate, and
    every such observation is counted against the budget."""

    def __init__(self, ks: KnowledgeSpace, embedder: Embedder,
                 alpha=ALPHA_NOVELTY, beta=BETA_UTILITY, V_ref: Optional[np.ndarray] = None):
        self.ks = ks
        C = ks.concepts
        self.M, self.P, self.G = C["Method"], C["Problem"], C["Goal"]
        self.shape = (len(self.M), len(self.P), len(self.G))
        self.alpha, self.beta = alpha, beta
        V_ref = ks.V_search if V_ref is None else V_ref

        self.triples = [(i, j, k) for i in range(self.shape[0])
                        for j in range(self.shape[1]) for k in range(self.shape[2])]
        self.texts = [hypothesis_text(self.M[i], self.P[j], self.G[k]) for i, j, k in self.triples]
        self.Z = embedder.encode(self.texts, "hyp")                       # phi(h)

        # Novelty, Eq. (18)/(27)-(28) revised:  N(h) = 1 - max_{k in K_search} cos(phi(h), v_k)
        self.maxsim_search = (self.Z @ V_ref.T).max(axis=1)
        self.N = (1.0 - self.maxsim_search).reshape(self.shape)

        # Utility, Eq. (19)/(29) revised: mean literature support of the three pairwise links
        mp = [f"{m} for {p}" for m in self.M for p in self.P]
        mg = [f"{m} for {g}" for m in self.M for g in self.G]
        pg = [f"addressing {p} to improve {g}" for p in self.P for g in self.G]
        s_mp = (embedder.encode(mp, "mp") @ V_ref.T).max(axis=1).reshape(len(self.M), len(self.P))
        s_mg = (embedder.encode(mg, "mg") @ V_ref.T).max(axis=1).reshape(len(self.M), len(self.G))
        s_pg = (embedder.encode(pg, "pg") @ V_ref.T).max(axis=1).reshape(len(self.P), len(self.G))
        self.U = (s_mp[:, :, None] + s_mg[:, None, :] + s_pg[None, :, :]) / 3.0
        self.set_weights(alpha, beta)

    def set_weights(self, alpha, beta):
        self.alpha, self.beta = alpha, beta
        self.F = alpha * self.N + beta * self.U

    def name(self, t: Triple) -> str:
        return f"{self.M[t[0]]} for {self.G[t[2]]} to solve {self.P[t[1]]}"

    def flat(self, t: Triple) -> int:
        return (t[0] * self.shape[1] + t[1]) * self.shape[2] + t[2]


class Budget:
    """Counts fitness evaluations; raises once the budget is exhausted."""

    class Exhausted(Exception):
        pass

    def __init__(self, land: Landscape, limit=EVAL_BUDGET):
        self.land, self.limit, self.used = land, limit, 0
        self.best: Optional[Triple] = None
        self.best_f = -np.inf
        self.trace: List[float] = []      # best-so-far after each evaluation

    def f(self, t: Triple) -> float:
        if self.used >= self.limit:
            raise Budget.Exhausted
        self.used += 1
        v = float(self.land.F[t])
        if v > self.best_f:
            self.best, self.best_f = t, v
        self.trace.append(self.best_f)
        return v


# ==========================================
# 3. Search methods (all share the same budget and the same fitness function)
# ==========================================

def _rand_triple(rng, shape) -> Triple:
    return (rng.randrange(shape[0]), rng.randrange(shape[1]), rng.randrange(shape[2]))


def run_ga(land: Landscape, seed: int, budget=EVAL_BUDGET, pop_size=POPULATION_SIZE,
           n_elite=N_ELITE, parent_pool=PARENT_POOL, p_mut=MUTATION_RATE) -> Budget:
    """Proposed GA (Sec. 3.3): uniform initialisation (Eq. 12/17), ranking (Eq. 21), elitism of the
    top 2 (Eq. 22), uniform crossover with parents drawn from the top 5 (Eq. 13-14, 23), single-
    attribute mutation with p = 0.3 applied to offspring only (Eq. 15-16, 24), next generation
    (Eq. 25). 20 generations x 10 individuals = 200 evaluations."""
    rng = random.Random(seed)
    B = Budget(land, budget)
    pop = [_rand_triple(rng, land.shape) for _ in range(pop_size)]
    try:
        while True:
            scored = sorted(((B.f(h), h) for h in pop), key=lambda x: -x[0])
            ranked = [h for _, h in scored]
            nxt = ranked[:n_elite]
            while len(nxt) < pop_size:
                p1, p2 = rng.choice(ranked[:parent_pool]), rng.choice(ranked[:parent_pool])
                child = tuple(p1[d] if rng.random() < 0.5 else p2[d] for d in range(3))
                if rng.random() < p_mut:
                    d = rng.randrange(3)
                    child = tuple(rng.randrange(land.shape[d]) if e == d else child[e] for e in range(3))
                nxt.append(child)
            pop = nxt
    except Budget.Exhausted:
        pass
    return B


def run_random(land: Landscape, seed: int, budget=EVAL_BUDGET) -> Budget:
    """Baseline: uniform random sampling of the same number of hypotheses."""
    rng = random.Random(seed)
    B = Budget(land, budget)
    try:
        while True:
            B.f(_rand_triple(rng, land.shape))
    except Budget.Exhausted:
        pass
    return B


def run_hillclimb(land: Landscape, seed: int, budget=EVAL_BUDGET, restart_after=25) -> Budget:
    """Baseline: stochastic hill climbing with the GA's own mutation operator and random restarts."""
    rng = random.Random(seed)
    B = Budget(land, budget)
    try:
        while True:
            cur = _rand_triple(rng, land.shape)
            fc, stall = B.f(cur), 0
            while stall < restart_after:
                d = rng.randrange(3)
                nb = tuple(rng.randrange(land.shape[d]) if e == d else cur[e] for e in range(3))
                fn = B.f(nb)
                if fn > fc:
                    cur, fc, stall = nb, fn, 0
                else:
                    stall += 1
    except Budget.Exhausted:
        pass
    return B


SEARCH_METHODS = {"GA": run_ga, "Random": run_random, "HillClimb": run_hillclimb}
