# llm_hypothesis_metrics.py
# Completes the Experiment-2 outcome measures for the 30 LLM-proposed hypotheses (same definitions as
# run_experiments.py: N_out, N_out^TF-IDF, U_out, FS, Delta, novelty-matched Delta percentile) and computes the
# diversity of the hypotheses selected by each condition (mean pairwise cosine similarity, distinct count,
# share of the most frequent method).  Output: ../results/llm_hypothesis_metrics.csv, ../results/diversity.csv
import glob
import json
import os

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

import creative_ga as cg
from concepts import hypothesis_text

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
MATCH_TOL = 0.01


def main():
    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)
    land = cg.Landscape(ks, emb)
    land_ev = cg.Landscape(ks, emb, V_ref=ks.V_eval_past)
    land_fu = cg.Landscape(ks, emb, V_ref=ks.V_future)
    Nout_flat = land_ev.N.ravel()
    Delta_flat = (land_ev.N - land_fu.N).ravel()
    tfidf = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=2)
    X_ev = tfidf.fit_transform([cg.KnowledgeSpace.paper_text(p) for p in ks.eval_past])

    llm = [json.load(open(p, encoding="utf-8"))["hypothesis"]
           for p in sorted(glob.glob(os.path.join(RES, "controlled", "hypotheses", "llm_seed*.json")))]
    texts = [hypothesis_text(h["method"], h["problem"], h["goal"]) for h in llm]
    Z = emb.encode(texts)

    def link(V):
        P = [emb.encode([f"{h['method']} for {h['problem']}" for h in llm]),
             emb.encode([f"{h['method']} for {h['goal']}" for h in llm]),
             emb.encode([f"addressing {h['problem']} to improve {h['goal']}" for h in llm])]
        return np.mean([(X @ V.T).max(1) for X in P], axis=0)

    ms, me, mf = (Z @ ks.V_search.T).max(1), (Z @ ks.V_eval_past.T).max(1), (Z @ ks.V_future.T).max(1)
    N, U = 1 - ms, link(ks.V_search)
    df = pd.DataFrame({"method": [h["method"] for h in llm], "f_search": 0.6 * N + 0.4 * U,
                       "N_out": 1 - me, "N_out_tfidf": 1 - (tfidf.transform(texts) @ X_ev.T).max(axis=1).toarray().ravel(),
                       "U_out": link(ks.V_eval_past), "FS_future": mf, "Delta": mf - me})
    df["Delta_pct_matched"] = [float((Delta_flat[np.abs(Nout_flat - n) < MATCH_TOL] < d).mean() * 100)
                               if (np.abs(Nout_flat - n) < MATCH_TOL).any() else np.nan
                               for n, d in zip(df.N_out, df.Delta)]
    df.to_csv(os.path.join(RES, "llm_hypothesis_metrics.csv"), index=False)
    cols = ["f_search", "N_out", "N_out_tfidf", "U_out", "FS_future", "Delta", "Delta_pct_matched"]
    print(df[cols].agg(["mean", "std"]).round(3).to_string())
    print("matched-percentile available for", df.Delta_pct_matched.notna().sum(), "of 30")

    runs = pd.read_csv(os.path.join(RES, "runs.csv"))
    rows = []

    def div(name, hs):
        Zh = emb.encode([hypothesis_text(*h) for h in hs])
        S = Zh @ Zh.T
        iu = np.triu_indices(len(hs), 1)
        meth = pd.Series([h[0] for h in hs]).value_counts()
        rows.append({"condition": name, "n": len(hs), "distinct": len(set(hs)), "mean_pairwise_cos": float(S[iu].mean()),
                     "most_frequent_method": meth.index[0], "share_most_frequent_method": float(meth.iloc[0] / len(hs))})

    for name in ["GA", "Random", "HillClimb", "Uniform(no search)", "Typical-30"]:
        sub = runs[runs.method == name]
        div(name, list(zip(sub.M, sub.P, sub.G)))
    div("LLM-proposed", [(h["method"], h["problem"], h["goal"]) for h in llm])
    neuro = sum("neuro-symbolic" in h["method"].lower() for h in llm)
    d = pd.DataFrame(rows).round(3)
    d.to_csv(os.path.join(RES, "diversity.csv"), index=False)
    print(d.to_string())
    print("LLM methods containing 'neuro-symbolic':", neuro, "/ 30;  mentioning hallucination:",
          sum("halluc" in (h["problem"] + h["goal"]).lower() for h in llm))


if __name__ == "__main__":
    main()
