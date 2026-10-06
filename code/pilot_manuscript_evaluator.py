# pilot_manuscript_evaluator.py
#
# Revised version of manuscript_evaluator.py, used ONLY for the pilot case study (Section 4.5 of
# the revised manuscript; one manuscript per condition A/B/C).
#
# Purpose of the revision:
#   1. Reproducibility of the originally reported Table 8 (Reviewer 1 #7). The submitted
#      evaluator imported a module (creative_ai_agent) that was not part of the code base and did
#      not contain the "combinatorial" Novelty variant that produced the reported SO values. Both
#      are now self-contained here; running this file reproduces every Table 8 value.
#   2. Transparency about circularity (Reviewer 1 #2). SQ (Quality) and SS (Significance) reuse
#      the same three success-pattern rules (Table 6) and domain signatures that the ORIGINAL GA
#      used as its utility term. They are therefore reported with an explicit `circular` flag and
#      are NOT used as evidence for the GA in the revised manuscript.
#   3. Ceiling diagnosis (Reviewer 1 #4, Reviewer 2 #1). In addition to the original instrument,
#      each manuscript's semantic novelty is computed with the same sentence encoder as the
#      revised GA, against (a) the original 3-paper knowledge space and (b) the full arXiv search
#      corpus, to show that the A = C ceiling in Originality was an artefact of the 3-paper space.
#
# This instrument is NOT a validated measure of scientific originality, correctness,
# reproducibility or significance (Reviewer 1 #6); decision labels are retained only so that the
# original Table 8 can be reproduced and are not reported in the revised manuscript.
#
# Usage: python pilot_manuscript_evaluator.py  A).docx B).docx C).docx

import difflib
import json
import os
import re
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    from docx import Document
except ImportError:
    Document = None

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- original instrument constants (unchanged; Eq. 30-37 of the submitted manuscript) --------
ALPHA_SO, BETA_SO = 0.6, 0.4
GAMMA_C, GAMMA_D, GAMMA_P = 0.6, 0.3, 0.1
W = 0.25
SR_REJECT_THRESHOLD = 2.0
DOMAIN_SIM_THRESHOLD = 0.0005

ORIGINAL_THREE_PAPERS = [
    ("Attention is All You Need", "Transformer architecture for sequence"),
    ("Language Models are Few-Shot Learners", "GPT-3 and in-context learning"),
    ("Constitutional AI", "RLHF and safety based on rules"),
]
DOMAIN_SIGNATURES = {
    "Finance": "investment risk portfolio assets banking transactions 投資 リスク ポートフォリオ 資産 銀行 取引",
    "Medical": "diagnosis imaging patient treatment clinical drug discovery 診断 画像 患者 治療 臨床 創薬 医療",
    "IT": "algorithm development security cloud automation アルゴリズム 開発 セキュリティ クラウド 自動化",
    "Energy": "energy power grid renewable battery emissions",
    "Education": "education learning outcomes curriculum student pedagogy 教育 学習",
}
RULE_DESCRIPTIONS = [   # = the original GA's utility rules (Table 6)  -> circular with the GA
    "quantum computing quantum annealing reduces inference latency and speeds up response time",
    "symbolic reasoning and formal logic mitigate hallucination and improve factual accuracy",
    "evolutionary search and genetic algorithms foster creativity and novel idea generation",
]
CONCEPT_VOCAB = {
    'Method': ['Transformer', 'Diffusion', 'Reinforcement Learning', 'Evolutionary Strategy',
               'Knowledge Graph', 'Symbolic AI', 'Quantum Annealing', 'Attention Mechanism',
               'Probabilistic Modeling', 'Multi-Agent System'],
    'Problem': ['Hallucination', 'Forgetting', 'Data Scarcity', 'High Latency', 'Bias',
                'Lack of Novelty', 'Energy Consumption', 'Homogenization', 'Unreliability',
                'Uncertainty'],
    'Goal': ['Creativity', 'Robustness', 'Efficiency', 'Fairness', 'Autonomy',
             'Explainability', 'Diversity', 'Trustworthiness'],
}


def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def to5(x):
    return round(1.0 + 4.0 * clip(x), 2)


def load_text(path):
    if path.lower().endswith((".md", ".txt")):
        return open(path, encoding="utf-8").read()
    return "\n".join(p.text for p in Document(path).paragraphs)


class Index:
    def __init__(self, docs):
        self.v = TfidfVectorizer(token_pattern=r"(?u)\b\w+\b", ngram_range=(1, 2), min_df=1)
        self.v.fit(docs)

    def sim(self, a, b):
        va, vb = self.v.transform([a, b])
        return float(cosine_similarity(va, vb)[0][0])


def recover_mpg(text, idx):
    out = []
    for cat, terms in CONCEPT_VOCAB.items():
        sims = {t: idx.sim(text, t) for t in terms}
        out.append(max(sims, key=sims.get))
    return tuple(out)


