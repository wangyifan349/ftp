# -*- coding: utf-8 -*-
"""
中文 TF-IDF + FAISS (CPU) 即时查询脚本搜索词频最接近）
依赖: jieba, scikit-learn, numpy, faiss-cpu
"""
import sys
import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
import faiss
# ---------- 配置 ----------
docs = [
    "细胞信号传导路径中，受体激活后通过二级信使如cAMP放大信号，调控基因表达与细胞代谢，从而影响细胞增殖、分化和凋亡；在药理学中针对这些通路的抑制剂或激动剂常用于治疗癌症与代谢性疾病。",
    "在人体免疫系统中，先天免疫通过巨噬细胞和中性粒细胞快速清除病原体并触发炎症反应，而获得性免疫依赖B细胞产生抗体和T细胞介导的细胞毒性来实现针对特异性抗原的长期保护；免疫耐受的破坏可导致自身免疫性疾病。",
    "热力学第二定律指出孤立系统的熵不可自发减小，这一原理在工程与统计物理中用于解释不可逆过程、热机效率上限（卡诺效率）以及微观粒子能级分布对宏观可逆性的限制。",
    "在药代动力学中，吸收、分布、代谢与排泄（ADME）共同决定药物在体内的浓度时间曲线；影响因素包括肝脏代谢酶活性、血浆蛋白结合率和组织灌注，剂量调整需考虑这些参数以避免毒性或疗效不足。",
    "一般民事法律原则强调公平与契约自由，合同成立需要要约与承诺并具有合法目的与相应能力；违约责任可以通过履行、损害赔偿或解除合同等救济方式解决，司法实践中常结合衡平原则确定合理救济。"
]

cut_all = False      # jieba 分词模式
max_features = None  # TF-IDF 最大特征数（None 表示不限制）
top_k = 5            # 每次查询返回 top_k 个结果
# ---------- 工具函数 ----------
def tokenize(text: str, cut_all_local: bool = False) -> str:
    tokens = jieba.cut(text, cut_all=cut_all_local)
    return " ".join([t for t in tokens if t.strip()])
def build_tfidf_matrix(docs_list, cut_all_local=False, max_features_local=None):
    tokenized = [tokenize(d, cut_all_local) for d in docs_list]
    vectorizer = TfidfVectorizer(
        analyzer='word',
        tokenizer=lambda x: x.split(),
        preprocessor=None,
        token_pattern=None,
        max_features=max_features_local
    )
    tfidf_sparse = vectorizer.fit_transform(tokenized)
    tfidf_dense = tfidf_sparse.toarray().astype('float32')
    return vectorizer, tfidf_dense
def l2_normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (mat / norms).astype('float32')
def build_faiss_index_cpu(embedded_vectors: np.ndarray):
    """仅构建 CPU 上的 FAISS IndexFlatIP"""
    n, d = embedded_vectors.shape
    index = faiss.IndexFlatIP(d)
    index.add(embedded_vectors)
    return index
def search_with_faiss(index: faiss.Index, query_vecs: np.ndarray, top_k_local=5):
    distances, indices = index.search(query_vecs, top_k_local)
    return distances, indices
# ---------- 初始化（脚本启动时运行一次） ----------
vectorizer, tfidf_dense = build_tfidf_matrix(docs, cut_all_local=cut_all, max_features_local=max_features)
tfidf_norm = l2_normalize_rows(tfidf_dense)
index = build_faiss_index_cpu(tfidf_norm)
print("索引构建完成，文档数:", len(docs))
# ---------- 交互查询循环 ----------
print("输入查询（输入 'exit' 或 'quit' 退出）：")
while True:
    try:
        query = input("> ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n退出。")
        break
    if not query:
        continue
    if query.lower() in ("exit", "quit"):
        print("退出。")
        break
    q_tok = tokenize(query, cut_all_local=cut_all)
    q_vec_sparse = vectorizer.transform([q_tok])
    q_vec = q_vec_sparse.toarray().astype('float32')
    q_vec = l2_normalize_rows(q_vec)
    distances, indices = search_with_faiss(index, q_vec, top_k_local=top_k)
    print(f"查询: {query}")
    for rank, (idx, score) in enumerate(zip(indices[0], distances[0]), start=1):
        if idx == -1:
            continue
        print(f"  top{rank}: idx={int(idx)}, score={float(score):.4f}, doc={docs[int(idx)]}")
