# analyze_manuscript_experiment.py
#
# Analysis of Experiment 4 (controlled manuscript generation) and of the blinded expert ratings.
#
#   python analyze_manuscript_experiment.py hyp
#       Hypothesis-level outcome measures (Section 3.4) for the LLM-proposed hypotheses, compared with
#       the GA / random-search / uniform hypotheses of Experiment 2 (results/runs.csv).
#       -> results/controlled/hypothesis_level.csv, hypothesis_level_tests.csv
#
#   python analyze_manuscript_experiment.py ratings  ratings_R1.csv ratings_R2.csv [...]
#       Expert ratings (one CSV per rater, exported from 評価シート_R*.xlsx by collect_ratings.ps1),
#       merged with results/controlled/_KEY_do_not_share.csv.
#       -> results/controlled/ratings_summary.csv, ratings_tests.csv, ratings_reliability.csv

import glob
import json
import os
import sys
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
CTRL = os.path.join(RES, "controlled")
CRITERIA = ["originality", "soundness", "reproducibility", "significance"]
LABEL = {"ga": "GA", "random": "Random", "llm": "LLM-proposed"}


def a12(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    return ((x[:, None] > y[None, :]).sum() + 0.5 * (x[:, None] == y[None, :]).sum()) / (len(x) * len(y))


def holm(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    adj, run = np.empty(len(p)), 0.0
    for k, i in enumerate(order):
        run = max(run, (len(p) - k) * p[i]); adj[i] = min(1.0, run)
    return adj


def kripp_alpha_interval(units):
    vals, num = [], 0.0
    for u in units:
        u = [v for v in u if v == v]
        if len(u) < 2:
            continue
        num += sum((a - b) ** 2 for a, b in combinations(u, 2)) * 2 / (len(u) - 1)
        vals += u
    n = len(vals)
    if n < 2:
        return float("nan")
    de = sum((a - b) ** 2 for a, b in combinations(vals, 2)) * 2 / (n * (n - 1))
    return 1 - (num / n) / de if de > 0 else float("nan")


# ------------------------------------------------------------------ hypothesis level
def hyp():
    import creative_ga as cg
    from concepts import hypothesis_text
    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)

    def measures(hs):
        H = emb.encode([hypothesis_text(h["method"], h["problem"], h["goal"]) for h in hs])
        def link(V):
            P = [emb.encode([f"{h['method']} for {h['problem']}" for h in hs]),
                 emb.encode([f"{h['method']} for {h['goal']}" for h in hs]),
                 emb.encode([f"addressing {h['problem']} to improve {h['goal']}" for h in hs])]
            return np.mean([(X @ V.T).max(1) for X in P], axis=0)
        ms, me, mf = (H @ ks.V_search.T).max(1), (H @ ks.V_eval_past.T).max(1), (H @ ks.V_future.T).max(1)
        N, U = 1 - ms, link(ks.V_search)
        return pd.DataFrame({"N_search": N, "U_search": U, "f_search": 0.6 * N + 0.4 * U,
                             "N_out": 1 - me, "U_out": link(ks.V_eval_past), "FS_future": mf, "Delta": mf - me})

    llm = []
    for p in sorted(glob.glob(os.path.join(CTRL, "hypotheses", "llm_seed*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        llm.append({"seed": d["seed"], **d["hypothesis"]})
    df_llm = pd.concat([pd.DataFrame(llm), measures(llm)], axis=1)
    df_llm["method_cond"] = "LLM-proposed"
    runs = pd.read_csv(os.path.join(RES, "runs.csv"))
    keep = runs[runs.method.isin(["GA", "Random", "Uniform(no search)", "Typical-30"])].copy()
    keep["method_cond"] = keep["method"]
    cols = ["method_cond", "N_out", "U_out", "FS_future", "Delta", "f_search"]
    allh = pd.concat([keep[cols], df_llm[cols]], ignore_index=True)
    df_llm.to_csv(os.path.join(CTRL, "llm_hypotheses_measures.csv"), index=False, encoding="utf-8")
    summ = allh.groupby("method_cond")[cols[1:]].agg(["mean", "std", "count"]).round(3)
    summ.to_csv(os.path.join(CTRL, "hypothesis_level.csv"), encoding="utf-8")
    print(summ.to_string())
    tests = []
    for k in cols[1:]:
        recs, ps = [], []
        for other in ["GA", "Random", "Uniform(no search)", "Typical-30"]:
            x, y = df_llm[k].values, keep[keep.method_cond == other][k].values
            u, p = stats.mannwhitneyu(x, y, alternative="two-sided")
            recs.append({"metric": k, "comparison": f"LLM-proposed vs {other}", "mean_llm": x.mean(),
                         "mean_other": y.mean(), "A12": a12(x, y), "p": p}); ps.append(p)
        for r, pa in zip(recs, holm(ps)):
            r["p_holm"] = pa; tests.append(r)
    t = pd.DataFrame(tests).round(4)
    t.to_csv(os.path.join(CTRL, "hypothesis_level_tests.csv"), index=False)
    print(t.to_string())
    print("distinct LLM hypotheses:", df_llm[["method", "problem", "goal"]].drop_duplicates().shape[0], "of", len(df_llm))


# ------------------------------------------------------------------ manuscripts (descriptive)
def manuscripts():
    rows = []
    for p in sorted(glob.glob(os.path.join(CTRL, "logs", "*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        rows.append({"run_id": d["run_id"], "condition": d["condition"], "words": d["check"]["words"],
                     "missing_sections": len(d["check"]["missing_sections"]), "minutes": d["seconds"] / 60})
    df = pd.DataFrame(rows)
    print(df.groupby("condition")[["words", "missing_sections", "minutes"]].agg(["mean", "min", "max"]).round(1))
    return df


# ------------------------------------------------------------------ expert ratings
def ratings(files):
    key = pd.read_csv(os.path.join(CTRL, "_KEY_do_not_share.csv"))
    frames = []
    for i, f in enumerate(files, 1):
        d = pd.read_csv(f, encoding="utf-8-sig")
        d.columns = [c.strip().lower() for c in d.columns]
        if "rater" not in d.columns:
            d["rater"] = f"R{i}"
        frames.append(d)
    r = pd.concat(frames, ignore_index=True).merge(key[["code", "condition"]], on="code", how="inner")
    # human raters score 3 criteria (soundness, reproducibility, significance); the LLM judge also scores
    # originality. Only the criteria present in every input file are analysed.
    crit = [c for c in CRITERIA if c in r.columns and r[c].notna().any()]
    for c in crit:
        r[c] = pd.to_numeric(r[c], errors="coerce")
    raters = sorted(r.rater.unique())
    print(f"raters: {raters}; ratings: {len(r)}; missing scores: {int(r[crit].isna().sum().sum())}")

    rel = []
    for c in crit:
        units = r.groupby("code")[c].apply(list).tolist()
        row = {"criterion": c, "kripp_alpha_interval": kripp_alpha_interval(units)}
        if len(raters) == 2:      # agreement on the manuscripts rated by both raters (shared set)
            w = r.pivot_table(index="code", columns="rater", values=c).dropna()
            row["n_shared"] = len(w)
            row["spearman_R1_R2"] = stats.spearmanr(w[raters[0]], w[raters[1]])[0] if len(w) > 2 else float("nan")
            row["exact_agreement"] = float((w[raters[0]] == w[raters[1]]).mean())
            row["within_1_point"] = float(((w[raters[0]] - w[raters[1]]).abs() <= 1).mean())
            row["mean_abs_diff"] = float((w[raters[0]] - w[raters[1]]).abs().mean())
        rel.append(row)
    rel = pd.DataFrame(rel).round(3)
    rel.to_csv(os.path.join(CTRL, "ratings_reliability.csv"), index=False)
    print(rel.to_string())

    m = r.groupby(["code", "condition"])[crit].mean().reset_index()   # manuscript-level mean over raters
    m["overall"] = m[crit].mean(axis=1)
    rng = np.random.default_rng(0)
    summ = []
    for cond, g in m.groupby("condition"):
        for c in crit + ["overall"]:
            x = g[c].dropna().values
            b = rng.choice(x, (10000, len(x))).mean(1)
            summ.append({"condition": LABEL.get(cond, cond), "criterion": c, "mean": x.mean(), "sd": x.std(ddof=1),
                         "ci95_lo": np.percentile(b, 2.5), "ci95_hi": np.percentile(b, 97.5), "n": len(x)})
    summ = pd.DataFrame(summ).round(3)
    summ.to_csv(os.path.join(CTRL, "ratings_summary.csv"), index=False)
    print(summ.to_string())

    tests = []
    for c in crit + ["overall"]:
        groups = {k: g[c].dropna().values for k, g in m.groupby("condition")}
        kw = stats.kruskal(*groups.values())
        pairs = list(combinations(sorted(groups), 2))
        ps = [stats.mannwhitneyu(groups[a], groups[b], alternative="two-sided")[1] for a, b in pairs]
        for (a, b), p, pa in zip(pairs, ps, holm(ps)):
            tests.append({"criterion": c, "kruskal_H": kw.statistic, "kruskal_p": kw.pvalue,
                          "comparison": f"{LABEL.get(a, a)} vs {LABEL.get(b, b)}", "A12": a12(groups[a], groups[b]),
                          "p": p, "p_holm": pa})
    tests = pd.DataFrame(tests).round(4)
    tests.to_csv(os.path.join(CTRL, "ratings_tests.csv"), index=False)
    print(tests.to_string())


# ------------------------------------------------------------------ desktop judge (pairwise)
def bradley_terry(wins, codes, iters=1000):
    """MM algorithm for Bradley-Terry strengths; wins[(i, j)] = times i beat j."""
    s = {c: 1.0 for c in codes}
    for _ in range(iters):
        new = {}
        for i in codes:
            w_i = sum(v for (a, b), v in wins.items() if a == i)
            denom = 0.0
            for (a, b), v in wins.items():
                if i in (a, b):
                    j = b if a == i else a
                    denom += v / (s[i] + s[j])
            new[i] = (w_i + 0.5) / (denom + 1.0 / (s[i] + 1.0))     # weak prior keeps strengths finite
        tot = np.exp(np.mean(np.log(list(new.values()))))
        s = {k: v / tot for k, v in new.items()}
    return {k: float(np.log(v)) for k, v in s.items()}


def pairwise(result_dir):
    key = pd.read_csv(os.path.join(CTRL, "_KEY_do_not_share.csv"))
    cond = dict(zip(key.code, key.condition))
    d = pd.read_csv(os.path.join(result_dir, "pairwise_results.csv"), encoding="utf-8-sig")
    out = []
    for c in CRITERIA + ["overall"]:
        col = f"winner_{c}"
        # position consistency: same winner in both presentation orders
        both = d.pivot_table(index="pair_id", columns="order", values=col, aggfunc="first").dropna()
        consistent = float((both["AB"] == both["BA"]).mean()) if len(both) else float("nan")
        wins = {}
        for _, row in d.iterrows():
            a, b = row["shown_as_A"], row["shown_as_B"]
            w = row[col]; l = b if w == a else a
            wins[(w, l)] = wins.get((w, l), 0) + 1
        bt = bradley_terry(wins, sorted(cond))
        g = {k: [v for code, v in bt.items() if cond[code] == k] for k in sorted(set(cond.values()))}
        kw = stats.kruskal(*g.values())
        rec = {"criterion": c, "position_consistency": consistent, "kruskal_p": kw.pvalue}
        for k, v in g.items():
            rec[f"BT_mean_{LABEL.get(k, k)}"] = float(np.mean(v))
        for a, b in combinations(sorted(g), 2):
            rec[f"A12_{LABEL.get(a, a)}_vs_{LABEL.get(b, b)}"] = a12(g[a], g[b])
        out.append(rec)
    out = pd.DataFrame(out).round(3)
    out.to_csv(os.path.join(CTRL, f"pairwise_{os.path.basename(os.path.normpath(result_dir))}.csv"), index=False)
    print(out.to_string())


if __name__ == "__main__":
    if sys.argv[1:2] == ["hyp"]:
        hyp()
    elif sys.argv[1:2] == ["ratings"]:
        ratings(sys.argv[2:])
    elif sys.argv[1:2] == ["pairwise"]:
        pairwise(sys.argv[2])
    else:
        manuscripts()
