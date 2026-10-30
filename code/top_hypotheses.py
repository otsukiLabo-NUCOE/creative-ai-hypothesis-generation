import numpy as np
import creative_ga as cg

emb = cg.Embedder()
ks = cg.KnowledgeSpace.build(emb)
land = cg.Landscape(ks, emb)
print("knowledge space (search partition):", len(ks.search), "papers")

print("--- GA (seed 1-5)")
for seed in range(1, 6):
    t = cg.run_ga(land, seed).best
    print(f"seed={seed}: {land.name(t)}  N={float(land.N[t]):.3f} U={float(land.U[t]):.3f} f={float(land.F[t]):.3f}")

print("--- top 10 of all combinations")
for idx in np.argsort(-land.F.ravel())[:10]:
    t = tuple(int(i) for i in np.unravel_index(idx, land.shape))
    print(f"{land.name(t)}  N={land.N[t]:.3f} U={land.U[t]:.3f} f={land.F[t]:.3f}")
