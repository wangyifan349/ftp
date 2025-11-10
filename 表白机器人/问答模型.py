from transformers import BertForQuestionAnswering, BertTokenizer
import torch
import math

# Configuration (English variable names)
MODEL_NAME = "bert-large-uncased-whole-word-masking-finetuned-squad"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
TOP_K = 5                   # number of final candidates to show
MAX_ANSWER_LENGTH = 40      # max tokens allowed in an answer span
MIN_START_LOGIT = None      # optional threshold for start logit (None means disabled)
NULL_SCORE_DIFF_THRESHOLD = -1e9  # threshold for treating top answer as "no answer"

# Load model and tokenizer
model = BertForQuestionAnswering.from_pretrained(MODEL_NAME).to(DEVICE)
tokenizer = BertTokenizer.from_pretrained(MODEL_NAME)

# ---------- choose example: biology or geology ----------
# Default: biology example. Swap/comment blocks to use geology.
context = (
    "Photosynthesis is the process by which green plants, algae, and some bacteria "
    "use sunlight to synthesize nutrients from carbon dioxide and water. It generally "
    "involves the pigment chlorophyll and generates oxygen as a byproduct. "
    "Photosynthesis occurs in chloroplasts in plant cells and can be divided into light-dependent "
    "reactions and the Calvin cycle (light-independent reactions). Light-dependent reactions "
    "capture energy from sunlight, producing ATP and NADPH, which are then used in the Calvin cycle "
    "to fix carbon dioxide into sugars."
)
question = "What is produced as a byproduct of photosynthesis?"

# geology example (uncomment to use)
# context = (
#     "The rock cycle describes the transitions through geologic time among the three main rock types: "
#     "igneous, sedimentary, and metamorphic. Igneous rocks form from the cooling and solidification "
#     "of magma or lava. Sedimentary rocks are formed by deposition and lithification of material, "
#     "often in layered beds. Metamorphic rocks form when existing rocks are subjected to heat and pressure, "
#     "causing physical and chemical changes without melting. Weathering, erosion, and plate tectonics "
#     "drive material through the rock cycle."
# )
# question = "How do igneous rocks form?"

# ---------- encode inputs ----------
inputs = tokenizer.encode_plus(
    question,
    context,
    add_special_tokens=True,
    return_tensors="pt",
    return_token_type_ids=True,
    return_attention_mask=True
)

# move tensors to device
for k in list(inputs.keys()):
    inputs[k] = inputs[k].to(DEVICE)

input_ids = inputs["input_ids"][0]  # tensor of token ids for the single example
tokens = tokenizer.convert_ids_to_tokens(input_ids)

# ---------- forward pass ----------
model.eval()
with torch.no_grad():
    outputs = model(**inputs)  # outputs.start_logits, outputs.end_logits are returned

start_logits = outputs.start_logits[0]  # shape: [seq_len]
end_logits = outputs.end_logits[0]      # shape: [seq_len]

seq_len = input_ids.size(0)
# choose how many top indices to consider for starts and ends (avoid full O(n^2) when long)
top_n = 50 if seq_len >= 50 else seq_len

# get top_n start indices (explicit loop, no list comprehension)
start_scores_and_idx = []
sorted_start_idxs = torch.argsort(start_logits, descending=True)
for i in range(top_n):
    idx = int(sorted_start_idxs[i].item())
    start_scores_and_idx.append((float(start_logits[idx].item()), idx))

# get top_n end indices (explicit loop)
end_scores_and_idx = []
sorted_end_idxs = torch.argsort(end_logits, descending=True)
for i in range(top_n):
    idx = int(sorted_end_idxs[i].item())
    end_scores_and_idx.append((float(end_logits[idx].item()), idx))

# Convert logits to probabilities for start and end (softmax over full sequence for consistency)
start_probs = torch.softmax(start_logits, dim=0).cpu().tolist()
end_probs = torch.softmax(end_logits, dim=0).cpu().tolist()

# collect candidate spans without duplicates
candidates = []  # will contain dicts: {"score":..., "start":..., "end":..., "start_prob":..., "end_prob":...}
seen_spans = set()

for start_score, start_idx in start_scores_and_idx:
    # optional filter by min start logit
    if (MIN_START_LOGIT is not None) and (start_score < MIN_START_LOGIT):
        continue
    for end_score, end_idx in end_scores_and_idx:
        # end must be >= start
        if end_idx < start_idx:
            continue
        length = end_idx - start_idx + 1
        if length > MAX_ANSWER_LENGTH:
            continue
        span_key = (start_idx, end_idx)
        if span_key in seen_spans:
            continue
        seen_spans.add(span_key)
        # combined score: sum of logits (common heuristic)
        combined_logit = start_score + end_score
        # joint probability approximation: start_prob * end_prob (assumes independence; used as intuitive confidence)
        joint_prob = float(start_probs[start_idx] * end_probs[end_idx])
        candidates.append({
            "score": combined_logit,
            "start": start_idx,
            "end": end_idx,
            "start_prob": float(start_probs[start_idx]),
            "end_prob": float(end_probs[end_idx]),
            "joint_prob": joint_prob
        })

if not candidates:
    print("No candidates generated. Check inputs or thresholds.")
    exit(0)

# sort candidates by combined logit descending (explicit loop sorting)
candidates.sort(key=lambda x: x["score"], reverse=True)

# take top TOP_K candidates
top_candidates = []
count = 0
for c in candidates:
    if count >= TOP_K:
        break
    top_candidates.append(c)
    count += 1

# normalize the scores among top candidates to produce relative probabilities (softmax over logits)
score_tensor = torch.tensor([c["score"] for c in top_candidates], dtype=torch.float32)
score_probs = torch.softmax(score_tensor, dim=0).cpu().tolist()

# helper to convert token span to clean string
def clean_text(token_list):
    text = tokenizer.convert_tokens_to_string(token_list)
    return text.strip()

# build answer objects
answers = []
i = 0
for c in top_candidates:
    start_idx = c["start"]
    end_idx = c["end"]
    token_span = tokens[start_idx:end_idx+1]
    answer_text = clean_text(token_span)
    answers.append({
        "rank": i + 1,
        "text": answer_text,
        "score": float(c["score"]),
        "relative_probability": float(score_probs[i]),   # softmax among top candidates
        "joint_probability": float(c["joint_prob"]),     # product of start/end probs
        "start_index": int(start_idx),
        "end_index": int(end_idx)
    })
    i += 1

# decide if top answer should be treated as "no answer"
best_answer = answers[0]
if best_answer["score"] < NULL_SCORE_DIFF_THRESHOLD:
    print("Model returned low confidence / possibly no answer.")
else:
    print(best_answer["text"])
    print(f"Confidence (relative among top candidates): {best_answer['relative_probability']:.4f}")
    print(f"Joint start/end probability: {best_answer['joint_probability']:.6f}\n")

    print("Top candidates:")
    for a in answers:
        print(f'Rank {a["rank"]}: "{a["text"]}"  (score={a["score"]:.4f}, rel_prob={a["relative_probability"]:.4f}, joint_prob={a["joint_probability"]:.6f})')
