# Pre-specified design of the round-2 robustness experiments (written before any data were generated)

**Date:** 2026-10-09. These experiments respond to Reviewer 1 (round 2), Comments 2 and 3. All results are
reported in the revised manuscript whatever their direction.

## R2-A: LLM-proposed hypotheses across models, prompts and temperatures (Comment 2)

- **Models (two families, local llama.cpp, CPU):**
  - NVIDIA Nemotron-Nano-9B-v2 (Q8_0), the model used in round 1, with internal reasoning disabled
  - Meta Llama-3.1-8B-Instruct (Q8_0)
- **Prompts:**
  - P0 = the original prompt, which asks for a hypothesis in AI, "in particular generative AI"
  - P1 = the same prompt without the generative-AI restriction ("in artificial intelligence and machine learning")
- **Temperatures:** 0.7 (original) and 1.0; top-p 0.95 in all configurations.
- **Samples:** seeds 1–30 for each of the 2 × 2 × 2 = 8 configurations. Nemotron/P0/0.7 is the existing round-1 set,
  which was generated with identical settings and seeds.
- **Answer format and validity:** the same JSON format and validity rule as in round 1, with up to 5 attempts per seed.

## R2-B: Scope-matched LLM selection (Comment 3, first part)

- The LLM receives the same concept vocabulary as the GA (15 methods, 15 problems, 12 goals; `concepts.py`) and is asked
  to choose one item of each list so that the combination is a novel and scientifically valid hypothesis.
- **Models:** both models above; temperature 0.7, top-p 0.95; seeds 1–30.
- **Validity rule:** the answers must match vocabulary items exactly (case-insensitive), with up to 5 attempts.

## Outcome measures and analysis (identical to Experiment 2)

- **Primary measures:**
  - diversity = mean pairwise cosine similarity of the 30 hypotheses (lower = more diverse)
  - N_out = held-out novelty
- **Secondary measures:** N_out (TF–IDF), FS, Δ, number of distinct hypotheses, share of the most frequent method.
- **Comparisons:** each configuration against the GA (30 runs of Experiment 2).
  - diversity: two-sided permutation test, 20,000 permutations
  - N_out: Mann–Whitney U test
  - Holm correction within each measure across configurations
- **Interpretation rule, fixed in advance:**
  - The claim that LLM proposals concentrate on mainstream themes is kept only for the configurations in which it
    holds.
  - If it holds in some configurations but not in others, the manuscript states that it depends on the setting.
- **Not done (Comment 3, second part):** a budget-matched best-of-200 selection from an LLM pool. It is acknowledged as
  a limitation.
