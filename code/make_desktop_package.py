# make_desktop_package.py
#
# Builds ../desktop_judge_package/, a self-contained folder that runs the blinded LLM-as-judge
# evaluation on a separate GPU machine WITHOUT Python or Claude (PowerShell + llama.cpp only).
#   manuscripts/M0xx.md  : the 30 controlled manuscripts under their blinded codes (no condition info)
#   pairs.csv            : pairwise-comparison design (each manuscript in 6 pairs; 90 pairs; both orders)
#   prompts/*.txt        : system prompt, calibrated absolute rubric, pairwise prompt
# The scripts (run_judge.bat, judge.ps1, download_model.bat) and the manual are written by
# make_desktop_scripts.py / make_desktop_manual.py.

import csv
import os
import random
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
CTRL = os.path.join(HERE, "..", "results", "controlled")
PKG = os.path.join(HERE, "..", "desktop_judge_package")
PAIR_SEED = 20261002
ROUNDS = 6                      # each manuscript appears in 6 pairs -> 90 pairs


def pair_design(codes):
    rng = random.Random(PAIR_SEED)
    seen, pairs = set(), []
    for _ in range(ROUNDS):
        for attempt in range(1000):        # random perfect matching without repeated pairs
            c = codes[:]
            rng.shuffle(c)
            cand = [tuple(sorted(c[i:i + 2])) for i in range(0, len(c), 2)]
            if not any(p in seen for p in cand):
                break
        seen.update(cand)
        pairs += cand
    return pairs


def main():
    os.makedirs(os.path.join(PKG, "manuscripts"), exist_ok=True)
    os.makedirs(os.path.join(PKG, "prompts"), exist_ok=True)
    key = list(csv.DictReader(open(os.path.join(CTRL, "_KEY_do_not_share.csv"), encoding="utf-8")))
    for k in key:
        shutil.copy(os.path.join(CTRL, "manuscripts", k["original_file"]),
                    os.path.join(PKG, "manuscripts", k["code"] + ".md"))
    codes = sorted(k["code"] for k in key)
    pairs = pair_design(codes)
    with open(os.path.join(PKG, "pairs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pair_id", "a", "b"])
        for i, (a, b) in enumerate(pairs, 1):
            w.writerow([f"P{i:03d}", a, b])
    print(f"{len(codes)} manuscripts, {len(pairs)} pairs ({len(set(pairs))} distinct) -> {PKG}")


if __name__ == "__main__":
    main()
