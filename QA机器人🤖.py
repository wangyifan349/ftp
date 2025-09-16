# -*- coding: utf-8 -*-
"""
基于分词级 LCS 与 TF-IDF 加权的问答检索示例（中文）

设计要点（精确说明）：
- 使用 jieba 对输入问题与候选问题做分词，分词后用空格拼接作为 TfidfVectorizer 的输入。
- 使用 TF-IDF 向量捕捉词级语义/关键词重合度，并可选用 TruncatedSVD 将稀疏高维向量降为低维稠密向量以便与 FAISS 一起加速检索。
- 使用分词级最长公共子序列（LCS）衡量两句的词序/结构相似度，LCS 归一化为 lcs_len / max(len(a), len(b))，以避免短句偶然匹配得分过高。
- 最终排名使用线性加权：score = alpha * TFIDF_sim + (1 - alpha) * LCS_sim。TFIDF_sim 采用归一化向量的内积（等价于余弦相似度）。
- 本脚本假设 faiss 已安装（若配置 USE_FAISS=True 且 faiss 未安装，导入会抛出 ImportError），并且不使用 try/except 做动态依赖检测（按你的要求）。
- QA_DICT 中答案为单行字符串（不包含显式换行字符），便于某些存储/传输限制环境。

注意事项与实现细节：
- TfidfVectorizer 使用 lowercase=False，并在外部完成分词（将 tokens 用空格连接），因此 vectorizer 的 token_pattern 仅用于分割已空格分隔的 token。
- TruncatedSVD 的 n_components 被限制为不超过特征数-1（且至少为1），以避免异常。
- 为了用内积表示余弦相似度，所有向量在进入 FAISS 前被归一化为单位向量（L2）。
- LCS 动态规划采用 O(min(n,m)) 空间优化实现以减少内存占用。
- TF-IDF 相似度值被裁剪到 [0, 1] 以增强数值稳定性（FAISS 返回的内积可能有微小数值误差）。
"""

