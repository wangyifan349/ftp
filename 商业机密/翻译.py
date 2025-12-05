# translate_loop_no_try.py
import re
from transformers import pipeline
zh_en = pipeline("translation", model="Helsinki-NLP/opus-mt-zh-en")
en_zh = pipeline("translation", model="Helsinki-NLP/opus-mt-en-zh")
def is_chinese(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text))
print('输入文本翻译，输入 "exit" 或 "quit" 退出')
while True:
    txt = input("> ").strip()
    if txt.lower() in {"exit", "quit"}:
        print("已退出。")
        break
    if not txt:
        continue
    translator = zh_en if is_chinese(txt) else en_zh
    result = translator(txt)[0]["translation_text"]
    print(result)
