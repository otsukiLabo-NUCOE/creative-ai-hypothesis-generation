# F1-2.py  (revised, Revision 1)
#
# The previous version plotted HARD-CODED novelty/utility values (A=1.00/0.50, B=0.89/0.82,
# C=0.85/0.89) that were not produced by any measurement; it is withdrawn and none of its numbers
# appears in the revised manuscript.
#
# This version computes the novelty-utility trade-off (and its harmonic mean, "F1") from the
# measured held-out outcomes in ../results/runs.csv (produced by run_experiments.py). Because N_out
# and U_out live on different numeric ranges, both are min-max normalised over all rows of
# runs.csv before the harmonic mean is taken.

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
COL = {"GA": "#2a78d6", "Random": "#eb6834", "HillClimb": "#1baf7a",
       "GA-NoveltyOnly": "#eda100", "GA-UtilityOnly": "#e87ba4",
       "Uniform(no search)": "#4a3aa7", "Typical-30": "#e34948"}


def f1(n, u):
    return 0.0 if n + u == 0 else 2 * n * u / (n + u)


def main():
    df = pd.read_csv(os.path.join(RES, "runs.csv"))
    lo_n, hi_n = df.N_out.min(), df.N_out.max()
    lo_u, hi_u = df.U_out.min(), df.U_out.max()
    df["N_norm"] = (df.N_out - lo_n) / (hi_n - lo_n)
    df["U_norm"] = (df.U_out - lo_u) / (hi_u - lo_u)
    df["F1"] = [f1(n, u) for n, u in zip(df.N_norm, df.U_norm)]
    tab = df.groupby("method")[["N_out", "U_out", "N_norm", "U_norm", "F1"]].mean().round(3)
    print(tab.to_string())
    tab.to_csv(os.path.join(RES, "novelty_utility_f1.csv"))

    fig, ax = plt.subplots(figsize=(5.4, 4))
    for m, sub in df.groupby("method"):
        ax.scatter(sub.N_out, sub.U_out, s=14, alpha=0.5, color=COL.get(m, "#898781"), lw=0)
        ax.scatter(sub.N_out.mean(), sub.U_out.mean(), s=70, color=COL.get(m, "#898781"),
                   edgecolor="white", lw=1.5, zorder=4, label=m)
    ax.set_xlabel("Held-out novelty  N_out")
    ax.set_ylabel("Held-out link support  U_out")
    ax.legend(frameon=False, fontsize=7, loc="best")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(RES, "fig_novelty_utility.png"), dpi=300)


if __name__ == "__main__":
    main()
