from sentence_transformers import SentenceTransformer
import numpy as np
import faiss
MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
DEFAULT_TOP_K = 5
DEFAULT_SIM_THRESHOLD = 0.45
model = SentenceTransformer(MODEL_NAME)
qa_pairs = [
    {
        "question": """如何重置密码？
我忘记密码，无法登录，步骤有哪些？""",
        "answer": """1. 打开设置 -> 安全。
2. 选择“重置密码”并输入注册邮箱。
3. 点击邮件中的验证码链接，设置新密码。
注意：重置链接 30 分钟内有效。"""
    }
]

def add_item(item):
    if not isinstance(item, dict):
        raise ValueError("item 必须是 dict")
    if "question" not in item or "answer" not in item:
        raise ValueError("item 必须包含 'question' 和 'answer' 字段")
    qa_pairs.append(item)
def add_items(items):
    for it in items:
        add_item(it)

# 示例：追加单条
new_item = {
    "question": """如何导出聊天记录？
我想把聊天记录保存为文件。""",
    "answer": """前往设置 -> 隐私 -> 导出记录，选择时间范围并导出。"""
}
add_item(new_item)

# 示例：追加多条
more = [
    {
        "question": """如何申请退款？
订单已支付但想退款，可以怎么操作？""",
        "answer": """请在订单详情页点击“申请退款”，填写退款原因并上传凭证。
退款审核通常需要 3-5 个工作日。"""
    },
    {
        "question": """如何联系客服？
有哪些联系方式？""",
        "answer": """在线客服：进入帮助中心点击“在线客服”。
电话客服：工作日 9:00-18:00，客服热线 400-123-4567。"""
    }
]
add_items(more)
# 验证
print(len(qa_pairs))
print(qa_pairs[-1]["question"])




# 平铺构建问题列表
questions = []
for item in qa_pairs:
    q_text = item["question"]
    questions.append(q_text)
# 每次启动重新编码并构建索引（不加载历史向量）
texts_to_encode = questions
embeddings = model.encode(texts_to_encode, convert_to_numpy=True, show_progress_bar=False)
# 归一化向量
norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
embeddings = embeddings / (norms + 1e-12)
# 构建 FAISS 索引（IndexFlatIP），每次启动均新建
dim = embeddings.shape[1]
index = faiss.IndexFlatIP(dim)
index.add(embeddings.astype('float32'))
# 增量添加函数（平铺实现），追加到当前内存索引（不会保存到磁盘）
def add_qa_flat(index_obj, existing_questions, existing_qa_pairs, new_qa_pairs_list):
    new_questions_local = []
    for new_item in new_qa_pairs_list:
        new_q = new_item["question"]
        new_questions_local.append(new_q)

    new_embeddings_local = model.encode(new_questions_local, convert_to_numpy=True, show_progress_bar=False)
    norms_new = np.linalg.norm(new_embeddings_local, axis=1, keepdims=True)
    new_embeddings_local = new_embeddings_local / (norms_new + 1e-12)
    index_obj.add(new_embeddings_local.astype('float32'))
    updated_questions = []
    for q in existing_questions:
        updated_questions.append(q)
    for q in new_questions_local:
        updated_questions.append(q)
    updated_qa_pairs = []
    for p in existing_qa_pairs:
        updated_qa_pairs.append(p)
    for p in new_qa_pairs_list:
        updated_qa_pairs.append(p)
    return index_obj, updated_questions, updated_qa_pairs
# 查询函数（平铺实现）
def query_index_flat(query_text, index_obj, questions_list, qa_pairs_list, top_k=DEFAULT_TOP_K, similarity_threshold=DEFAULT_SIM_THRESHOLD):
    q_emb_local = model.encode([query_text], convert_to_numpy=True)
    norm_q = np.linalg.norm(q_emb_local, axis=1, keepdims=True)
    q_emb_local = q_emb_local / (norm_q + 1e-12)
    D, I = index_obj.search(q_emb_local.astype('float32'), top_k)
    scores = []
    idxs = []
    for s in D[0]:
        scores.append(float(s))
    for ii in I[0]:
        idxs.append(int(ii))
    results = []
    i = 0
    while i < len(idxs):
        idx = idxs[i]
        score = scores[i]
        if idx >= 0 and score >= similarity_threshold:
            res_item = {}
            res_item["question"] = questions_list[idx]
            res_item["answer"] = qa_pairs_list[idx]["answer"]
            res_item["score"] = score
            results.append(res_item)
        i += 1
    return results
# 主循环：持续对话（每次启动使用新编码的索引）
if __name__ == "__main__":
    loaded_index = index
    loaded_questions = questions
    loaded_qa_pairs = qa_pairs
    print("进入对话模式（使用本次启动重新编码的向量），输入空行或 Ctrl-C 退出。")
    while True:
        try:
            user_input = input("\n用户: ").strip()
        except KeyboardInterrupt:
            print("\n已退出。")
            break
        if user_input == "":
            print("退出对话。")
            break
        topk_str = input("top_k (回车使用默认 {}): ".format(DEFAULT_TOP_K)).strip()
        if topk_str == "":
            topk_val = DEFAULT_TOP_K
        else:
            try:
                topk_val = int(topk_str)
            except:
                topk_val = DEFAULT_TOP_K
        thresh_str = input("相似度阈值 (0-1, 回车使用默认 {}): ".format(DEFAULT_SIM_THRESHOLD)).strip()
        if thresh_str == "":
            thresh_val = DEFAULT_SIM_THRESHOLD
        else:
            try:
                thresh_val = float(thresh_str)
            except:
                thresh_val = DEFAULT_SIM_THRESHOLD
        results = query_index_flat(user_input, loaded_index, loaded_questions, loaded_qa_pairs, top_k=topk_val, similarity_threshold=thresh_val)
        if not results:
            print("助手: 未命中高相似度答案（可调整阈值或转人工）。")
        else:
            j = 0
            while j < len(results):
                item = results[j]
                print("\n---\n相似度: {:.3f}\n问题:\n{}\n答案:\n{}\n---".format(item["score"], item["question"], item["answer"]))
                j += 1
        #add_flag = input("是否添加新的 QA 到内存索引？(y/N): ").strip().lower()
        add_flag="n"
        if add_flag == "y":
            print("请输入新问题（支持多行请通过脚本修改 qa_pairs 后重启）：")
            new_q = input("新问题: ")
            print("请输入新答案:")
            new_a = input("新答案: ")
            new_pair = {"question": new_q, "answer": new_a}
            loaded_index, loaded_questions, loaded_qa_pairs = add_qa_flat(loaded_index, loaded_questions, loaded_qa_pairs, [new_pair])
            print("已添加到内存索引（本次启动有效）。")
