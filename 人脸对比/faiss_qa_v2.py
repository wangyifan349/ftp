# faiss_qa_v2.py
import os
import json
import numpy as np
import faiss
import pandas as pd
from sentence_transformers import SentenceTransformer
from typing import List, Dict
# ----------------- 配置 -----------------
MODEL_CHOICES = [
    "paraphrase-MiniLM-L6-v2",
    "all-MiniLM-L6-v2",
    "all-mpnet-base-v2",
    "paraphrase-multilingual-MiniLM-L12-v2"
]
model_name = "all-MiniLM-L6-v2"   # 从列表中选一个
INDEX_PATH = "faiss_qa_v2.index"
META_PATH = "faiss_qa_v2_meta.json"
EMB_DTYPE = 'float32'
BATCH_SIZE = 128
TOP_K = 5  # 检索候选数
# ----------------- 示例或从 CSV 读取 -----------------
# 若提供 CSV，请确保包含列 id,title,text；否则使用内置 SAMPLE_DOCS
CSV_PATH = None  # 若使用 CSV，填写路径 e.g. "kb.csv"
SAMPLE_DOCS = [
    {"id": 0, "title": "电动汽车充电基础", "text": "电动汽车充电通常分为慢充（交流充电）和快充（直流快充）。慢充适合家用，功率小，充满时间较长；快充适合公共快充站，可在短时间内充入较多电量。"},
    {"id": 1, "title": "电池容量与续航", "text": "电池容量以千瓦时(kWh)计，续航里程受电池容量、车辆能耗、驾驶习惯和温度等影响。一般冬季续航会降低。"},
    {"id": 2, "title": "电池安全与热失控", "text": "锂离子电池若遭受过充、短路或机械损伤，可能发生热失控。电池包通常有热管理系统、BMS（电池管理系统）和防护结构以降低风险。"},
    {"id": 3, "title": "充电注意事项", "text": "使用原厂或认证的充电设备，避免在极端高温或低温下长时间充电；插拔充电枪前确保充电停止；定期检查充电接口与线缆。"},
    {"id": 4, "title": "道路安全-行驶距离与车速", "text": "安全行驶需保持与前车足够的跟车距离，车速越高所需制动距离越长。雨雪路面摩擦系数降低，应适当减速并增大跟车距离。"},
    {"id": 5, "title": "道路安全-电动汽车特殊注意", "text": "电动汽车通常制动能量回收系统，会影响踩刹车的感受；遇到事故时需注意高压部件与电池包，救援人员应遵循电动汽车事故处理规范。"},
    {"id": 6, "title": "电池保养建议", "text": "长期不使用车辆时，建议将电池保持在大约30%-60%电量并定期充放电；避免长时间将电池充到100%或放到0%。"},
]
# ----------------- 加载知识库 -----------------
def load_docs(csv_path: str = None) -> List[Dict]:
    if csv_path and os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        docs = []
        for _, row in df.iterrows():
            docs.append({"id": int(row.get("id", _)), "title": str(row.get("title", "")), "text": str(row.get("text", ""))})
        return docs
    return SAMPLE_DOCS
docs = load_docs(CSV_PATH)
# ----------------- 加载模型 -----------------
model = SentenceTransformer(model_name)
# ----------------- Embedding 和 FAISS 操作 -----------------
def docs_to_texts(docs: List[Dict]) -> List[str]:
    return [ (str(d.get("title","")) + "。 " + str(d.get("text",""))).strip() for d in docs ]
def build_embeddings(docs: List[Dict], batch_size: int = BATCH_SIZE) -> np.ndarray:
    texts = docs_to_texts(docs)
    embs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        emb = model.encode(batch, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
        embs.append(emb)
    return np.vstack(embs).astype(EMB_DTYPE)
def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    d = embeddings.shape[1]
    index = faiss.IndexFlatIP(d)
    index.add(embeddings)
    return index
def save_index_and_meta(index: faiss.Index, docs: List[Dict], index_path=INDEX_PATH, meta_path=META_PATH):
    faiss.write_index(index, index_path)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
def load_index_and_meta(index_path=INDEX_PATH, meta_path=META_PATH):
    if not os.path.exists(index_path) or not os.path.exists(meta_path):
        return None, None
    index = faiss.read_index(index_path)
    with open(meta_path, 'r', encoding='utf-8') as f:
        docs = json.load(f)
    return index, docs
# ----------------- 检索与答案生成 -----------------
def ensure_index(docs: List[Dict]):
    index, meta = load_index_and_meta()
    if index is None:
        embeddings = build_embeddings(docs)
        index = build_faiss_index(embeddings)
        save_index_and_meta(index, docs)
    return load_index_and_meta()
def search_query(index: faiss.Index, query: str, k: int = TOP_K):
    q_emb = model.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype(EMB_DTYPE)
    D, I = index.search(q_emb, k)
    scores = D[0].tolist()
    idxs = I[0].tolist()
    # 组合并按相似度降序（faiss 返回即为降序）
    results = []
    for pos, score in zip(idxs, scores):
        if pos < 0:
            continue
        results.append({"pos": int(pos), "score": float(score)})
    return results
def compose_answer(query: str, docs: List[Dict], hits: List[Dict]) -> str:
    if not hits:
        return "抱歉，未检索到相关信息。请提供更多细节或换个问法。"
    # 将 hits 映射到文档并按 score 降序（已降序）
    mapped = []
    for h in hits:
        pos = h["pos"]
        if pos < 0 or pos >= len(docs):
            continue
        d = docs[pos]
        mapped.append({"id": d.get("id"), "title": d.get("title"), "text": d.get("text"), "score": h["score"]})
    # 构建较长的展示：列出所有候选（降序），然后给出基于最相似项的最终回答
    lines = []
    lines.append(f"检索到 {len(mapped)} 条候选（按相似度降序）：\n")
    for i, m in enumerate(mapped, start=1):
        lines.append(f"{i}. 标题：{m['title']}\n   相似度：{m['score']:.4f}\n   内容：{m['text']}\n")
    best = mapped[0]
    lines.append("-----\n最终简要回答（依据相似度最高的条目）：\n")
    # 用规则抽取：若条目较长，可取首句/摘要；这里直接返回条目文本并补充一句推荐
    lines.append(best["text"])
    lines.append(f"\n（以上结论基于与问题最相似的知识片段：\"{best['title']}\"，相似度 {best['score']:.4f}）")
    return "\n".join(lines)
def answer_query(query: str, top_k: int = TOP_K):
    index, meta_docs = ensure_index(docs)
    if index is None or meta_docs is None:
        raise RuntimeError("索引加载或创建失败。")
    hits = search_query(index, query, k=top_k)
    return compose_answer(query, meta_docs, hits)
# ----------------- 命令行交互 -----------------
if __name__ == "__main__":
    # 若索引不存在则创建并保存
    if not (os.path.exists(INDEX_PATH) and os.path.exists(META_PATH)):
        emb = build_embeddings(docs)
        idx = build_faiss_index(emb)
        save_index_and_meta(idx, docs)
        print("已构建并保存索引与元数据。")
    print("可选模型：", MODEL_CHOICES)
    print("当前模型：", model_name)
    while True:
        q = input("\n请输入用户问题（exit 退出）：\n> ").strip()
        if q.lower() in ("exit", "quit"):
            break
        print("\n正在检索并生成答案...\n")
        ans = answer_query(q, top_k=TOP_K)
        print(ans)