import sys
import math
import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
import faiss
# ---------- 配置 ----------
# 是否启用 FAISS 索引进行近邻检索。若设置为 True 但环境未安装 faiss，将抛出 ImportError。
USE_FAISS = True
# 若为整数则把 TF-IDF 稀疏向量降维到该数；若为 None 则不降维（直接使用稠密化的 TF-IDF 向量）。
# 在特征数很大时，不降维会占用大量内存并降低检索速度。
SVD_DIM = 128
# 返回的候选答案条数（最终按组合相似度排序后截取）
TOP_K = 5
# 若启用 FAISS，先检索的候选数量（FAISS 返回 top K），之后对这些候选再用 LCS 重新排序并截取 TOP_K。
FAISS_CANDIDATES = 50
# 权重参数：最终得分 = alpha * TFIDF_sim + (1-alpha) * LCS_sim
ALPHA = 0.5
# 若为 True，会打印更多调试信息（不影响主流程逻辑）
VERBOSE = False
# ---------- QA 字典（问题 -> 单行答案字符串） ----------
QA_DICT = {
    "我脸上长了痘痘，应该怎么办？":
        "保持面部清洁，避免用手挤压或点按脓包；可尝试非处方外用：过氧化苯甲酰（benzoyl peroxide 2.5–10%，用于炎性痘）或含水杨酸（salicylic acid 0.5–2%）的局部产品；处方药物（需皮肤科医师评估）：外用抗生素如克林霉素（clindamycin 1%凝胶/乳膏）或红霉素（erythromycin）通常与过氧化苯甲酰或维A类联用以降低耐药；中重度或囊肿性痤疮可能需要口服抗生素（常用：四环素类如多西环素 doxycycline 100 mg 或米诺环素 minocycline，短程疗程）或口服异维A酸（isotretinoin，重度或耐药病例，仅在专科监测下使用）。若痘痘反复、化脓严重或伴囊肿样损害，应就医皮肤科。",
    "如何去除黑头？":
        "规律清洁并使用含BHA（水杨酸 salicylic acid 0.5–2%）的产品帮助溶解毛孔油脂；可使用低浓度AHA（如10%以下甘醇酸 glycolic acid）或含酵素的化学去角质以改善角质堆积；可考虑专业治疗：导出、微针、果酸或浅层化学换肤；慎用机械挤压以免感染或留疤，必要时到专业机构由医技人员处理。",
    "皮肤过敏红肿怎么办？":
        "立即停止可疑致敏产品，冷敷可缓解不适；轻度可用温和修复保湿（含神经酰胺 ceramides、甘油 glycerin、泛醇 panthenol）及口服非处方抗组胺药（如氯雷他定 loratadine 或西替利嗪 cetirizine）缓解瘙痒；中重度或伴大片红肿、水疱、呼吸受累应尽快就医，医生可能短期使用外用低强度糖皮质激素或处方强效激素与口服/注射治疗。",
    "补水和保湿的区别是什么？":
        "补水是向皮肤增加水分，常用成分：透明质酸（hyaluronic acid）、甘油（glycerin）；保湿是防止水分流失并修复屏障，常用成分：神经酰胺（ceramides）、脂质类/角鲨烷（squalane）、凡士林或石蜡类封闭剂；推荐做法：先用含透明质酸或甘油的补水精华，再用含神经酰胺或油脂的面霜锁水。",
    "早晚护肤步骤有哪些？":
        "早：洁面-（可选）爽肤水-抗氧化精华（如维生素C 5–20%）-保湿乳/面霜-广谱防晒（SPF30+）；晚：卸妆（如化妆）-洁面-治疗性精华（如视黄醇/retinol 或处方维A酸按医生建议）-保湿。",
    "敏感肌怎么护肤？":
        "选无香料、无酒精、成分表短且低刺激的产品；先在耳后或下颌做斑贴试验；减少活性成分叠加，步骤简单（温和洁面、补水、修复屏障、必要时抗炎产品如低浓度烟酰胺 niacinamide 2–5%）；持续严重不适请就医皮肤科。",
    "毛孔粗大怎么办？":
        "保持清洁并规律去角质（低浓度AHA/BHA）；长期可使用视黄醇（retinol，0.2–1%常见浓度，逐步耐受）促进胶原生成；短期可用含收敛成分（如含金缕梅 witch hazel 或含锌的控油配方）改善外观；严重可咨询医生做激光、射频或果酸换肤等医疗美容。",
    "油皮如何护理？":
        "温和洁面但避免过度清洁造成反跳性出油；使用轻薄非致粉刺（non-comedogenic）保湿剂，如含透明质酸或水杨酸的轻乳液；针对性使用含水杨酸、壬二酸（azelaic acid 10–15%）或低浓度视黄醇控制粉刺；白天使用控油但不干燥的广谱防晒。",
    "干皮怎么补救？":
        "温和滋润洁面，使用含神经酰胺、甘油、透明质酸、角鲨烷等的保湿产品；睡前可用更厚重的修复面霜或封闭性较好的凡士林类产品；避免长时间热水洗脸和高浓度去脂/磨砂产品。",
    "痘印怎么消除？":
        "严格防晒以防色素加重；可用活性成分促进色素代谢与亮白：外用维A类（如视黄醇 retinol 或处方维A酸在医生指导下）、维生素C（L-ascorbic acid 或稳定衍生物）、烟酰胺（niacinamide）或低浓度果酸；医学方法：化学换肤、激光或微针可加速改善，需由专科医生评估。",
    "什么时候需要去看皮肤科？":
        "痤疮化脓、广泛反复发作或出现囊肿、严重过敏反应、疑似皮肤感染（脓液、蜂窝组织炎样改变）、常规外用产品无效或怀疑需要处方药物时应就医皮肤科。",
    "如何正确去角质？":
        "物理去角质（磨砂）应温和，避免每天使用；化学去角质用低浓度AHA（如5–10%）或BHA（0.5–2%水杨酸），初用每周1–2次，观察耐受并注意后续保湿与防晒；有开放性伤口或严重炎症时暂停去角质。",
    "防晒到底要怎么做？":
        "每日涂抹广谱防晒（SPF30+推荐）；脸部用量约0.5毫升（约1/4茶匙）或按每平方厘米2 mg 的原则；每两小时补涂一次，出汗或游泳后应立即补涂；阴天或室内靠近窗时也应注意。",
    "如何选择面霜？":
        "按肤质选：干性选含油脂和封闭性能好的霜状；油性选清爽乳液或凝胶；敏感肌优先温和少香精与致敏成分；查成分表选non-comedogenic配方以降低粉刺风险。",
    "如何判断产品是否致痘？":
        "观察更换产品后2–4周内是否新出现闭口或粉刺明显增多；查看成分表是否含重油脂成分或已知致粉刺成分（如部分矿物油、厚重乳化剂等）；怀疑时停止使用该产品并观察皮损变化。",
    "维生素C（L-抗坏血酸）的作用和使用建议？":
        "作用：抗氧化、抑制酪氨酸酶减少黑色素合成、促进胶原合成与提亮肤色；使用建议：常用浓度5–20%；酸性易氧化，初用者可选稳定衍生物（如magnesium ascorbyl phosphate、sodium ascorbyl phosphate）或从低浓度起步；通常早晨使用可与防晒协同。",
    "视黄醇/类维A（Retinol/处方维A酸）的作用和使用建议？":
        "作用：加速表皮更新、刺激真皮胶原生成、改善细纹、痤疮与色素沉着；使用建议：从低浓度、低频率（如每周1–2次）起步，逐步增加频率；夜间使用并配合保湿以减少脱皮与刺激；孕期应避免使用处方型口服或外用维甲酸类（如tretinoin、isotretinoin）。",
    "烟酰胺（Niacinamide）的作用和使用建议？":
        "作用：增强皮肤屏障、减少经皮水分流失、抗炎降红、抑制黑色素转移有助提亮肤色；使用建议：常见浓度1–5%，耐受性好，可与多数成分共用；少数人出现刺激可分时段使用或降低浓度。",
    "果酸/AHA和水杨酸/BHA的区别？":
        "AHA（如甘醇酸 glycolic acid、乳酸 lactic acid）为水溶性，主要作用于表皮角质层，改善肤质与细纹；BHA（水杨酸 salicylic acid）为油溶性，能进入毛孔溶解油脂，适合油性与粉刺肌；使用时注意浓度、频率并务必防晒。",
    "如何分辨敏感反应与正常的产品反应（如轻微刺痛）？":
        "短暂轻微刺痛（数十秒到数分钟）在使用酸类或视黄醇初期可能可接受；若伴明显红肿、水泡、剧烈疼痛或反应持续并加重，应立即停用并就医；出现泛红但随时间和频率调整后改善，可能为可调整的耐受反应。",
    "孕期和哺乳期能用哪些护肤成分？":
        "避免口服维甲酸类及处方外用高强度维A酸；通常可使用温和保湿剂、低浓度维生素C、烟酰胺及温和果酸（在产科/皮肤科确认下使用）；任何活性成分使用前建议与产科或皮肤科医生确认。",
    "祛痘贴/消炎贴有用吗？":
        "对单个化脓性痘痘局部含吸收与消炎成分的痘贴可短期减少炎症并保护创面；对广泛或重度痤疮不能替代系统治疗，必要时就医。"
}
# ---------- 分词辅助函数 ----------
def jieba_tokenize(text):
    """
    使用 jieba.cut 进行中文分词，返回非空 token 列表。
    说明：保留原始大小写与字符，不进行额外规范化。
    """
    return [tok for tok in jieba.cut(text) if tok.strip()]
