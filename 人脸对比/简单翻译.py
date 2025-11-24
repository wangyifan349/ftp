# -*- coding: utf-8 -*-
"""
中英互译示例（自动语言检测 + 翻译）
"""
# 安装一次即可：pip install transformers sentencepiece torch langdetect
from transformers import MarianMTModel, MarianTokenizer
from langdetect import detect
import torch
# ------------------- 加载模型 -------------------
zh_en = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-zh-en")
zh_en_tok = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-zh-en")
en_zh = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-en-zh")
en_zh_tok = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-en-zh")
if torch.cuda.is_available():
    zh_en.to("cuda"); en_zh.to("cuda")
# ------------------- 语言检测 -------------------
def detect_lang(txt: str) -> str:
    try:
        return "zh" if detect(txt).startswith("zh") else "en"
    except:
        return "zh"
# ------------------- 翻译函数 -------------------
def translate(txt: str) -> str:
    src = detect_lang(txt)
    if src == "zh":      # 中文→英文
        tok, model = zh_en_tok, zh_en
    else:                # 英文→中文
        tok, model = en_zh_tok, en_zh
    enc = tok.prepare_seq2seq_batch(src_texts=[txt], return_tensors="pt")
    if torch.cuda.is_available():
        enc = {k: v.to("cuda") for k, v in enc.items()}
    with torch.no_grad():
        out = model.generate(**enc, max_length=256)
    return tok.batch_decode(out, skip_special_tokens=True)[0]
# ------------------- 交互循环 -------------------
def main():
    print("中英互译助手（输入 exit 退出）")
    while True:
        try:
            s = input(">>> ").strip()
            if not s: continue
            if s.lower() == "exit": break
            print("翻译结果:", translate(s))
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("错误:", e)
if __name__ == "__main__":
    main()
