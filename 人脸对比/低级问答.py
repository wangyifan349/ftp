import faiss
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
faq = [
    {
        "question": "如何重置密码？",
        "answer": "在登录页面点击“忘记密码”，按照邮件指示完成重置。"
    },
    {
        "question": "我的订单什么时候发货？",
        "answer": "订单在付款后 1‑2 个工作日内发货，具体时间请查看订单详情。"
    },
    {
        "question": "支持哪些支付方式？",
        "answer": "我们支持信用卡、PayPal、Apple Pay 和 Google Pay。"
    },
    {
        "question": "如何申请退款？",
        "answer": "进入订单详情页，点击“申请退款”，按照提示填写原因即可。"
    },
    {
        "question": "客服工作时间是什么时候？",
        "answer": "客服工作时间为周一至周五 9:00‑18:00（北京时间）。"
    },
]
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
def build_faiss_index():
    texts = [f"{item['question']} {item['answer']}" for item in faq]
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True
    )
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(np.array(embeddings, dtype='float32'))
    return index
faiss_index = build_faiss_index()
def answer_question(query: str, top_k: int = 1):
    query_vec = model.encode([query], normalize_embeddings=True)
    query_vec = np.array(query_vec, dtype='float32')
    distances, indices = faiss_index.search(query_vec, top_k)
    results = []
    for idx, score in zip(indices[0], distances[0]):
        item = faq[idx]
        cosine_similarity = float(score)
        query_embedding = query_vec[0].tolist()
        doc_text = f"{item['question']} {item['answer']}"
        doc_embedding = model.encode([doc_text], normalize_embeddings=True)[0].tolist()
        results.append({
            "question": item["question"],
            "answer": item["answer"],
            "similarity": cosine_similarity,
            "query_embedding": query_embedding,
            "doc_embedding": doc_embedding
        })
    return results
if __name__ == "__main__":
    print("=== 基于向量相似度的问答机器人 ===")
    print("输入 'exit' 退出。\n")
    while True:
        user_input = input("🗨️ 你的问题： ").strip()
        if user_input.lower() == "exit":
            print("再见！")
            break
        if not user_input:
            continue
        resp = answer_question(user_input, top_k=1)[0]
        print("\n🔎 匹配问题：", resp["question"])
        print("✅ 答案：")
        print(resp["answer"])
        print(f"🔢 余弦相似度：{resp['similarity']:.6f}")
      