def tokenize_for_vectorizer(text):
    """
    将分词结果以空格连接，作为 TfidfVectorizer 的输入格式。
    说明：vectorizer 配置为 lowercase=False，因此分词必须事先完成。
    """
    return " ".join(jieba_tokenize(text))
# ---------- LCS（分词级）相似度 ----------
def lcs_length_tokens(a_tokens, b_tokens):
    """
    计算两个 token 列表的最长公共子序列长度（LCS）。
    实现细节：
    - 使用自右向左迭代的 DP，并把空间复杂度优化到 O(min(n,m)).
    - 返回整数 LCS 长度（以 token 数计）。
    """
    n, m = len(a_tokens), len(b_tokens)
    if n == 0 or m == 0:
        return 0
    # 为保证空间复杂度基于较短序列，交换顺序以便 outer loop 运行在较短序列上
    if n < m:
        shorter, longer = a_tokens, b_tokens
        n, m = n, m
    else:
        shorter, longer = b_tokens, a_tokens
        n, m = m, n
    prev = [0] * (m + 1)
    for i in range(n - 1, -1, -1):
        curr = [0] * (m + 1)
        for j in range(m - 1, -1, -1):
            if shorter[i] == longer[j]:
                curr[j] = 1 + prev[j+1]
            else:
                curr[j] = max(prev[j], curr[j+1])
        prev = curr
    return prev[0]
