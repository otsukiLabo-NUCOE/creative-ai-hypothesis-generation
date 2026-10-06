# analyze_hypothesis_eval.py — Experiment 5: blinded rankings of hypothesis triplets (humans and LLM judge)
#
#   python analyze_hypothesis_eval.py <ratings_hyp_R1.csv> <ratings_hyp_R2.csv> [--llm <hypothesis_rankings.csv>]
#
# Each rating row: rater, tid, most_useful, least_useful, most_novel, least_novel (letters A/B/C).
# Letters are mapped to sources (ga / random / llm) with results/hypothesis_eval/_TRIPLET_KEY_do_not_share.csv.
# Rank within a triplet: best = 1, worst = 3, the remaining one = 2.
# Outputs: results/hypothesis_eval/human_rank_summary.csv, human_rank_tests.csv, agreement.csv (and LLM files)
import os
import sys
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "hypothesis_eval")
SOURCES = ["ga", "random", "llm"]
LABEL = {"ga": "GA", "random": "Random", "llm": "LLM-proposed"}
CRITS = {"usefulness": ("most_useful", "least_useful"), "novelty": ("most_novel", "least_novel")}


def holm(p):
    p = np.asarray(p, float); order = np.argsort(p); adj = np.empty(len(p)); run = 0.0
    for k, i in enumerate(order):
        run = max(run, (len(p) - k) * p[i]); adj[i] = min(1.0, run)
    return adj


def ranks(df, key):
    """long table: rater, tid, letter, source, criterion, rank"""
    rows = []
    for _, r in df.iterrows():
        k = key.loc[r["tid"]]
        for crit, (best, worst) in CRITS.items():
            b, w = str(r[best]).strip(), str(r[worst]).strip()
            if b not in "ABC" or w not in "ABC" or b == w or not b or not w:
                continue
            for letter in "ABC":
                rk = 1 if letter == b else 3 if letter == w else 2
                rows.append({"rater": r["rater"], "tid": r["tid"], "letter": letter, "hid": k[letter],
                             "source": k["source_" + letter], "criterion": crit, "rank": rk})
    return pd.DataFrame(rows)


def kripp_interval(units):
    vals, num = [], 0.0
    for u in units:
        if len(u) < 2:
            continue
        num += sum((a - b) ** 2 for a, b in combinations(u, 2)) * 2 / (len(u) - 1); vals += u
    n = len(vals)
    de = sum((a - b) ** 2 for a, b in combinations(vals, 2)) * 2 / (n * (n - 1)) if n > 1 else 0
    return 1 - (num / n) / de if de > 0 else float("nan")


def compare(L, tag):
    summ, tests = [], []
    for crit in CRITS:
        d = L[L.criterion == crit]
        per = d.groupby(["tid", "source"])["rank"].mean().unstack()          # mean over raters per triplet
        for s in SOURCES:
            summ.append({"who": tag, "criterion": crit, "source": LABEL[s], "mean_rank": per[s].mean(),
                         "share_ranked_best": float((d[d.source == s]["rank"] == 1).mean()),
                         "share_ranked_worst": float((d[d.source == s]["rank"] == 3).mean()), "n_triplets": len(per)})
        fr = stats.friedmanchisquare(*[per[s] for s in SOURCES])
        pairs = list(combinations(SOURCES, 2))
        ps, recs = [], []
        for a, b in pairs:
            diff = per[a] - per[b]
            w = stats.wilcoxon(per[a], per[b], zero_method="zsplit") if diff.abs().sum() > 0 else None
            ps.append(w.pvalue if w else 1.0)
            recs.append({"who": tag, "criterion": crit, "comparison": f"{LABEL[a]} vs {LABEL[b]}",
                         "friedman_chi2": fr.statistic, "friedman_p": fr.pvalue,
                         "share_triplets_a_above_b": float((per[a] < per[b]).mean()), "p": ps[-1]})
        for r_, pa in zip(recs, holm(ps)):
            r_["p_holm"] = pa; tests.append(r_)
    return pd.DataFrame(summ).round(3), pd.DataFrame(tests).round(4)


def agreement(L, tag):
    rows = []
    for crit in CRITS:
        d = L[L.criterion == crit]
        raters = sorted(d.rater.unique())
        units = d.groupby(["tid", "letter"])["rank"].apply(list).tolist()
        row = {"who": tag, "criterion": crit, "raters": len(raters), "kripp_alpha_interval": kripp_interval(units)}
        if len(raters) >= 2:
            best = d[d["rank"] == 1].pivot_table(index="tid", columns="rater", values="letter", aggfunc="first").dropna()
            worst = d[d["rank"] == 3].pivot_table(index="tid", columns="rater", values="letter", aggfunc="first").dropna()
            row["same_best_share"] = float((best.nunique(axis=1) == 1).mean())
            row["same_worst_share"] = float((worst.nunique(axis=1) == 1).mean())
            taus = []
            for tid, g in d.groupby("tid"):
                piv = g.pivot_table(index="letter", columns="rater", values="rank")
                if piv.shape[1] >= 2 and piv.notna().all().all():
                    taus.append(np.mean([stats.kendalltau(piv[a], piv[b])[0] for a, b in combinations(piv.columns, 2)]))
            row["mean_kendall_tau"] = float(np.mean(taus)) if taus else float("nan")
            row["chance_same_best"] = 1 / 3
        rows.append(row)
    return pd.DataFrame(rows).round(3)


def main():
    args = sys.argv[1:]
    llm_file = None
    if "--llm" in args:
        i = args.index("--llm"); llm_file = args[i + 1]; args = args[:i] + args[i + 2:]
    key = pd.read_csv(os.path.join(OUT, "_TRIPLET_KEY_do_not_share.csv")).set_index("tid")
    human = pd.concat([pd.read_csv(f, encoding="utf-8-sig") for f in args], ignore_index=True) if args else None
    results = {}
    if human is not None and len(human):
        H = ranks(human, key)
        s, t = compare(H, "human"); a = agreement(H, "human")
        results.update(human_rank_summary=s, human_rank_tests=t, human_agreement=a)
    if llm_file:
        llm = pd.read_csv(llm_file, encoding="utf-8-sig")
        Lm = ranks(llm, key)
        s, t = compare(Lm, "LLM"); a = agreement(Lm, "LLM (orders)")
        results.update(llm_rank_summary=s, llm_rank_tests=t, llm_order_consistency=a)
        if human is not None and len(human):
            hm = H.groupby(["hid", "criterion"])["rank"].mean()
            lm = Lm.groupby(["hid", "criterion"])["rank"].mean()
            j = pd.concat([hm.rename("human"), lm.rename("llm")], axis=1).dropna().reset_index()
            results["human_llm_agreement"] = pd.DataFrame(
                [{"criterion": c, "spearman_human_vs_llm": stats.spearmanr(g.human, g.llm)[0], "n_items": len(g)}
                 for c, g in j.groupby("criterion")]).round(3)
    pd.set_option("display.width", 220)
    for name, df in results.items():
        df.to_csv(os.path.join(OUT, name + ".csv"), index=False)
        print(f"== {name}\n{df.to_string()}\n")


if __name__ == "__main__":
    main()
