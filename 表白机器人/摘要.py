#pip install transformers torch


# 引入所需的库
from transformers import BartForConditionalGeneration, BartTokenizer

# 加载预训练的BART模型和tokenizer
model_name = "facebook/bart-large-cnn"  # 这是用于摘要的BART模型
model = BartForConditionalGeneration.from_pretrained(model_name)
tokenizer = BartTokenizer.from_pretrained(model_name)

# 输入长文本，作为需要生成摘要的文本
text = """
Hugging Face 是一个致力于自然语言处理（NLP）技术的公司。它开源了多种模型，供研究人员和开发者使用。特别是在预训练模型和转移学习领域，Hugging Face 在推动 NLP 发展方面做出了巨大贡献。它的 transformers 库支持多种语言模型，包括 BERT、GPT、T5 等。开发者可以通过简单的 API 使用这些模型，并在其基础上进行微调，以便完成各种任务，包括文本分类、摘要生成、问答系统等。Hugging Face 的目标是让机器学习更加普及，并使得每个开发者都能在自己的应用中使用最先进的模型。该公司提供了许多免费的资源，包括模型、数据集和教学材料，帮助更多的人进入人工智能领域。
"""

# 对输入文本进行编码（将文本转化为模型可以理解的token格式）
inputs = tokenizer([text], max_length=1024, return_tensors="pt", truncation=True)

# 使用BART模型生成摘要
summary_ids = model.generate(
    inputs["input_ids"],           # 输入的编码
    max_length=150,                # 设置摘要的最大长度
    min_length=50,                 # 设置摘要的最小长度
    length_penalty=2.0,            # 设置摘要生成的长度惩罚（鼓励更长或更短的摘要）
    num_beams=4,                   # 设置束搜索的宽度，增加生成质量
    early_stopping=True            # 当生成的摘要满足条件时提前停止
)

# 解码生成的摘要（将模型输出的token转换为可读的文本）
summary = tokenizer.decode(summary_ids[0], skip_special_tokens=True)

# 打印原文和生成的摘要
print(f"原文:\n{text}\n")
print("\n生成的摘要:\n", summary)
