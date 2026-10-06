# validate_novelty_openreview.py
#
# Proposal 3: external validation of the automated novelty metric against expert peer-review judgments.
# Data: ReviewArena (Hugging Face: Samarth0710/reviewarena, CC BY 4.0), ICLR split, collected from OpenReview.
# In this dataset ICLR 2024-2026 contain accepted papers only (with per-review contribution / soundness /
# presentation / rating scores), and ICLR 2020-2023 contain accepted AND rejected papers (rating only).
# No year has an explicit "originality" score; "contribution" is the closest available construct.
#
#   (A) contribution vs novelty : ICLR 2024 and ICLR 2025 (replication), accepted papers only
#       (range-restricted -> correlations are attenuated)
#   (B) rating and acceptance vs novelty : ICLR 2023 (accepted + rejected; full quality range)
#
# Instrument (identical to the paper): N = 1 - max cosine similarity (all-MiniLM-L6-v2) between a text and a
# reference corpus of PRIOR literature, i.e. dated before the year's submission deadline:
#   ref "arXiv"         : the paper's own arXiv knowledge space (Section 3.1), restricted to the cutoff
#   ref "arXiv+ICLR"    : the above + all earlier ICLR papers in the dataset
# Text granularity: title+abstract, title only, first sentence of the abstract (closest to a hypothesis).
#
# Output: ../results/openreview_validation.csv, ../results/openreview_quintiles.csv

import glob
import json
import os
import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy import stats

import creative_ga as cg

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "reviewarena")
RES = os.path.join(HERE, "..", "results")
DEADLINES = {2023: "2022-09-28", 2024: "2023-09-28", 2025: "2024-10-01"}
N_BOOT = 2000


def num(v):
    m = re.match(r"\s*(\d+(\.\d+)?)", str(v))
    return float(m.group(1)) if m else np.nan


def load():
    cols = ["year", "track", "title", "abstract", "decision", "reviews_json"]
    df = pd.concat([pq.read_table(f, columns=cols).to_pandas()
                    for f in sorted(glob.glob(os.path.join(DATA, "iclr-*.parquet")))], ignore_index=True)
    df["year"] = df["year"].astype(int)
    df = df[(df["track"] == "main") & df["abstract"].fillna("").str.len().gt(50)].reset_index(drop=True)
    revs = df["reviews_json"].apply(lambda s: json.loads(s) if isinstance(s, str) else [])
    for k in ("contribution", "soundness", "presentation", "rating"):
        df[k] = revs.apply(lambda rv: np.nanmean([num(r.get(k)) for r in rv]) if rv and
                           any(np.isfinite(num(r.get(k))) for r in rv) else np.nan)
    df["accepted"] = df["decision"].fillna("").str.startswith("Accept").astype(int)
    return df


def first_sentence(t):
    s = re.split(r"(?<=[.!?])\s+", str(t).strip())
    return s[0] if s else str(t)


def spearman_ci(x, y, rng):
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    rho, p = stats.spearmanr(x, y)
    idx = np.arange(len(x))
    boots = [stats.spearmanr(x[b], y[b])[0] for b in (rng.choice(idx, len(idx)) for _ in range(N_BOOT))]
    return rho, p, np.percentile(boots, 2.5), np.percentile(boots, 97.5), len(x)


def main():
    df = load()
    emb = cg.Embedder()
    corpus = cg.load_corpus()
    past = [p for p in corpus if p["window"] == "past"]
    V_past = emb.encode([f"{p['title']}. {p['abstract']}" for p in past], "orv_arxiv_past")
    past_dates = np.array([p["date"] for p in past])
    V_iclr = emb.encode([f"{t}. {a}" for t, a in zip(df["title"], df["abstract"])], "orv_iclr_all")
    rng = np.random.default_rng(0)
    rows, quint = [], []
    for year, targets in ((2024, ["contribution", "soundness", "rating"]),
                          (2025, ["contribution", "soundness", "rating"]),
                          (2023, ["rating", "accepted"])):
        cur = df[df["year"] == year].reset_index(drop=True)
        cur_idx = df.index[df["year"] == year].to_numpy()
        prior_iclr = df.index[df["year"] < year].to_numpy()
        V_arx = V_past[past_dates < DEADLINES[year]]
        refs = {"arXiv": V_arx, "arXiv+ICLR": np.vstack([V_arx, V_iclr[prior_iclr]])}
        Z = {"title+abstract": V_iclr[cur_idx],
             "title": emb.encode(list(cur["title"]), f"orv_title_{year}"),
             "first sentence": emb.encode([first_sentence(a) for a in cur["abstract"]], f"orv_first_{year}")}
        print(f"ICLR {year}: {len(cur)} papers (accepted {cur['accepted'].sum()}); prior arXiv {len(V_arx)}, "
              f"prior ICLR {len(prior_iclr)}", flush=True)
        for rname, V in refs.items():
            for tname, z in Z.items():
                N = 1 - (z @ V.T).max(axis=1)
                for t in targets:
                    rho, p, lo, hi, n = spearman_ci(N, cur[t].to_numpy(dtype=float), rng)
                    rec = {"year": year, "reference": rname, "text": tname, "target": t, "n": n,
                           "spearman_rho": rho, "p": p, "ci95_lo": lo, "ci95_hi": hi}
                    if t == "accepted":
                        a = N[cur["accepted"] == 1]; r_ = N[cur["accepted"] == 0]
                        rec["AUC_novelty_predicts_accept"] = stats.mannwhitneyu(a, r_).statistic / (len(a) * len(r_))
                    rows.append(rec)
                if rname == "arXiv+ICLR" and tname == "title+abstract":
                    q = pd.qcut(N, 5, labels=[1, 2, 3, 4, 5])
                    g = cur.assign(N_quintile=q).groupby("N_quintile", observed=True)[targets].mean()
                    g.insert(0, "year", year)
                    quint.append(g.reset_index())
    out = pd.DataFrame(rows).round(4)
    out.to_csv(os.path.join(RES, "openreview_validation.csv"), index=False)
    pd.concat(quint).round(3).to_csv(os.path.join(RES, "openreview_quintiles.csv"), index=False)
    pd.set_option("display.width", 220)
    print(out.to_string())
    print(pd.concat(quint).round(3).to_string())


if __name__ == "__main__":
    main()