def lcs_similarity(a, b):
    """
    将 LCS 长度归一化为 [0,1]，归一化分母使用两个句子中更长的 token 数，
    以降低短句偶然匹配导致的高分风险。
    """
    a_toks = jieba_tokenize(a)
    b_toks = jieba_tokenize(b)
    lcs_len = lcs_length_tokens(a_toks, b_toks)
    denom = max(len(a_toks), len(b_toks), 1)
    return lcs_len / denom
# ---------- TF-IDF 向量化与（可选）降维 ----------
questions = list(QA_DICT.keys())
corpus_for_tfidf = [tokenize_for_vectorizer(q) for q in questions]
# Vectorizer 配置说明：
# - lowercase=False：不对 token 做小写化（中文不需要，但可保留英文大小写信息）
# - token_pattern 用于匹配已经以空格分隔的 token（不会做中文自动分词）
vectorizer = TfidfVectorizer(lowercase=False, token_pattern=r"(?u)\b\w+\b")
tfidf_matrix = vectorizer.fit_transform(corpus_for_tfidf)  # (n_questions, n_features), 稀疏矩阵
# 若配置了 SVD_DIM，则把稀疏 TF-IDF 映射到低维稠密向量，便于使用 FAISS 或减少内存占用。
if SVD_DIM is not None:
    n_features = tfidf_matrix.shape[1]
    # n_components 必须小于 n_features，且至少为 1
    n_comp = min(SVD_DIM, max(1, n_features - 1))
    svd = TruncatedSVD(n_components=n_comp)
    dense_matrix = svd.fit_transform(tfidf_matrix)  # (n_questions, n_comp)
else:
    # 直接把稀疏矩阵转成密集数组（当特征数大时会占用大量内存）
    dense_matrix = tfidf_matrix.toarray()
# 将向量类型转为 float32，便于与 FAISS 交互
dense_matrix = dense_matrix.astype('float32')
# L2 归一化：在使用 IndexFlatIP 时，内积等价于余弦相似度
norms = np.linalg.norm(dense_matrix, axis=1, keepdims=True)
norms[norms == 0] = 1.0
dense_norm = dense_matrix / norms
# ---------- 构建 FAISS 索引（若启用） ----------
if USE_FAISS:
    d = dense_norm.shape[1]
    # IndexFlatIP 使用内积作为相似度度量，向量需为单位向量以实现余弦相似度
    index = faiss.IndexFlatIP(d)
    index.add(dense_norm)
else:
    index = None
# ---------- 相似度合并与检索主流程 ----------
def combined_similarity(query, candidate_question, tfidf_sim=None, alpha=ALPHA):
    """
    计算 query 与 candidate_question 的加权相似度。
    - 如果未提供 tfidf_sim，则现场计算 query 的 TF-IDF 向量并与候选向量做余弦相似度。
    - 对 TF-IDF 相似度做数值裁剪以保证在 [0,1] 范围内（提高稳定性）。
    - 返回加权得分（float）。
    """
    if tfidf_sim is None:
        q_vec = vectorizer.transform([tokenize_for_vectorizer(query)])
        if SVD_DIM is not None:
            q_dense = svd.transform(q_vec)
        else:
            q_dense = q_vec.toarray()
        q_dense = q_dense.astype('float32')
        q_norm = q_dense / (np.linalg.norm(q_dense, axis=1, keepdims=True) + 1e-9)
        cand_idx = questions.index(candidate_question)
        cand_vec = dense_norm[cand_idx: cand_idx+1]
        tfidf_sim = float(np.dot(q_norm, cand_vec.T)[0,0])
    # 裁剪 TF-IDF 相似度到 [0,1]
    tfidf_sim = max(0.0, min(1.0, float(tfidf_sim)))
    lcs_sim = lcs_similarity(query, candidate_question)
    return alpha * tfidf_sim + (1.0 - alpha) * lcs_sim
