import numpy as np
qa_dict = {
    "什么品牌生产 Astrox 系列？": """Yonex 生产 Astrox 系列。""",
    "Yonex 是何时成立的？": """Yonex 成立于 1946 年。""",
    "Yonex 生产哪些产品？": """Yonex 生产球拍、鞋子、线、包以及服装。""",
    "羽毛球中哪个系列的球拍以强力扣杀著称？": """Yonex 的 Astrox 系列专为追求强力进攻的选手设计。""",
    "篮球篮筐的标准高度是多少？": """篮筐离地面高度为 10 英尺（约 3.05 米）。""",
    "标准篮球比赛每队场上有多少名球员？": """每支球队场上有 5 名球员。""",
    "一次好的有氧运动通常包括哪些环节？": """一般包括热身、持续的中等强度活动（如跑步、骑行或游泳）以及放松。""",
    "哪项运动使用羽毛球（shuttlecock）？": """羽毛球使用羽毛球（也称为鸟羽）。""",
    "单打羽毛球场地的标准长度是多少？": """单打场地长 13.4 米，宽 5.18 米。""",
    "成年人每周建议进行多少分钟的中等强度有氧运动？": """健康指南建议每周至少 150 分钟的中等强度有氧运动。"""
}
questions = list(qa_dict.keys())
tokenized_questions = []
for q in questions:
    tokenized_questions.append(q.lower().split())
def lcs_len(a, b):
    m = len(a)
    n = len(b)
    dp = [0] * (n + 1)
    for i in range(1, m + 1):
        prev = 0
        for j in range(1, n + 1):
            cur = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
            else:
                dp[j] = dp[j] if dp[j] > dp[j - 1] else dp[j - 1]
            prev = cur
    return dp[n]
def lcs_similarity(a, b):
    if not a or not b:
        return 0.0
    return lcs_len(a, b) / max(len(a), len(b))
def retrieve_by_lcs(user_query, top_k=3, score_thr=0.0):
    if not user_query.strip():
        return []
    query_tokens = user_query.lower().split()
    scores = []
    for qt in tokenized_questions:
        scores.append(lcs_similarity(query_tokens, qt))
    sorted_idx = list(range(len(scores)))
    sorted_idx.sort(key=lambda i: scores[i], reverse=True)
    results = []
    count = 0
    for idx in sorted_idx:
        if count >= top_k:
            break
        s = scores[idx]
        if s < score_thr:
            continue
        results.append({
            "question_idx": idx,
            "question": questions[idx],
            "answer": qa_dict[questions[idx]],
            "score": float(s)
        })
        count += 1
    return results
# -------------------------------------------------
# 交互式循环（while True）
# -------------------------------------------------
if __name__ == "__main__":
    while True:
        query = input("请输入查询（直接回车退出）: ").strip()
        if not query:
            break
        matches = retrieve_by_lcs(query, top_k=2, score_thr=0.2)
        if not matches:
            print("未找到匹配。\n")
            continue
        for m in matches:
            print(m["question"])
            print(m["answer"])
            print(f"score = {m['score']:.4f}\n")
