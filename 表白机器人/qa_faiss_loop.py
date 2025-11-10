# qa_faiss_loop.py
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
# 1) 预存问答字典（科普常识示例）
qa_dict = {
    "什么是光年？": """光年是天文学中用于表示距离的单位，等于光在真空中一年所经过的距离，约为9.46 × 10^12 公里。""",
    "为什么天空是蓝色的？": """天空看起来是蓝色的因为大气分子对短波长（蓝光）的散射比对长波长（红光）更强，这个现象称为瑞利散射。""",
    "水的沸点是多少？": """在标准大气压（1 atm）下，纯净水的沸点是100°C（212°F）。海拔升高会降低大气压，从而降低沸点。""",
    "植物如何进行光合作用？": """光合作用是植物利用光能把二氧化碳和水转化为有机物（如葡萄糖）并释放氧气的过程，主要发生在叶绿体中的叶绿素。""",
    "什么是黑洞？": """黑洞是广义相对论预测的一种天体，因质量极大浓缩导致附近时空极度弯曲，甚至连光也无法逃脱其事件视界。"""
}
# 2) 模型与向量化
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
questions = list(qa_dict.keys())
answers = [qa_dict[q] for q in questions]
embeddings = model.encode(questions, convert_to_numpy=True, show_progress_bar=False)
embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)  # 归一化
dim = embeddings.shape[1]
index = faiss.IndexFlatIP(dim)
index.add(embeddings)
# 3) 检索函数
def retrieve_answers(query, top_k=3, score_threshold=0.35):
    q_emb = model.encode([query], convert_to_numpy=True)
    q_emb = q_emb / np.linalg.norm(q_emb, axis=1, keepdims=True)
    D, I = index.search(q_emb, top_k)
    results = []
    for score, idx in zip(D[0], I[0]):
        if idx == -1:
            continue
        if float(score) < score_threshold:
            continue
        results.append({
            "question": questions[idx],
            "answer": answers[idx],
            "score": float(score)
        })
    return results
# 4) 主循环
def main_loop():
    print("输入问题（输入 'exit' 或 'quit' 退出）：")
    while True:
        try:
            user_q = input("\n你的问题: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n退出。")
            break
        if not user_q:
            print("请先输入问题。")
            continue
        if user_q.lower() in ("exit", "quit"):
            print("退出。")
            break
        hits = retrieve_answers(user_q, top_k=3, score_threshold=0.35)
        if not hits:
            print("抱歉，未找到匹配的预存答案。")
            continue
        best = hits[0]
        # 使用三引号格式化答案输出
        answer_text = f'''"""{best["answer"]}"""'''
        print("\n匹配问题：", best["question"])
        print("相似度得分：", round(best["score"], 4))
        print("答案：")
        print(answer_text)
if __name__ == "__main__":
    main_loop()
