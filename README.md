# Comparing Genetic Algorithms and LLMs for Research-Hypothesis Generation

Code, data, prompts and logs for the article

> Otsuki, A. *Comparing Genetic Algorithms and LLMs for Research-Hypothesis Generation: Mainstream Convergence of
> LLMs, Wider Hypothesis Exploration by Combinatorial Search, and the Limits of Literature-Distance Novelty
> Metrics.* Informatics (MDPI), manuscript informatics-4591240 (revised version).

Every table and figure of the revised article can be regenerated from this repository.

## Layout

| Path | Content | Article |
|---|---|---|
| `code/concepts.py` | Method / Problem / Goal vocabulary (15 × 15 × 12 = 2,700 hypotheses) | §3.2 |
| `code/build_knowledge_space.py` | Builds the knowledge space from the arXiv API | §3.1, Table 2 |
| `code/creative_ga.py` | Proposed model: shared embedding space, novelty, literature-grounded utility, GA and baselines | §3.1–3.4 |
| `code/run_experiments.py` | Experiments 1–3 (30 seeds, baselines, ablations, temporal hold-out, corpus-size sensitivity) | §4.2–4.4, Tables 8–10, Figs. 1–3 |
| `code/llm_hypothesis_metrics.py` | Outcome measures and diversity of the LLM-proposed hypotheses | §4.3, Table 9 |
| `code/diversity_tests.py` | Permutation tests of the diversity of GA vs. random search / hill climbing | §4.3 |
| `code/link_examples.py` | Examples of literature support for pairwise links | Table 6 |
| `code/make_figures.py`, `code/F1-2.py` | Figures from `results/*.csv` | Figs. 1–3 |
| `code/run_manuscript_experiment.py` | Experiment 4: controlled manuscript generation (local LLM writer, fully logged) | §4.5 |
| `code/llm_judge.py`, `code/analyze_manuscript_experiment.py`, `code/pairwise_consistency.py` | LLM judges (absolute and pairwise) and their analysis | §4.5 |
| `code/prepare_hypothesis_eval.py`, `code/analyze_hypothesis_eval.py` | Experiment 5: blinded rendering of hypotheses, booklets, and analysis of the rankings | §4.6 |
| `code/validate_novelty_openreview.py` | Validation of the novelty measure against ICLR peer reviews | §4.7, Table 11 |
| `code/pilot_manuscript_evaluator.py` | Instrument of the pilot case study (reproduces Table 12 exactly) | §4.8–4.10 |
| `code/*.ps1`, `code/make_*.py`, `code/prepare_rater_package.py` | Tools used to produce rating sheets and manuals (Windows) | §4.6 |
| `data/corpus.jsonl` | Knowledge space: 4,553 arXiv records (id, title, abstract, date, window, retrieval route) | §3.1 |
| `data/corpus_build_log.json` | Every arXiv query issued and its result count | §3.1 |
| `results/runs.csv`, `results/run_logs/` | One row / one log per run (method × seed): selected hypothesis and all outcome measures | §4.2–4.3 |
| `results/stats_*.csv`, `summary.json`, `sensitivity.csv`, `diversity*.csv` | Statistics behind Tables 8–10 and §4.3 | §4.2–4.4 |
| `results/openreview_*.csv` | Correlations of the novelty measure with ICLR review scores | Table 11 |
| `results/controlled/` | Experiment 4: hypotheses, the 30 manuscripts, all prompts and raw responses (`logs/`), LLM-judge outputs and summaries | §4.5 |
| `results/hypothesis_eval/` | Experiment 5: rendered hypotheses, triplets, rater orders, anonymized ratings (`ratings/`), summaries | §4.6 |
| `materials/human_evaluation/` | Rater manual (Japanese) and the booklets given to the two raters | §4.6, Appendix A |
| `desktop_judge/` | Scripts, prompts and inputs of the 70B LLM judge (Windows, llama.cpp, no Python needed) and its raw outputs | §4.5–4.6 |
| `prompts/` | Verbatim prompts of Conditions A, B and C of the pilot case study | §4.8 |
| `pilot_manuscripts/` | The three manuscripts evaluated in the pilot case study | §4.8–4.10 |

Files named `*_KEY_do_not_share.csv` map blinded codes to conditions. They were kept from the raters during the
evaluation and are published now that the evaluation is complete.

## Reproduce

```bash
pip install -r requirements.txt
cd code
python run_experiments.py            # Experiments 1-3, ~5 min on CPU (uses data/corpus.jsonl)
python make_figures.py
python llm_hypothesis_metrics.py
python diversity_tests.py
python analyze_hypothesis_eval.py ../results/hypothesis_eval/ratings/ratings_hyp_R1.csv ../results/hypothesis_eval/ratings/ratings_hyp_R2.csv --llm ../desktop_judge/results/Llama-3.3-70B-Instruct-Q3_K_M/hypothesis_rankings.csv
python pairwise_consistency.py ../desktop_judge/results/Llama-3.3-70B-Instruct-Q3_K_M
python pilot_manuscript_evaluator.py ../pilot_manuscripts/A.docx ../pilot_manuscripts/B.docx ../pilot_manuscripts/C.docx
```

* `build_knowledge_space.py` re-queries the live arXiv API, whose ranking can change; use the archived
  `data/corpus.jsonl` to reproduce the reported numbers exactly.
* `validate_novelty_openreview.py` needs the ReviewArena dataset (CC BY 4.0), which is not redistributed here.
  Download the five `iclr-*.parquet` files from <https://huggingface.co/datasets/Samarth0710/reviewarena> into
  `data/reviewarena/`.
* Experiment 4 and the LLM judges need local GGUF models served with llama.cpp (NVIDIA Nemotron-Nano-9B-v2,
  Llama-3.1-8B-Instruct, Llama-3.3-70B-Instruct). The model files are not redistributed; `desktop_judge/download_model.bat`
  shows the exact files used. All model outputs used in the article are included, so the analyses run without them.

Random seeds: GA/baselines 1–30; corpus split 12345; uniform reference 999; bootstrap 2026; corpus-size sensitivity 7;
arXiv background sampling 20261001; writer seed 100 + s; permutation tests 2026.
Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (CPU, normalized embeddings).

## Licence

Code: MIT (see `LICENSE`). arXiv metadata: CC0 1.0, as distributed by arXiv. Generated manuscripts, hypotheses,
ratings and other results: CC BY 4.0.

## Citation

Please cite the article above; citation metadata are in `CITATION.cff`.
