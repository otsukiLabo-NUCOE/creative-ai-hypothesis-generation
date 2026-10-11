# analyze_llm_robustness.py — analysis of the round-2 robustness experiments (pre-specified in
# Revision2/PREREGISTRATION_round2_experiments.md). For every LLM configuration (and, for reference, the GA and
# uniform selection of Experiment 2): diversity (mean pairwise cosine similarity), held-out novelty N_out,
# N_out (TF-IDF), FS, Delta, distinct hypotheses, share of the most frequent method, share of neuro-symbolic methods
# and of hallucination problems. Each LLM configuration is compared with the GA: diversity by a two-sided
# permutation test (20,000 permutations), N_out by a Mann-Whitney U test; Holm correction within each measure.
# Output: ../results/robustness/robustness_summary.csv
import glob
import json
import os

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_extraction.text import TfidfVectorizer

import creative_ga as cg
from concepts import hypothesis_text

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
N_PERM, SEED = 20000, 2026


def holm(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    run = 0.0
    for k, i in enumerate(order):
        run = max(run, (len(p) - k) * p[i])
        adj[i] = min(1.0, run)
    return adj


def load_sets():
    sets = {}
    r1 = sorted(glob.glob(os.path.join(RES, "controlled", "hypotheses", "llm_seed*.json")))
    sets["nemotron_P0_t0.7"] = [json.load(open(p, encoding="utf-8"))["hypothesis"] for p in r1]
    for d in sorted(glob.glob(os.path.join(RES, "robustness", "*"))):
        if os.path.isdir(d):
            hs = [json.load(open(p, encoding="utf-8"))["hypothesis"] for p in sorted(glob.glob(os.path.join(d, "seed*.json")))]
            sets[os.path.basename(d)] = [h for h in hs if h]
    return sets


def mean_pair(S, idx):
    sub = S[np.ix_(idx, idx)]
    return float(sub[np.triu_indices(len(idx), 1)].mean())


def main():
    rng = np.random.default_rng(SEED)
    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)
    tfidf = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=2)
    X_ev = tfidf.fit_transform([cg.KnowledgeSpace.paper_text(p) for p in ks.eval_past])
    runs = pd.read_csv(os.path.join(RES, "runs.csv"))

    groups = {}
    for name in ("GA", "Uniform(no search)"):
        sub = runs[runs.method == name].sort_values("seed")
        groups[name] = [{"method": m, "problem": p, "goal": g} for m, p, g in zip(sub.M, sub.P, sub.G)]
    groups.update(load_sets())

    def measures(hs):
        texts = [hypothesis_text(h["method"], h["problem"], h["goal"]) for h in hs]
        Z = emb.encode(texts)
        me, mf = (Z @ ks.V_eval_past.T).max(1), (Z @ ks.V_future.T).max(1)
        nt = 1 - (tfidf.transform(texts) @ X_ev.T).max(axis=1).toarray().ravel()
        return Z, 1 - me, nt, mf, mf - me

    data = {k: measures(v) for k, v in groups.items()}
    Zga, Nga = data["GA"][0], data["GA"][1]
    rows = []
    for name, hs in groups.items():
        Z, nout, nt, fs, dl = data[name]
        S = Z @ Z.T
        meth = pd.Series([h["method"] for h in hs]).value_counts()
        row = {"config": name, "n": len(hs), "distinct": len({(h["method"], h["problem"], h["goal"]) for h in hs}),
               "mean_pairwise_cos": mean_pair(S, np.arange(len(hs))), "N_out": nout.mean(), "N_out_tfidf": nt.mean(),
               "FS": fs.mean(), "Delta": dl.mean(), "share_top_method": meth.iloc[0] / len(hs),
               "top_method": meth.index[0],
               "share_neuro_symbolic": np.mean(["neuro-symbolic" in h["method"].lower() or "neurosymbolic" in h["method"].lower() for h in hs]),
               "share_hallucination": np.mean(["halluc" in (h["problem"] + " " + h["goal"]).lower() for h in hs])}
        if name not in ("GA", "Uniform(no search)"):
            Zall = np.vstack([Zga, Z])
            Sall = Zall @ Zall.T
            n1 = len(Zga)
            obs = mean_pair(Sall, np.arange(n1, len(Zall))) - mean_pair(Sall, np.arange(n1))
            perm = np.empty(N_PERM)
            for k in range(N_PERM):
                pi = rng.permutation(len(Zall))
                perm[k] = mean_pair(Sall, pi[n1:]) - mean_pair(Sall, pi[:n1])
            row["p_div_vs_GA"] = float((np.abs(perm) >= abs(obs) - 1e-12).mean())
            row["p_Nout_vs_GA"] = float(stats.mannwhitneyu(nout, Nga, alternative="two-sided").pvalue)
            row["A12_Nout_vs_GA"] = float(stats.mannwhitneyu(nout, Nga).statistic / (len(nout) * len(Nga)))
        rows.append(row)
    d = pd.DataFrame(rows)
    m = d.p_div_vs_GA.notna()
    d.loc[m, "p_holm_div"] = holm(d.loc[m, "p_div_vs_GA"])
    d.loc[m, "p_holm_Nout"] = holm(d.loc[m, "p_Nout_vs_GA"])
    d = d.round(4)
    os.makedirs(os.path.join(RES, "robustness"), exist_ok=True)
    d.to_csv(os.path.join(RES, "robustness", "robustness_summary.csv"), index=False)
    cols = ["config", "n", "distinct", "mean_pairwise_cos", "p_holm_div", "N_out", "A12_Nout_vs_GA", "p_holm_Nout",
            "N_out_tfidf", "FS", "share_top_method", "share_neuro_symbolic", "share_hallucination"]
    print(d[cols].to_string())
    for name in groups:
        if "scope" in name:
            print(name, "top method:", d.set_index("config").loc[name, "top_method"])


if __name__ == "__main__":
    main()
