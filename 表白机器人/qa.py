# -*- coding: utf-8 -*-
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
# -------------------------------------------------
# 1️⃣ 载入模型 & 准备问答数据
# -------------------------------------------------
model = SentenceTransformer('all-MiniLM-L6-v2')
# model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
# 最高精度的 LaBSE（如果硬件足够，可选）
# model = SentenceTransformer('sentence-transformers/LaBSE')
qa_dict = {
    "What brand makes the Astrox series?": "Yonex makes the Astrox series.",
    "When was Yonex founded?": "Yonex was founded in 1946.",
    "What products does Yonex produce?": "Yonex produces rackets, shoes, strings, bags and apparel."
}
questions = list(qa_dict.keys())                     # 所有候选问题
# -------------------------------------------------
# 2️⃣ 编码所有问题并归一化（得到单位向量）
# -------------------------------------------------
embeddings = model.encode(
    questions,
    convert_to_tensor=False,
    normalize_embeddings=True          # 直接返回 L2‑归一化向量
).astype('float32')                    # FAISS 只接受 float32
# -------------------------------------------------
# 3️⃣ 建立 FAISS 索引（余弦相似度 → 内积）
# -------------------------------------------------
dim = embeddings.shape[1]               # 向量维度
index = faiss.IndexFlatIP(dim)          # Inner Product 索引
index.add(embeddings)                   # 一次性写入所有向量
# -------------------------------------------------
# 4️⃣ 检索函数
# -------------------------------------------------
def retrieve(user_query: str,
             top_k: int = 3,
             score_thr: float = 0.45,
             return_pairwise: bool = False):
    """
    返回匹配的答案列表，每项包含:
        - question_idx: 在 questions 列表中的下标
        - question:      原始问题文本
        - answer:        对应答案
        - score:         余弦相似度（0~1）
    若 return_pairwise 为 True 且返回多条结果，会额外返回
    `pairwise` 矩阵，矩阵[i][j] 为第 i、j 条问题的余弦相似度。
    """
    if not user_query.strip():
        return {"matches": [], "pairwise": None}
    # 编码查询并归一化
    q_vec = model.encode(
        [user_query],
        convert_to_tensor=False,
        normalize_embeddings=True
    ).astype('float32')
    # 在索引中搜索 top_k 条
    k = min(top_k, len(questions))
    scores, idxs = index.search(q_vec, k)   # shape (1, k)
    matches = []
    for score, idx in zip(scores[0], idxs[0]):
        if score < score_thr:               # 过滤低相似度
            continue
        matches.append({
            "question_idx": int(idx),
            "question":     questions[idx],
            "answer":       qa_dict[questions[idx]],
            "score":        float(score)
        })
    # 计算两两相似度矩阵（可选）
    pairwise = None
    if return_pairwise and len(matches) > 1:
        ids = [m["question_idx"] for m in matches]
        pairwise = np.dot(embeddings[ids], embeddings[ids].T).astype('float32')
    return {"matches": matches, "pairwise": pairwise}
# -------------------------------------------------
# 5️⃣ 交互式命令行循环
# -------------------------------------------------
def interactive_loop():
    print('输入问题（输入 "exit" 或 "quit" 结束）：')
    while True:
        txt = input(">> ").strip()
        if txt.lower() in {"exit", "quit"}:
            print("再见！")
            break
        res = retrieve(txt, top_k=3, score_thr=0.45, return_pairwise=True)
        if not res["matches"]:
            print("未找到合适的匹配。\n")
            continue
        best = res["matches"][0]
        print(f"答案: {best['answer']}")
        print(f"相似度: {best['score']:.4f}\n")
        if len(res["matches"]) > 1:
            print("其他候选:")
            for m in res["matches"][1:]:
                print(f"  - 相似度: {m['score']:.4f}  问题: {m['question']}")
            print()
        if res["pairwise"] is not None:
            print("返回问题之间的两两相似度矩阵：")
            print(res["pairwise"])
            print()
if __name__ == "__main__":
    interactive_loop()
