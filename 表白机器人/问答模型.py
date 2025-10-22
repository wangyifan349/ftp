from transformers import BertForQuestionAnswering, BertTokenizer

# 加载预训练的BERT模型和tokenizer
model_name = "bert-large-uncased-whole-word-masking-finetuned-squad"
model = BertForQuestionAnswering.from_pretrained(model_name)
tokenizer = BertTokenizer.from_pretrained(model_name)

# 定义上下文和问题
context = """新型冠状病毒（SARS-CoV-2）是引起COVID-19的病毒，它首次出现在2019年底的中国武汉市。COVID-19是一种呼吸道疾病，主要通过飞沫传播，可能导致轻度到重度的肺炎，甚至死亡。当前，疫苗已被广泛开发并推向市场，帮助减少病毒传播并降低重症率。不同类型的COVID-19疫苗已经在全球范围内得到批准，并且被广泛用于防控疫情。"""
question = "新冠病毒是什么？"

# 对问题和上下文进行编码
inputs = tokenizer(question, context, return_tensors="pt")

# 使用BERT模型进行问答推理
outputs = model(**inputs)

# 获取答案的起始和结束位置
start_position = outputs.start_logits.argmax()
end_position = outputs.end_logits.argmax()

# 解码获取答案
answer_tokens = inputs['input_ids'][0][start_position:end_position + 1]
answer = tokenizer.decode(answer_tokens)

print("问题:", question)
print("答案:", answer)