def evaluate(paths):
    texts = {os.path.basename(p): load_text(p) for p in paths}
    refs = [f"{t} {s}" for t, s in ORIGINAL_THREE_PAPERS]
    corpus = list(texts.values()) + refs + [t for v in CONCEPT_VOCAB.values() for t in v] \
        + list(DOMAIN_SIGNATURES.values()) + RULE_DESCRIPTIONS
    idx = Index(corpus)
    ref_mpg = [recover_mpg(r, idx) for r in refs]

    res = {}
    for name, text in texts.items():
        mpg = recover_mpg(text, idx)
        # Originality: text-level (first implementation) and combinatorial (reported in Table 8)
        nov_text = clip(1 - max(idx.sim(text, r) for r in refs))
        nov_comb = clip(1 - max(idx.sim(" ".join(mpg), " ".join(rm)) for rm in ref_mpg))
        nontriv = clip(1 - max(difflib.SequenceMatcher(None, text, r).quick_ratio() for r in refs))
        # Quality (circular: same rules as the original GA utility)
        sims = [idx.sim(text, d) for d in RULE_DESCRIPTIONS]
        tr = clip(0.5 + max(sims) * 3.0)
        ee = clip(0.5 + np.mean(sims) * 3.0)
        # Reproducibility (literal disclosure check, unchanged)
        low = text.lower()
        code = bool(re.search(r'github\.com|\brepo(sitory)?\b|\.py(?![a-z])|code\s+(is\s+)?available|'
                              r'コード|実装基盤|実装(コード)?(を|が|は|の)|リポジトリ', low))
        data = bool(re.search(r'\bdataset\b|data\s+(is\s+)?available|data availability|\bbenchmark\b|'
                              r'データセット|ベンチマーク', low))
        par = bool(re.search(r'hyperparameter|learning rate|\bepoch|\btoken\b', low)) or \
            bool(re.search(r'ハイパーパラメータ|学習率|エポック|トークン数', low)) or \
            bool(re.search(r'\b\d+(\.\d+)?\s*(%|percent)\b', low))
        # Significance (circular: domain signatures + the same rule-based utility)
        gen = sum(idx.sim(text, s) >= DOMAIN_SIM_THRESHOLD for s in DOMAIN_SIGNATURES.values()) / len(DOMAIN_SIGNATURES)
        SO = to5(ALPHA_SO * nov_comb + BETA_SO * nontriv)
        SQ = to5((tr + ee) / 2)
        SR = to5(GAMMA_C * code + GAMMA_D * data + GAMMA_P * par)
        SS = to5(gen * ee)
        tot = round(W * (SO + SQ + SR + SS), 2)
        res[name] = {"recovered_MPG": mpg, "Novelty_text": round(nov_text, 3),
                     "Novelty_combinatorial": round(nov_comb, 3), "NonTriviality": round(nontriv, 3),
                     "SO": SO, "SQ": SQ, "SR": SR, "SS": SS, "Stotal": tot,
                     "SO_textlevel_variant": to5(ALPHA_SO * nov_text + BETA_SO * nontriv),
                     "circular": {"SQ": True, "SS": True, "SO": False, "SR": False},
                     "Generality": gen, "code": code, "data": data, "params": par}
    return res, texts


def semantic_ceiling_check(texts):
    """Novelty of each manuscript (mean-pooled MiniLM embedding of 200-word chunks) against the
    original 3-paper space and against the full arXiv search corpus of the revised experiments."""
    try:
        import creative_ga as cg
    except Exception as e:      # sentence-transformers / corpus not available
        return {"skipped": str(e)}
    emb = cg.Embedder()
    ks = cg.KnowledgeSpace.build(emb)
    V3 = emb.encode([f"{t}. {s}" for t, s in ORIGINAL_THREE_PAPERS])
    out = {}
    for name, text in texts.items():
        words = text.split()
        chunks = [" ".join(words[i:i + 200]) for i in range(0, max(len(words), 1), 200)] or [text]
        z = emb.encode(chunks).mean(axis=0)
        z /= np.linalg.norm(z)
        s3, sfull = float((V3 @ z).max()), float((ks.V_search @ z).max())
        nearest = ks.search[int((ks.V_search @ z).argmax())]["title"]
        out[name] = {"N_vs_3papers": round(1 - s3, 3), "N_vs_full_corpus": round(1 - sfull, 3),
                     "nearest_corpus_paper": nearest}
    return out


if __name__ == "__main__":
    paths = sys.argv[1:] or ["A).docx", "B).docx", "C).docx"]
    res, texts = evaluate(paths)
    sem = semantic_ceiling_check(texts)
    for k, v in res.items():
        print(k, json.dumps(v, ensure_ascii=False))
    print("semantic ceiling check:", json.dumps(sem, ensure_ascii=False, indent=1))
    os.makedirs(os.path.join(HERE, "..", "results"), exist_ok=True)
    with open(os.path.join(HERE, "..", "results", "pilot_evaluation.json"), "w", encoding="utf-8") as f:
        json.dump({"instrument": res, "semantic_ceiling_check": sem}, f, ensure_ascii=False, indent=1)