def answer_query(query, top_k=TOP_K, alpha=ALPHA, use_faiss=USE_FAISS, faiss_k=FAISS_CANDIDATES):
    """
    检索流程：
    1) 将 query 分词并构造 TF-IDF 向量（并在需要时做 SVD 降维与归一化）；
    2) 若启用 FAISS：使用归一化后的 query 向量在 FAISS 中检索 top faiss_k 候选及其 TF-IDF 相似度（内积值）；
       否则对所有候选逐一计算 TF-IDF 相似度（适用于问题量较小的场景）；
    3) 对候选集合计算分词级 LCS 相似度，并根据 alpha 加权合并 TF-IDF 与 LCS 得分；
    4) 返回按综合得分排序的 top_k 条目，每条包含 question、answer、score、tfidf_sim、lcs_sim。
    """
    q_tok_str = tokenize_for_vectorizer(query)

    # 1) 通过 FAISS 或全量计算获取候选集合及其 TF-IDF 相似度
    if use_faiss and index is not None:
        q_vec = vectorizer.transform([q_tok_str])
        if SVD_DIM is not None:
            q_dense = svd.transform(q_vec)
        else:
            q_dense = q_vec.toarray()
        q_dense = q_dense.astype('float32')
        q_norm = q_dense / (np.linalg.norm(q_dense, axis=1, keepdims=True) + 1e-9)
        k = min(faiss_k, len(questions))
        D, I = index.search(q_norm, k)  # D: 相似度（内积）数组，I: 索引数组
        cand_indices = [int(i) for i in I[0] if i >= 0]
        # 将 FAISS 返回的内积值映射为 tfidf_sims 字典
        tfidf_sims = {idx: float(D[0, j]) for j, idx in enumerate(cand_indices)}
    else:
        q_vec = vectorizer.transform([q_tok_str])
        if SVD_DIM is not None:
            q_dense = svd.transform(q_vec)
        else:
            q_dense = q_vec.toarray()
        q_dense = q_dense.astype('float32')
        q_norm = q_dense / (np.linalg.norm(q_dense, axis=1, keepdims=True) + 1e-9)
        tfidf_sims = {}
        cand_indices = list(range(len(questions)))
        for idx in cand_indices:
            cand_vec = dense_norm[idx:idx+1]
            tfidf_sims[idx] = float(np.dot(q_norm, cand_vec.T)[0,0])
    # 2) 对候选集合计算 LCS 相似度并合并得分
    scored = []
    for idx in cand_indices:
        q_text = questions[idx]
        tfidf_sim = tfidf_sims.get(idx, None)
        score = combined_similarity(query, q_text, tfidf_sim=tfidf_sim, alpha=alpha)
        scored.append((idx, score, tfidf_sim))
    # 3) 按综合得分排序并返回 top_k（包含各类得分）
    scored.sort(key=lambda x: x[1], reverse=True)
    results = []
    for idx, score, tfidf_sim in scored[:top_k]:
        q_text = questions[idx]
        results.append({
            "question": q_text,
            "answer": QA_DICT[q_text],
            "score": float(score),
            "tfidf_sim": float(tfidf_sim) if tfidf_sim is not None else None,
            "lcs_sim": float(lcs_similarity(query, q_text))
        })
    return results
# ---------- 命令行交互（用于快速测试） ----------
if __name__ == "__main__":
    print("LCS+TF-IDF QA 检索（输入空行退出）")
    while True:
        q = input("请输入问题：").strip()
        if not q:
            break
        res = answer_query(q, top_k=TOP_K, alpha=ALPHA)
        if not res:
            print("未匹配到答案。")
        else:
            for i, r in enumerate(res, 1):
                print(f"候选{i}（综合得分={r['score']:.4f}，tfidf={r['tfidf_sim']:.4f}，lcs={r['lcs_sim']:.4f}）")
                print("问：", r["question"])
                print("答：", r["answer"])
                print("-" * 30)
