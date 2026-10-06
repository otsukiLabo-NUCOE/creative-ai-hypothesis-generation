# link_examples.py — examples of literature support for pairwise links (Table 6 of the revised
# manuscript): the Method-Problem links with the highest and lowest support in K_search, together
# with the nearest supporting paper.
import os

import numpy as np
import pandas as pd

import creative_ga as cg

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)
    C = ks.concepts
    pairs = [(mm, pp) for mm in C["Method"] for pp in C["Problem"]]
    V = emb.encode([f"{a} for {b}" for a, b in pairs], "mp")
    S = V @ ks.V_search.T
    best, arg = S.max(1), S.argmax(1)
    order = np.argsort(-best)
    rows = []
    for tag, idxs in (("highest", order[:3]), ("lowest", order[-3:][::-1])):
        for i in idxs:
            rows.append({"support": tag, "link": f"{pairs[i][0]} – {pairs[i][1]}",
                         "s": round(float(best[i]), 3), "nearest_paper": ks.search[int(arg[i])]["title"]})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(HERE, "..", "results", "link_examples.csv"), index=False, encoding="utf-8")
    print(df.to_string())


if __name__ == "__main__":
    main()
