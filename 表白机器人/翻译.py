#!/usr/bin/env python3
# coding: utf-8

"""
双向自动翻译 (中文 <-> 英文) — 使用 transformers.pipeline
- 启动时预加载两个 translation pipeline（zh->en, en->zh）
- 翻译记录追加写入本地日志文件（translations.log）
- 在终端中持续运行，输入空行或 Ctrl+C 退出
"""

import re
from datetime import datetime
from transformers import pipeline

MODEL_ZH_TO_EN = "Helsinki-NLP/opus-mt-zh-en"
MODEL_EN_TO_ZH = "Helsinki-NLP/opus-mt-en-zh"
LOG_PATH = "translations.log"

print("正在创建 translation pipelines，可能需要一些时间，请稍候...")
pipe_zh_en = pipeline("translation", model=MODEL_ZH_TO_EN)
pipe_en_zh = pipeline("translation", model=MODEL_EN_TO_ZH)
print("pipelines 已就绪。")

def detect_direction(text: str) -> str:
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    total = len(text) or 1
    if zh / total >= 0.4:
        return "zh->en"
    if en / total >= 0.4:
        return "en->zh"
    return "zh->en"

def translate_with_pipeline(text: str, direction: str) -> str:
    if direction == "zh->en":
        out = pipe_zh_en(text, max_length=512)
    else:
        out = pipe_en_zh(text, max_length=512)
    return out[0]["translation_text"]

def append_log(path: str, timestamp: str, direction: str, src: str, tgt: str) -> None:
    # 以单行记录保存，替换换行符为 \n，字段使用制表符分隔
    src_safe = src.replace("\n", "\\n")
    tgt_safe = tgt.replace("\n", "\\n")
    line = f"{timestamp}\t{direction}\t{src_safe}\t{tgt_safe}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)

def main():
    try:
        while True:
            user_input = input("输入（空行退出）: ").strip()
            if not user_input:
                print("已退出。")
                break
            direction = detect_direction(user_input)
            translated = translate_with_pipeline(user_input, direction)
            timestamp = datetime.utcnow().isoformat() + "Z"
            append_log(LOG_PATH, timestamp, direction, user_input, translated)
            print(f"方向: {direction}，翻译: {translated}\n")
    except KeyboardInterrupt:
        print("\n已退出（KeyboardInterrupt）。")

if __name__ == "__main__":
    main()
