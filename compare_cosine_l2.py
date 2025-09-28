# 文件：compare_cosine_l2.py
# 说明：使用 sentence-transformers 提取句子嵌入并比较余弦相似度与 L2 距离
# 依赖：pip install sentence-transformers numpy
from sentence_transformers import SentenceTransformer, util
import numpy as np
from typing import List, Tuple
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"  # 常用 Sentence-BERT 模型

def load_sentence_encoder(model_name: str = MODEL_NAME) -> SentenceTransformer:
    """
    加载 SentenceTransformer 模型（自动下载或从缓存读取）。
    返回已加载的模型实例。
    """
    return SentenceTransformer(model_name)

def get_embeddings(model: SentenceTransformer, texts: List[str],
                   normalize: bool = False, batch_size: int = 32) -> np.ndarray:
    """
    将文本列表编码为句子嵌入向量（numpy 数组）。
    参数:
      - model: SentenceTransformer 实例
      - texts: 待编码句子列表
      - normalize: 若为 True，返回的向量已做 L2 归一化（单位向量）
      - batch_size: 批处理大小
    返回:
      - shape (n_texts, dim) 的 numpy 数组
    """
    # model.encode 支持 convert_to_numpy 和 normalize_embeddings 两个参数
    emb = model.encode(texts,
                       batch_size=batch_size,
                       convert_to_numpy=True,
                       normalize_embeddings=normalize)
    return emb

def l2_distance(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的 L2（欧氏）距离，返回标量"""
    return float(np.linalg.norm(a - b))

def safe_cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    计算余弦相似度，带零向量保护。
    如果任意向量范数为 0，返回 0.0（表示不相似 / 无信息）。
    """
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

def l2_normalize(v: np.ndarray) -> np.ndarray:
    """对单个向量做 L2 归一化（单位向量）；若范数为 0 则返回原向量"""
    n = np.linalg.norm(v)
    return v / n if n > 0 else v

def compare_pair(a: np.ndarray, b: np.ndarray) -> Tuple[float, float]:
    """
    返回给定两个向量的 (cosine, l2) 值（未归一化情况下）。
    """
    return safe_cosine_similarity(a, b), l2_distance(a, b)

if __name__ == "__main__":
    # 加载模型（只需一次）
    model = load_sentence_encoder(MODEL_NAME)
    # 示例句子（用于对比）
    texts = [
        "这是同一意思的句子示例一。",
        "这是与上句语义接近的另一种表述。",
        "这是一条语义完全不同的句子。"
    ]
    # 1) 获取未归一化的嵌入（原始向量）
    embeddings = get_embeddings(model, texts, normalize=False)  # shape (3, dim)
    # 2) 计算未归一化情况下的余弦与 L2（直接使用 embedding 向量）
    cos_12, l2_12 = compare_pair(embeddings[0], embeddings[1])
    cos_13, l2_13 = compare_pair(embeddings[0], embeddings[2])
    print("=== 未归一化嵌入 ===")
    print(f"cos(text0, text1) = {cos_12:.6f}    L2 = {l2_12:.6f}")
    print(f"cos(text0, text2) = {cos_13:.6f}    L2 = {l2_13:.6f}")
    # 3) 如果需要检索常用的单位向量比较：直接获取归一化嵌入
    embeddings_norm = get_embeddings(model, texts, normalize=True)  # 每行已单位化
    # 归一化后用内积等价于余弦
    dot_12 = float(np.dot(embeddings_norm[0], embeddings_norm[1]))
    dot_13 = float(np.dot(embeddings_norm[0], embeddings_norm[2]))
    l2norm_12 = l2_distance(embeddings_norm[0], embeddings_norm[1])
    l2norm_13 = l2_distance(embeddings_norm[0], embeddings_norm[2])
    print("\n=== L2 归一化后的嵌入（单位向量） ===")
    print(f"dot(text0, text1) [等于余弦] = {dot_12:.6f}    L2 = {l2norm_12:.6f}")
    print(f"dot(text0, text2) [等于余弦] = {dot_13:.6f}    L2 = {l2norm_13:.6f}")
    # 4) 可选：直接使用 sentence-transformers 提供的 util.cos_sim 计算批量余弦相似度矩阵
    #    util.cos_sim 返回 torch 张量或 numpy（取决于输入），可用于大规模检索
    cos_matrix = util.cos_sim(embeddings, embeddings)  # shape (3,3)
    print("\n余弦相似度矩阵（未归一化嵌入）:")
    print(cos_matrix.numpy())  # 打印为 numpy 数组
