# 安装依赖
# pip install transformers torch

from transformers import MarianMTModel, MarianTokenizer

# 选择中文到韩文的翻译模型
model_name = "Helsinki-NLP/opus-mt-zh-ko"  # 中文到韩文的翻译模型
model = MarianMTModel.from_pretrained(model_name)
tokenizer = MarianTokenizer.from_pretrained(model_name)

# 输入中文文本
text = "你好，今天过得怎么样？"

# 对输入文本进行编码
encoded_text = tokenizer.encode(text, return_tensors="pt")

# 使用模型进行翻译
translated = model.generate(encoded_text, max_length=50)

# 解码翻译后的文本
translated_text = tokenizer.decode(translated[0], skip_special_tokens=True)

# 打印原文和翻译后的文本
print(f"原文: {text}")
print(f"翻译后的文本: {translated_text}")
