# pairwise_consistency.py — robustness check for the pairwise LLM-judge comparisons of Experiment 4.
# A pair counts as a "consistent" judgment when the same manuscript wins in both presentation orders; pairs whose
# winner flips with the order are attributed to position bias. For each criterion: share of consistent pairs,
# consistent wins by hypothesis source, and an exact binomial test per source pair on the consistent decisions.
#   python pairwise_consistency.py <result_dir containing pairwise_results.csv>
# Output: ../results/controlled/pairwise_consistent_<model>.csv
import os
import sys
from itertools import combinations

import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.join(HERE, "..", "results", "controlled")
CRITERIA = ["originality", "soundness", "reproducibility", "significance", "overall"]
LABEL = {"ga": "GA", "random": "Random", "llm": "LLM-proposed"}


def main(result_dir):
    key = pd.read_csv(os.path.join(CTRL, "_KEY_do_not_share.csv"))
    cond = dict(zip(key.code, key.condition))
    d = pd.read_csv(os.path.join(result_dir, "pairwise_results.csv"), encoding="utf-8-sig")
    rows = []
    for c in CRITERIA:
        piv = d.pivot_table(index="pair_id", columns="order", values=f"winner_{c}", aggfunc="first").dropna()
        first = d[d.order == "AB"].set_index("pair_id")
        cons = piv[piv.AB == piv.BA]
        wins = {}
        for pid, r in cons.iterrows():
            a, b = first.loc[pid, "shown_as_A"], first.loc[pid, "shown_as_B"]
            w = r.AB
            l = b if w == a else a
            ca, cb = cond[w], cond[l]
            if ca != cb:
                wins[(ca, cb)] = wins.get((ca, cb), 0) + 1
        rec = {"criterion": c, "pairs": len(piv), "consistent_pairs": len(cons),
               "consistent_share": round(len(cons) / len(piv), 3) if len(piv) else float("nan")}
        for s1, s2 in combinations(sorted(set(cond.values())), 2):
            w1, w2 = wins.get((s1, s2), 0), wins.get((s2, s1), 0)
            p = stats.binomtest(w1, w1 + w2, 0.5).pvalue if w1 + w2 else float("nan")
            rec[f"{LABEL[s1]}_beats_{LABEL[s2]}"] = w1
            rec[f"{LABEL[s2]}_beats_{LABEL[s1]}"] = w2
            rec[f"p_{LABEL[s1]}_vs_{LABEL[s2]}"] = round(p, 4)
        rows.append(rec)
    out = pd.DataFrame(rows)
    name = os.path.basename(os.path.normpath(result_dir))
    out.to_csv(os.path.join(CTRL, f"pairwise_consistent_{name}.csv"), index=False)
    print(out.T.to_string())


if __name__ == "__main__":
    main(sys.argv[1])
