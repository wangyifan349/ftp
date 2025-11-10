# sentence_basic_no_wrappers.py
# 依赖: pip install -U sentence-transformers scikit-learn numpy
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
model = SentenceTransformer(MODEL_NAME)
# 示例语料
corpus = [
    "That is a happy person",
    "That is a happy dog",
    "That is a very happy person",
    "Today is a sunny day"
]
# 编码（返回 numpy array）
corpus_embeddings = model.encode(corpus, convert_to_numpy=True, batch_size=32, show_progress_bar=False)
print("corpus embeddings shape:", corpus_embeddings.shape)  # e.g., (4, 384)
# 计算 pairwise 余弦相似度矩阵
sim_matrix = cosine_similarity(corpus_embeddings, corpus_embeddings)
print("pairwise similarity matrix:\n", np.round(sim_matrix, 4))
# 两句相似度（直接编码并比较）
sent_a = "That is a happy person"
sent_b = "That is a very happy person"
emb_a, emb_b = model.encode([sent_a, sent_b], convert_to_numpy=True)
sim_ab = cosine_similarity([emb_a], [emb_b])[0][0]
print(f"similarity('{sent_a}', '{sent_b}') = {sim_ab:.4f}")
# 语义搜索（暴力检索）：给定 query，返回 top_k 索引/分数/文本
query = "happy person"
query_emb = model.encode([query], convert_to_numpy=True)[0]
sims = cosine_similarity([query_emb], corpus_embeddings)[0]  # 1 x N
top_k = 3
topk_idx = np.argsort(-sims)[:top_k]
print(f"Top {top_k} results for query '{query}':")
for i in topk_idx:
    print(f"  idx={int(i)} score={sims[i]:.4f} text='{corpus[int(i)]}'")
