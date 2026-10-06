# run_experiments.py
#
# Experiments of the revised manuscript (Section 4). Everything reported in the paper's new
# Tables/Figures is produced by this script from data/corpus.jsonl; nothing is hand-entered.
#
#   Exp. 1  Search effectiveness : GA vs Random search vs Hill climbing, identical fitness and
#                                  identical budget (200 evaluations), 30 seeds each.
#   Exp. 2  Hold-out outcomes    : the hypotheses selected in Exp. 1 (plus ablations and two
#                                  no-search references) evaluated on data the GA never saw:
#                                  held-out past papers and FUTURE papers (2024-07..2025-12).
#   Exp. 3  Corpus-size sensitivity: how the resolution of the novelty measure depends on the size
#                                  of the knowledge space (3 papers as in the original version
#                                  up to the full search corpus).
#
# Outputs (../results/): runs.csv, stats_*.csv, sensitivity.csv, summary.json, run_logs/*.json,
#                        fig_*.png, environment.json
#
# Usage: python run_experiments.py         (~3-5 min on CPU after the corpus has been built)

import json
import os
import platform
import random
import sys
import datetime
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_extraction.text import TfidfVectorizer

import creative_ga as cg
from concepts import hypothesis_text

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
LOGS = os.path.join(RES, "run_logs")
SEEDS = list(range(1, 31))
N_BOOT = 10000
MATCH_TOL = 0.01

ORIGINAL_THREE_PAPERS = [   # the knowledge space of the originally submitted version
    ("Attention is All You Need", "Transformer architecture for sequence"),
    ("Language Models are Few-Shot Learners", "GPT-3 and in-context learning"),
    ("Constitutional AI", "RLHF and safety based on rules"),
]


def a12(x, y):
    """Vargha-Delaney A12: P(X > Y) + 0.5 P(X = Y)."""
    x, y = np.asarray(x), np.asarray(y)
    gt = (x[:, None] > y[None, :]).sum()
    eq = (x[:, None] == y[None, :]).sum()
    return (gt + 0.5 * eq) / (len(x) * len(y))


def boot_ci(x, rng, n=N_BOOT):
    x = np.asarray(x)
    means = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def holm(pvals):
    order = np.argsort(pvals)
    adj = np.empty(len(pvals))
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (len(pvals) - rank) * pvals[idx])
        adj[idx] = min(1.0, running)
    return adj


