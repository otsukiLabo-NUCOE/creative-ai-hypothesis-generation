# make_figures.py — figures of the revised manuscript, drawn only from ../results/*.csv|npy
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e6e5e0"
COL = {"GA": "#2a78d6", "Random": "#eb6834", "HillClimb": "#1baf7a",
       "GA-NoveltyOnly": "#eda100", "GA-UtilityOnly": "#e87ba4",
       "Uniform(no search)": "#4a3aa7", "Typical-30": "#e34948"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6})


def fig_convergence():
    tr = np.load(os.path.join(RES, "traces.npy"), allow_pickle=True).item()
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    for name in ["GA", "HillClimb", "Random"]:
        a = tr[name]
        x = np.arange(1, a.shape[1] + 1)
        m = a.mean(0)
        se = a.std(0, ddof=1) / np.sqrt(a.shape[0])
        ax.plot(x, m, color=COL[name], lw=2, label=name)
        ax.fill_between(x, m - 1.96 * se, m + 1.96 * se, color=COL[name], alpha=0.18, lw=0)
    summ = pd.read_json(os.path.join(RES, "summary.json"), typ="series")
    ax.axhline(summ["global_optimum"]["f"], color=MUTED, lw=1, ls="--")
    ax.text(5, summ["global_optimum"]["f"], "global optimum (exhaustive)", va="bottom",
            color=MUTED, fontsize=7.5)
    ax.set_xlabel("Fitness evaluations")
    ax.set_ylabel("Best fitness so far, f(h)")
    ax.legend(frameon=False, loc="lower right")
    ax.set_xlim(1, 215)
    fig.tight_layout()
    fig.savefig(os.path.join(RES, "fig_convergence.png"), dpi=300)


def fig_outcomes():
    df = pd.read_csv(os.path.join(RES, "runs.csv"))
    order = ["GA", "Random", "HillClimb", "GA-NoveltyOnly", "GA-UtilityOnly",
             "Uniform(no search)", "Typical-30"]
    panels = [("N_out", "Held-out novelty  $N_{out}$"), ("U_out", "Held-out link support  $U_{out}$"),
              ("Delta", "Anticipation  $\\Delta$ (future − past)")]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    rng = np.random.default_rng(0)
    for ax, (k, title) in zip(axes, panels):
        data = [df[df.method == m][k].values for m in order]
        bp = ax.boxplot(data, vert=True, widths=0.55, patch_artist=True, showfliers=False,
                        medianprops=dict(color=INK, lw=1.2), whiskerprops=dict(color=MUTED),
                        capprops=dict(color=MUTED))
        for patch, m in zip(bp["boxes"], order):
            patch.set_facecolor(COL[m]); patch.set_alpha(0.35); patch.set_edgecolor(COL[m])
        for i, (d, m) in enumerate(zip(data, order), 1):
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(d)), d, s=9, color=COL[m],
                       edgecolor="white", linewidth=0.4, zorder=3)
        ax.set_xticks(range(1, len(order) + 1))
        ax.set_xticklabels(["GA", "Random", "Hill climb", "GA N-only", "GA U-only",
                            "Uniform (no search)", "Typical-30"], fontsize=7, rotation=40,
                           ha="right", rotation_mode="anchor")
        ax.set_title(title, fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(RES, "fig_outcomes.png"), dpi=300)


def fig_sensitivity():
    s = pd.read_csv(os.path.join(RES, "sensitivity.csv"))
    arx = s[s.source == "arXiv sample"].groupby("n_papers").agg(
        sd=("N_sd", "mean"), sd_e=("N_sd", "std"), rho=("spearman_vs_full", "mean"),
        rho_e=("spearman_vs_full", "std"), mx=("N_max", "mean"), mn=("N_min", "mean")).reset_index()
    o3 = s[s.source == "original 3 papers"].iloc[0]
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.1))
    ax = axes[0]
    ax.errorbar(arx.n_papers, arx.rho, yerr=arx.rho_e.fillna(0), color=COL["GA"], lw=2,
                marker="o", ms=5, capsize=2)
    ax.scatter([3], [o3.spearman_vs_full], marker="s", s=40, color=COL["Random"], zorder=4)
    ax.annotate("original 3 papers", (3, o3.spearman_vs_full), xytext=(6, -2),
                textcoords="offset points", fontsize=7.5, color=INK2)
    ax.set_xscale("log"); ax.set_xlabel("Papers in knowledge space (log)")
    ax.set_ylabel("Spearman ρ with full-corpus novelty"); ax.set_title("Ranking agreement", fontsize=9)
    ax = axes[1]
    ax.fill_between(arx.n_papers, arx.mn, arx.mx, color=COL["GA"], alpha=0.15, lw=0)
    ax.plot(arx.n_papers, arx.mx, color=COL["GA"], lw=1, ls="--")
    ax.plot(arx.n_papers, arx.mn, color=COL["GA"], lw=1, ls="--")
    ax.plot(arx.n_papers, (arx.mx + arx.mn) / 2, color=COL["GA"], lw=0)
    ax.vlines([3], o3.N_min, o3.N_max, color=COL["Random"], lw=3)
    ax.annotate("original 3 papers", (3, o3.N_max), xytext=(6, 2), textcoords="offset points",
                fontsize=7.5, color=INK2)
    ax.set_xscale("log"); ax.set_xlabel("Papers in knowledge space (log)")
    ax.set_ylabel("Novelty N(h): min–max over 2,700 h"); ax.set_title("Range of the novelty score", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(RES, "fig_sensitivity.png"), dpi=300)


if __name__ == "__main__":
    fig_convergence(); fig_outcomes(); fig_sensitivity()
    print("figures written to", RES)
