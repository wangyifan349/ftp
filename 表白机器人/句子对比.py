import torch
from transformers import AutoTokenizer, AutoModel
from sklearn.metrics.pairwise import cosine_similarity
# 定义模型列表，用户可以选择
models = {
    "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "paraphrase-MiniLM-L6-v2": "sentence-transformers/paraphrase-MiniLM-L6-v2",
    "distilbert-base-nli-stsb-mean-tokens": "sentence-transformers/distilbert-base-nli-stsb-mean-tokens",
    "bert-base-nli-mean-tokens": "sentence-transformers/bert-base-nli-mean-tokens"
}
# 提示用户选择模型
print("可选的模型: ")
for idx, model_name in enumerate(models.keys(), 1):
    print(f"{idx}. {model_name}")
model_choice = int(input("\n请选择一个模型 (输入数字): "))
selected_model = list(models.values())[model_choice - 1]
# 加载选择的模型
tokenizer = AutoTokenizer.from_pretrained(selected_model)
model = AutoModel.from_pretrained(selected_model)
# 输入多个句子
print("\n请输入多个句子，每个句子按回车分隔（输入空行结束）:")
sentences = []
while True:
    sentence = input()
    if sentence == "":
        break
    sentences.append(sentence)
# 定义一个函数来获取句子的嵌入
def get_sentence_embedding(sentence):
    # 对句子进行分词
    inputs = tokenizer(sentence, return_tensors='pt', truncation=True, padding=True, max_length=128)
    # 获取模型的输出
    with torch.no_grad():
        outputs = model(**inputs)
    # 获取最后一层的隐藏状态，取[CLS] token的嵌入
    embeddings = outputs.last_hidden_state[:, 0, :]
    return embeddings
# 计算每对句子的余弦相似度
embeddings = {}
for sentence in sentences:
    embeddings[sentence] = get_sentence_embedding(sentence)
similarities = []
# 计算每两句之间的余弦相似度
for i in range(len(sentences)):
    for j in range(i + 1, len(sentences)):
        embedding1 = embeddings[sentences[i]]
        embedding2 = embeddings[sentences[j]]
        # 计算余弦相似度
        cos_sim = cosine_similarity(embedding1.numpy(), embedding2.numpy())
        similarities.append((sentences[i], sentences[j], cos_sim[0][0]))
# 输出相似度
print("\n句子对之间的余弦相似度:")
for sentence1, sentence2, sim in similarities:
    print(f"句子1: {sentence1}\n句子2: {sentence2}\n相似度: {sim:.4f}\n")
