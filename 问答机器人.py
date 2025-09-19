# tfidf_qa.py
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import jieba
import numpy as np
# 示例问答库（可替换为更大的知识库或文档集合）
qa_pairs = [
    {"question": "如何重置我的密码？", "answer": "请前往设置->账号->重置密码，按提示操作。"},
    {"question": "怎样申请发票？", "answer": "登录后在订单页面选择需要开票的订单，点击开票并填写抬头信息。"},
    {"question": "退货政策是什么？", "answer": "未使用且在7天内可以无理由退货，运费按退货原因不同承担。"},
    {"question": "如何联系客服？", "answer": "拨打客服电话 400-123-456 或在应用内使用在线客服功能。"},
    {"question": "支持哪些支付方式？", "answer": "支持银行卡、支付宝、微信和部分信用卡支付。"}
]
# 把问答条目的“问题”和“答案”合并为检索文本（也可以只用问题或用文档）
documents = [item["question"] + " " + item["answer"] for item in qa_pairs]
# 中文分词器，用于给 TfidfVectorizer 提供分词函数
def jieba_tokenize(text):
    return jieba.lcut(text)
# 构建 TF-IDF 向量器（use_idf=True 是默认）
vectorizer = TfidfVectorizer(tokenizer=jieba_tokenize, lowercase=False)
tfidf_matrix = vectorizer.fit_transform(documents)  # shape: (n_docs, n_features)
def query_answer(user_query, top_k=1, min_sim=0.2):
    """
    输入用户查询，返回 top_k 个相似的答案（如果相似度低于 min_sim，则返回未命中提示）。
    返回格式：list of dicts: {"index","question","answer","score"}
    """
    if not user_query or not user_query.strip():
        return []
    q_vec = vectorizer.transform([user_query])
    sims = cosine_similarity(q_vec, tfidf_matrix)[0]  # shape: (n_docs,)
    top_idx = np.argsort(-sims)[:top_k]
    results = []
    for idx in top_idx:
        score = float(sims[idx])
        if score < min_sim:
            continue
        results.append({
            "index": int(idx),
            "question": qa_pairs[idx]["question"],
            "answer": qa_pairs[idx]["answer"],
            "score": score
        })
    return results
# 简单命令行交互示例
if __name__ == "__main__":
    print("TF-IDF QA demo. 输入问题（输入 exit 退出）：")
    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        res = query_answer(q, top_k=3, min_sim=0.15)
        if not res:
            print("Bot: 抱歉，未找到合适答案。可尝试换个说法。")
        else:
            for r in res:
                print(f"Bot (score={r['score']:.3f}): {r['answer']}")