def main():
    os.makedirs(LOGS, exist_ok=True)
    t0 = datetime.datetime.now()
    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)
    print(f"K: search={len(ks.search)}  eval_past={len(ks.eval_past)}  future={len(ks.future)}")

    land = cg.Landscape(ks, emb)                                   # what the GA sees
    land_ev = cg.Landscape(ks, emb, V_ref=ks.V_eval_past)          # held-out past
    land_fu = cg.Landscape(ks, emb, V_ref=ks.V_future)             # held-out future

    # independent lexical representation for a robustness check of out-of-sample novelty
    tfidf = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=2)
    X_ev = tfidf.fit_transform([cg.KnowledgeSpace.paper_text(p) for p in ks.eval_past])
    X_h = tfidf.transform(land.texts)
    N_tfidf = (1.0 - (X_h @ X_ev.T).max(axis=1).toarray().ravel()).reshape(land.shape)

    N_out = land_ev.N
    U_out = land_ev.U
    FS = 1.0 - land_fu.N                       # closeness of the nearest FUTURE paper
    Delta = land_ev.N - land_fu.N              # = maxsim(future) - maxsim(held-out past)
    F_flat = land.F.ravel()
    Nout_flat, Delta_flat = N_out.ravel(), Delta.ravel()

    def outcome(t):
        fl = land.flat(t)
        # novelty-matched null: Delta of all hypotheses with (almost) the same held-out novelty
        mask = np.abs(Nout_flat - Nout_flat[fl]) < MATCH_TOL
        return {
            "f_search": float(land.F[t]),
            "f_percentile": float((F_flat < land.F[t]).mean() * 100),
            "N_search": float(land.N[t]), "U_search": float(land.U[t]),
            "N_out": float(N_out[t]), "N_out_tfidf": float(N_tfidf[t]), "U_out": float(U_out[t]),
            "FS_future": float(FS[t]), "Delta": float(Delta[t]),
            "Delta_pct_matched": float((Delta_flat[mask] < Delta_flat[fl]).mean() * 100),
        }

    rows = []
    # ---- Exp. 1 / 2: search methods and ablations -----------------------------------------
    configs = [("GA", cg.run_ga, 0.6, 0.4), ("Random", cg.run_random, 0.6, 0.4),
               ("HillClimb", cg.run_hillclimb, 0.6, 0.4),
               ("GA-NoveltyOnly", cg.run_ga, 1.0, 0.0), ("GA-UtilityOnly", cg.run_ga, 0.0, 1.0)]
    traces = {}
    for name, fn, a, b in configs:
        land.set_weights(a, b)
        F_flat_cfg = land.F.ravel()
        opt = land.triples[int(F_flat_cfg.argmax())]
        for s in SEEDS:
            B = fn(land, s)
            t = B.best
            land.set_weights(0.6, 0.4)          # outcomes always reported on the main objective
            o = outcome(t)
            land.set_weights(a, b)
            rows.append({"method": name, "seed": s, "alpha": a, "beta": b,
                         "hypothesis": land.name(t), "M": land.M[t[0]], "P": land.P[t[1]],
                         "G": land.G[t[2]], "evals": B.used,
                         "found_cfg_optimum": t == opt, **o})
            if a == 0.6:
                traces.setdefault(name, []).append(B.trace)
            with open(os.path.join(LOGS, f"{name}_seed{s:02d}.json"), "w", encoding="utf-8") as f:
                json.dump({"method": name, "seed": s, "alpha": a, "beta": b,
                           "budget": cg.EVAL_BUDGET, "pop": cg.POPULATION_SIZE,
                           "generations": cg.GENERATION_COUNT, "elite": cg.N_ELITE,
                           "parent_pool": cg.PARENT_POOL, "p_mut": cg.MUTATION_RATE,
                           "best": land.name(t), "best_fitness_cfg": B.best_f,
                           "trace_best_so_far": B.trace, "outcomes": o}, f, indent=1)
    land.set_weights(0.6, 0.4)

    # ---- no-search references (n = 30 hypotheses each) -------------------------------------
    rng = random.Random(999)
    for s in SEEDS:                                 # a single uniformly drawn hypothesis
        t = cg._rand_triple(rng, land.shape)
        rows.append({"method": "Uniform(no search)", "seed": s, "hypothesis": land.name(t),
                     "M": land.M[t[0]], "P": land.P[t[1]], "G": land.G[t[2]], "evals": 1, **outcome(t)})
    typ_order = np.argsort(-land.maxsim_search)     # most "typical" = closest to existing papers
    for r, fl in enumerate(typ_order[:len(SEEDS)]):
        t = land.triples[int(fl)]
        rows.append({"method": "Typical-30", "seed": r + 1, "hypothesis": land.name(t),
                     "M": land.M[t[0]], "P": land.P[t[1]], "G": land.G[t[2]], "evals": 0, **outcome(t)})

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(RES, "runs.csv"), index=False, encoding="utf-8")

    # ---- statistics: GA vs every other condition, per metric, Holm-corrected ----------------
    brng = np.random.default_rng(2026)
    metrics = ["f_search", "f_percentile", "N_out", "N_out_tfidf", "U_out", "FS_future",
               "Delta", "Delta_pct_matched"]
    desc = []
    for m_ in df["method"].unique():
        sub = df[df.method == m_]
        for k in metrics:
            lo, hi = boot_ci(sub[k].values, brng)
            desc.append({"method": m_, "metric": k, "mean": sub[k].mean(), "sd": sub[k].std(ddof=1),
                         "median": sub[k].median(), "ci95_lo": lo, "ci95_hi": hi, "n": len(sub)})
    pd.DataFrame(desc).to_csv(os.path.join(RES, "stats_descriptive.csv"), index=False)

    tests = []
    ga = df[df.method == "GA"]
    for k in metrics:
        others = [m_ for m_ in df.method.unique() if m_ != "GA"]
        ps, recs = [], []
        for m_ in others:
            o = df[df.method == m_][k].values
            u, p = stats.mannwhitneyu(ga[k].values, o, alternative="two-sided")
            ps.append(p)
            recs.append({"metric": k, "comparison": f"GA vs {m_}", "U": u, "p": p,
                         "A12": a12(ga[k].values, o), "mean_GA": ga[k].mean(), "mean_other": o.mean()})
        for r_, pa in zip(recs, holm(np.array(ps))):
            r_["p_holm"] = pa
            tests.append(r_)
    pd.DataFrame(tests).to_csv(os.path.join(RES, "stats_tests.csv"), index=False)

    # ---- landscape-level correlations (all 2,700 hypotheses) --------------------------------
    corr = {
        "spearman_Nsearch_Nout": stats.spearmanr(land.N.ravel(), N_out.ravel())[0],
        "spearman_Nout_Ntfidf": stats.spearmanr(N_out.ravel(), N_tfidf.ravel())[0],
        "spearman_Nout_Delta": stats.spearmanr(N_out.ravel(), Delta.ravel())[0],
        "spearman_U_Delta": stats.spearmanr(land.U.ravel(), Delta.ravel())[0],
        "spearman_F_Delta": stats.spearmanr(land.F.ravel(), Delta.ravel())[0],
        "spearman_N_U": stats.spearmanr(land.N.ravel(), land.U.ravel())[0],
    }

    # ---- Exp. 3: corpus-size sensitivity ----------------------------------------------------
    sens = []
    full_rank_N = land.N.ravel()
    srng = np.random.default_rng(7)
    V3 = emb.encode([f"{t}. {s}" for t, s in ORIGINAL_THREE_PAPERS], "orig3")
    for n in [x for x in [3, 10, 30, 100, 300, 1000] if x < len(ks.search)] + [len(ks.search)]:
        reps = 1 if n == len(ks.search) else 10
        for r in range(reps):
            idx = srng.choice(len(ks.search), size=n, replace=False)
            Nn = 1.0 - (land.Z @ ks.V_search[idx].T).max(axis=1)
            sens.append({"n_papers": n, "rep": r, "source": "arXiv sample",
                         "N_mean": Nn.mean(), "N_sd": Nn.std(), "N_min": Nn.min(), "N_max": Nn.max(),
                         "spearman_vs_full": stats.spearmanr(Nn, full_rank_N)[0],
                         "spearman_Delta": stats.spearmanr(Nn, Delta_flat)[0]})
    N3 = 1.0 - (land.Z @ V3.T).max(axis=1)
    sens.append({"n_papers": 3, "rep": 0, "source": "original 3 papers",
                 "N_mean": N3.mean(), "N_sd": N3.std(), "N_min": N3.min(), "N_max": N3.max(),
                 "spearman_vs_full": stats.spearmanr(N3, full_rank_N)[0],
                 "spearman_Delta": stats.spearmanr(N3, Delta_flat)[0]})
    sens_df = pd.DataFrame(sens)
    sens_df.to_csv(os.path.join(RES, "sensitivity.csv"), index=False)

    # ---- summary ---------------------------------------------------------------------------
    gsub = df[df.method == "GA"]
    summary = {
        "corpus": {"search": len(ks.search), "eval_past": len(ks.eval_past), "future": len(ks.future)},
        "space_size": int(np.prod(land.shape)), "budget": cg.EVAL_BUDGET,
        "global_optimum": {"hypothesis": land.name(land.triples[int(F_flat.argmax())]),
                           "f": float(F_flat.max())},
        "landscape": {"F_mean": float(F_flat.mean()), "F_sd": float(F_flat.std()),
                      "N_mean": float(land.N.mean()), "U_mean": float(land.U.mean()),
                      "Delta_mean": float(Delta_flat.mean()), "Delta_sd": float(Delta_flat.std())},
        "correlations": corr,
        "optimum_hit_rate": df[df.method.isin(["GA", "Random", "HillClimb"])]
            .groupby("method")["found_cfg_optimum"].mean().to_dict(),
        "GA_distinct_best_hypotheses": int(gsub.hypothesis.nunique()),
        "GA_best_hypothesis_counts": gsub.hypothesis.value_counts().head(10).to_dict(),
        "runtime_s": (datetime.datetime.now() - t0).total_seconds(),
    }
    with open(os.path.join(RES, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=float)

    import sklearn, scipy, sentence_transformers, torch
    env = {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
           "pandas": pd.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__,
           "sentence_transformers": sentence_transformers.__version__, "torch": torch.__version__,
           "embed_model": cg.EMBED_MODEL, "seeds": SEEDS, "split_seed": cg.SPLIT_SEED,
           "run_at": t0.isoformat()}
    with open(os.path.join(RES, "environment.json"), "w") as f:
        json.dump(env, f, indent=1)

    # traces for the convergence figure
    np.save(os.path.join(RES, "traces.npy"), {k: np.array(v) for k, v in traces.items()},
            allow_pickle=True)
    print(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    main()
