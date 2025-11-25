# qa_faiss_cli_memory.py
import sys
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
# Configuration
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
DEVICE = "cpu"
TOP_K = 3
# Initialize model
sentence_model = SentenceTransformer(MODEL_NAME, device=DEVICE)
embedding_dimension = sentence_model.get_sentence_embedding_dimension()
# Predefined QA list (replace or load from file if desired)
qa_pairs = [
    ("什么是比特币，它如何工作？", '''比特币是一种基于区块链技术的去中心化数字货币，最早由化名中本聪（Satoshi Nakamoto）在 2008 年提出并于 2009 年发布。其设计旨在在无需受信任第三方的情况下实现点对点价值转移。核心要点包括：
- 账户与密钥管理：用户通过椭圆曲线（通常为 secp256k1）生成公私钥对。私钥用于对交易进行数字签名，公钥/地址用于接收资金。私钥泄露即意味着资金丧失控制权。
- UTXO 模型：比特币采用未花费交易输出（UTXO）账本模型。每笔交易将一个或多个 UTXO 作为输入并产生新的 UTXO，交易的有效性需满足签名和金额守恒等规则。
- 共识机制：比特币使用工作量证明（Proof-of-Work, PoW）。矿工通过大量哈希计算寻找满足目标难度的区块头，使得新区块生成具备不可预测性与防篡改成本。网络通过最长（最高累积难度）链规则达成一致。
- 区块结构与链上不可变性：每个区块包含上一区块哈希、Merkle 根（交易集合的哈希摘要）、时间戳、难度目标与 nonce。区块链因链接哈希而增加重写历史的计算成本，保障交易不可逆性随确认数增加。
- 货币发行与通缩机制：比特币的总供应上限为 21,000,000 BTC。区块奖励约每 210,000 个区块发生一次减半（halving），形成稀缺性与长期通缩倾向。
- 扩展性与隐私：链上吞吐受限（TPS 低），为解决延迟与费用问题出现了分片、隔离见证（SegWit）、闪电网络等二层或协议优化手段。链上交易具可审计性，需额外混合或隐私增强方案（如 CoinJoin、CoinSwap 或隐私币）以提高匿名性。
- 安全考量：51% 算力攻击、重放攻击、私钥管理失误、软件漏洞与交易所托管风险是主要威胁。链上分析与监管亦影响隐私与可用性。'''),
    ("比特币的交易确认需要多长时间？", '''比特币的目标出块时间约为 10 分钟，但实际确认时间受网络条件与手续费市场影响。重要考量包括：
- 确认（confirmations）的含义：交易被包含在某个区块即获得 1 次确认；每新增一个后继区块，确认次数加一。确认次数越多，交易被链重写或双重支付回滚的概率越低。
- 安全阈值与实践：常见行业实践将 6 次确认（约 60 分钟）视为高度安全，适用于大额转账或交易所入金；对于小额或低风险交易，1–3 次确认可能被接受；在信任对方的场景下甚至可接受零确认（未包含在区块中的交易），但存在高风险。
- 延迟来源：网络拥堵时 mempool 中交易堆积，矿工优先选择手续费（satoshi/byte）更高的交易打包，低费交易可能长时间滞留。交易传播延迟、节点同步状态以及区块大小限制也会影响确认时间。
- 加速手段：提高手续费以增加被矿工优先打包概率；使用 Replace-By-Fee（RBF）或 Child-Pays-For-Parent（CPFP）策略重新竞价加速确认；采用二层协议（闪电网络）进行即时小额支付以规避链上确认延迟。'''),
    ("高血压的常见危险因素有哪些？", '''高血压（动脉性高血压）是导致心血管疾病、卒中和肾病的主要可修饰危险因素。关键危险因素与其作用机制包括：
- 不可改变量：年龄（血管顺应性下降、动脉僵硬增加）、遗传背景/家族史、种族/民族差异（例如部分非裔人群更易早发且病情更严重）。
- 生活方式与代谢因素：超重/肥胖（尤其中心性肥胖通过胰岛素抵抗与炎症通路影响血压）、高钠摄入（影响体液稳态与血容量）、低钾摄入、久坐不动、过量饮酒与吸烟（增加动脉粥样硬化及血管反应性异常）。
- 共病与药物诱因：慢性肾脏病、原发性或继发性内分泌病变（如原发性醛固酮增多症、库欣综合征）、阻塞性睡眠呼吸暂停、甲状腺功能异常等均可直接或间接升高血压。某些药物（如 NSAIDs、部分抗抑郁药、口服避孕药、皮质类固醇、免疫抑制剂）亦会影响血压水平。
- 心理社会因素：长期压力、睡眠不足、低社会经济地位与环境因素（食品可得性、城市化生活方式）与高血压流行相关。
临床管理需基于风险分层：通过生活方式干预（减重、限盐、DASH 饮食、规律有氧运动、限酒、戒烟）、筛查与治疗潜在继发原因、以及基于指南的药物治疗（包括利尿剂、ACE 抑制剂/ARB、钙通道阻滞剂、β 受体阻滞剂等），并监测器官损害指标（心脏、肾脏、视网膜）。'''),
    ("糖尿病患者如何控制餐后血糖？", '''餐后高血糖对糖尿病患者的血管并发症风险和代谢控制有显著影响。以循证与个体化为原则，控制策略包括：
- 营养学干预：通过碳水化合物计量（carbohydrate counting）和分配控制餐时碳水负荷；优选低升糖指数（GI）与高纤维食物（全谷类、豆类、非淀粉蔬菜）；合理搭配蛋白质与健康脂肪以延缓胃排空与葡萄糖吸收；避免液体糖和精制碳水。
- 药物调整：根据个体需要采用速效胰岛素或调整胰岛素剂量/时机；口服降糖药如速效促泌剂（格列奈类）、DPP-4 抑制剂、GLP-1 受体激动剂、SGLT2 抑制剂等可在不同病程与伴随疾病下用于改善餐后血糖控制。胰岛素泵与闭环系统能更精细管理餐时血糖。
- 非药物干预：餐后短时中等强度运动（如餐后 10–30 分钟步行）可显著降低血糖峰值并改善胰岛素敏感性；进餐顺序（先吃蛋白/蔬菜再吃碳水）和分餐（少量多餐）也能降低餐后峰值。
- 监测与个体化：使用连续血糖监测（CGM）或频繁血糖检测分析餐后血糖曲线，依据数据进行饮食与药物微调，注意避免低血糖。目标设定应平衡 HbA1c、空腹与餐后血糖目标并兼顾患者安全与生活质量。
- 综合管理：并发症评估、体重管理、血压与血脂控制以及与营养师或内分泌科协作，采用多学科方法以长期降低心血管与微血管并发症风险。'''),
    ("比特币与其他加密货币（如以太坊）有什么主要区别？", '''比特币与以太坊等其他加密货币在设计目标、协议功能与经济激励上存在显著差异：
- 初衷与定位：比特币主要定位为价值储存与点对点电子现金系统，强调货币属性与安全性；以太坊的设计目标是成为去中心化应用（dApp）与智能合约平台，强调图灵完备的链上计算能力。
- 货币经济学：比特币总量上限为 21,000,000 BTC，采用减半机制控制通胀；以太坊在不同升级阶段调整发行策略（如 EIP-1559 引入基础手续费燃烧机制，合并后采用 PoS 并显著改变发行率），其供应动态更为复杂。
- 共识机制：传统比特币长期使用 PoW（SHA-256）；以太坊在 2022 年“合并”后从 PoW 转向权益证明（Proof-of-Stake, PoS），以降低能耗并改变安全与激励模型。
- 脚本与智能合约：比特币脚本语言是非图灵完备、限制性较强以增强安全性；以太坊支持图灵完备的 EVM（Ethereum Virtual Machine），允许复杂合约与去中心化金融（DeFi）应用运行，但也带来更高的攻击面与合约漏洞风险。
- 可扩展性与生态系统：以太坊生态更侧重 DeFi、NFT、链上治理与跨链互操作性，因而在扩展性、交易费用与用户体验上进行了多个 Layer-2 与分片提案。比特币生态则更多围绕货币层面的二层解决方案（如闪电网络）与跨链桥的保守演进。
- 安全与治理：比特币以保守演进著称，协议变更谨慎以维持共识稳定；以太坊采用更活跃的协议开发与治理路线，频繁通过 EIP 提案改进功能，但这也可能带来不同的中心化与安全权衡。''')
]

