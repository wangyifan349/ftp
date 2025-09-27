# chatbot_lcs.py
from typing import List, Tuple, Dict

# QA 字典：问题 -> 回答
QA_DB: Dict[str, str] = {
    "你好": "你好！有什么可以帮你？",
    "你叫什么名字": "我是一个示例聊天机器人。",
    "今天天气怎么样": "抱歉，我无法实时获取天气信息。",
    "怎么做蛋炒饭": "先把米饭、鸡蛋和配菜准备好，热锅冷油，先炒鸡蛋再下饭……",
    "最长公共子序列是什么": "最长公共子序列（LCS）是在两个序列中都出现且保持相对顺序的最长序列。",
    # 可根据需要扩展
}

def lcs_length(a: str, b: str) -> int:
    """
    计算两个字符串的最长公共子序列长度（动态规划）。
    时间复杂度 O(len(a) * len(b))。
    """
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    # dp[i][j]：a[:i] 与 b[:j] 的 LCS 长度；使用 1D 优化也可，但这里用 2D 清晰
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]

def lcs_similarity(a: str, b: str) -> float:
    """
    基于 LCS 的相似度度量。将 LCS 长度归一化到 [0,1]。
    使用的归一化方法：LCS_len / max(len(a), len(b))。
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    l = lcs_length(a, b)
    return l / max(len(a), len(b))

def rank_answers_by_lcs(query: str, qa_db: Dict[str, str], top_k: int = 3) -> List[Tuple[str, str, float]]:
    """
    返回按相似度降序排列的前 top_k 个候选 (question, answer, score)。
    """
    scores = []
    for q, a in qa_db.items():
        score = lcs_similarity(query, q)
        scores.append((q, a, score))
    # 按 score 降序排序
    scores.sort(key=lambda x: x[2], reverse=True)
    return scores[:top_k]

def chatbot_response(query: str, qa_db: Dict[str, str], threshold: float = 0.2) -> str:
    """
    简单响应策略：
    - 计算相似度最高的候选；
    - 若最高分 >= threshold，则返回该答案；
    - 否则返回一个默认未匹配回复并列出前几个候选供人工选择。
    """
    ranked = rank_answers_by_lcs(query, qa_db, top_k=5)
    best_q, best_a, best_score = ranked[0]
    if best_score >= threshold:
        return best_a
    else:
        # 构造包含候选问题和分数的回复（降序）
        lines = ["没有找到高置信度的直接匹配。以下是候选回复（按相似度降序）："]
        for q, a, s in ranked:
            lines.append(f"问题: {q}  (相似度: {s:.3f}) -> 回答: {a}")
        return "\n".join(lines)

# 简单命令行交互示例
if __name__ == "__main__":
    print("示例聊天机器人（基于 LCS 相似度）。输入 '退出' 结束。")
    while True:
        user = input("你: ").strip()
        if user in ("退出", "quit", "exit"):
            print("再见！")
            break
        reply = chatbot_response(user, QA_DB, threshold=0.25)
        print("机器人:", reply)
