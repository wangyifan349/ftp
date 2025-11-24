# -*- coding: utf-8 -*-
"""
中英互译示例（自动语言检测 + 翻译）
"""
# 安装一次即可：pip install transformers sentencepiece torch langdetect
from transformers import MarianMTModel, MarianTokenizer
from langdetect import detect
import torch
# ------------------- 加载模型 -------------------
zhEnModel = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-zh-en")
zhEnTokenizer = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-zh-en")
enZhModel = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-en-zh")
enZhTokenizer = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-en-zh")
if torch.cuda.is_available():
    zhEnModel.to("cuda")
    enZhModel.to("cuda")
# ------------------- 语言检测 -------------------
def detectLanguage(text: str) -> str:
    try:
        return "zh" if detect(text).startswith("zh") else "en"
    except:
        return "zh"
# ------------------- 翻译函数 -------------------
def translate(text: str) -> str:
    sourceLang = detectLanguage(text)
    if sourceLang == "zh":      # 中文→英文
        tokenizer, model = zhEnTokenizer, zhEnModel
    else:                       # 英文→中文
        tokenizer, model = enZhTokenizer, enZhModel
    encoded = tokenizer.prepare_seq2seq_batch(src_texts=[text], return_tensors="pt")
    if torch.cuda.is_available():
        encoded = {k: v.to("cuda") for k, v in encoded.items()}
    with torch.no_grad():
        generated = model.generate(**encoded, max_length=256)
    return tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
# ------------------- 交互循环 -------------------
def main():
    print("中英互译助手（输入 exit 退出）")
    while True:
        try:
            userInput = input(">>> ").strip()
            if not userInput:
                continue
            if userInput.lower() == "exit":
                break
            print("翻译结果:", translate(userInput))
        except KeyboardInterrupt:
            break
        except Exception as err:
            print("错误:", err)
if __name__ == "__main__":
    main()