# Vectorize only questions and build in-memory index (rebuild every run)
questions = [question for question, _ in qa_pairs]
question_embeddings = sentence_model.encode(questions, convert_to_numpy=True, show_progress_bar=False)
question_embeddings = question_embeddings / (np.linalg.norm(question_embeddings, axis=1, keepdims=True) + 1e-10)
question_embeddings = question_embeddings.astype('float32')
faiss_index = faiss.IndexFlatIP(embedding_dimension)  # inner product on normalized vectors == cosine similarity
faiss_index.add(question_embeddings)
def encode_query_to_embedding(query_text: str) -> np.ndarray:
    embedding = sentence_model.encode([query_text], convert_to_numpy=True, show_progress_bar=False)
    embedding = embedding / (np.linalg.norm(embedding, axis=1, keepdims=True) + 1e-10)
    return embedding.astype('float32')
def retrieve_answers_for_query(query_text: str, top_k: int = TOP_K):
    query_embedding = encode_query_to_embedding(query_text)
    k = min(top_k, len(qa_pairs))
    distances, indices = faiss_index.search(query_embedding, k)
    results = []
    for score, index in zip(distances[0], indices[0]):
        matched_question, matched_answer = qa_pairs[int(index)]
        results.append({"question": matched_question, "answer": matched_answer, "score": float(score)})
    return results
def interactive_loop():
    print("QA CLI (in-memory index, rebuilt each run; type 'q' or 'exit' to quit)")
    try:
        while True:
            user_input = input("\nPlease enter your question: ").strip()
            if user_input.lower() in ("q", "quit", "exit"):
                print("Exiting.")
                break
            if not user_input:
                print("Please enter a non-empty question.")
                continue
            search_results = retrieve_answers_for_query(user_input, top_k=TOP_K)
            print(f"\nTop {len(search_results)} matches:")
            for rank, result in enumerate(search_results, start=1):
                print(f"\n[{rank}] Similarity: {result['score']:.4f}")
                print(f"Matched question: {result['question']}")
                print(f"Answer: {result['answer']}")
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
        sys.exit(0)
if __name__ == "__main__":
    interactive_loop()
