# diversity_tests.py
# Tests whether the 30 hypotheses returned by the GA (one per seed) are more diverse than those returned by
# random search and hill climbing with the same objective and budget (Experiment 2, diversity measure of
# llm_hypothesis_metrics.py).  Measures: mean pairwise cosine similarity (lower = more diverse; primary) and the
# number of distinct hypotheses (secondary).  Two-sided permutation tests (labels of the 60 pooled runs shuffled,
# 20,000 permutations), Holm correction over the 2 comparisons x 2 measures, and a bootstrap 95% CI (runs
# resampled within each method) for the difference in mean pairwise similarity.
# Output: ../results/diversity_tests.csv
import os

import numpy as np
import pandas as pd

import creative_ga as cg
from concepts import hypothesis_text

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
N_PERM, N_BOOT, SEED = 20000, 10000, 2026


def mean_pair_cos(S, idx):
    sub = S[np.ix_(idx, idx)]
    iu = np.triu_indices(len(idx), 1)
    return float(sub[iu].mean())


def holm(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    for k, i in enumerate(order):
        running = max(running, (len(p) - k) * p[i])
        adj[i] = min(1.0, running)
    return adj


def main():
    rng = np.random.default_rng(SEED)
    emb = cg.Embedder()
    runs = pd.read_csv(os.path.join(RES, "runs.csv"))
    rows = []
    for other in ["Random", "HillClimb"]:
        a = runs[runs.method == "GA"].sort_values("seed")
        b = runs[runs.method == other].sort_values("seed")
        hs = list(zip(a.M, a.P, a.G)) + list(zip(b.M, b.P, b.G))
        Z = emb.encode([hypothesis_text(*h) for h in hs])
        S = Z @ Z.T
        n = len(a)
        ia, ib = np.arange(n), np.arange(n, 2 * n)
        cos_a, cos_b = mean_pair_cos(S, ia), mean_pair_cos(S, ib)
        dist_a, dist_b = len(set(hs[:n])), len(set(hs[n:]))
        obs_cos, obs_dist = cos_b - cos_a, dist_a - dist_b
        perm_cos, perm_dist = np.empty(N_PERM), np.empty(N_PERM)
        for k in range(N_PERM):
            pi = rng.permutation(2 * n)
            pa, pb = pi[:n], pi[n:]
            perm_cos[k] = mean_pair_cos(S, pb) - mean_pair_cos(S, pa)
            perm_dist[k] = len({hs[i] for i in pa}) - len({hs[i] for i in pb})
        p_cos = float((np.abs(perm_cos) >= abs(obs_cos) - 1e-12).mean())
        p_dist = float((np.abs(perm_dist) >= abs(obs_dist)).mean())
        boot = np.empty(N_BOOT)
        for k in range(N_BOOT):
            boot[k] = mean_pair_cos(S, rng.choice(ib, n)) - mean_pair_cos(S, rng.choice(ia, n))
        lo, hi = np.percentile(boot, [2.5, 97.5])
        f_a, f_b = a.f_search.mean(), b.f_search.mean()
        rows.append({"comparison": f"GA vs {other}", "measure": "mean_pairwise_cos",
                     "GA": round(cos_a, 3), "other": round(cos_b, 3), "difference_other_minus_GA": round(obs_cos, 3),
                     "boot_CI_low": round(lo, 3), "boot_CI_high": round(hi, 3), "p_perm": p_cos,
                     "mean_f_GA": round(f_a, 3), "mean_f_other": round(f_b, 3)})
        rows.append({"comparison": f"GA vs {other}", "measure": "distinct_hypotheses",
                     "GA": dist_a, "other": dist_b, "difference_other_minus_GA": dist_b - dist_a,
                     "p_perm": p_dist, "mean_f_GA": round(f_a, 3), "mean_f_other": round(f_b, 3)})
    d = pd.DataFrame(rows)
    d["p_holm"] = holm(d.p_perm).round(4)
    d.to_csv(os.path.join(RES, "diversity_tests.csv"), index=False)
    print(d.to_string())


if __name__ == "__main__":
    main()
