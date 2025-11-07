#!/usr/bin/env python3
"""
semantic_faiss_search.py
Purpose:
    Build a semantic search tool that maps an input title to stored articles using
    SentenceTransformers embeddings + FAISS nearest-neighbor search. The script:
      - Provides a small model catalog for user choice.
      - Encodes a pre-stored article corpus into dense vectors (L2-normalized).
      - Builds a FAISS index (IndexIVFFlat or IndexFlatIP for small corpora).
      - Accepts a title string from the user and returns top-K matching articles
        (id, title, score, content) sorted by cosine similarity.
How it works (short):
    1. SentenceTransformer converts texts to embedding vectors.
    2. Embeddings are L2-normalized so that inner product == cosine similarity.
    3. FAISS is used to perform fast nearest-neighbor search on embedding vectors.
       For small corpora, an exact IndexFlatIP is used; for larger corpora an
       IVF index (IndexIVFFlat) is built and trained.
    4. Query title is encoded, searched against the FAISS index, and top results
       above a configurable similarity threshold are printed.
Usage:
    1. Install dependencies (one-line):
       pip install -U sentence-transformers faiss-cpu numpy torch
       If you have a CUDA GPU and want GPU FAISS, install faiss-gpu and adjust
       code accordingly (this script uses faiss-cpu by default).
    2. Put your articles into ARTICLE_DB (list of dicts with 'id','title','content'),
       or modify the script to load from JSON/CSV.
    3. Run:
       python semantic_faiss_search.py
    4. Enter a title when prompted, or type 'quit' to exit.
Author:
    (Example file) - Clean, well-documented reference implementation.
"""
import sys
import os
from typing import List, Dict, Tuple, Optional
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
import faiss
# ----------------------------
# Configuration: Models & Data
# ----------------------------
MODEL_CATALOG = {
    "all-mpnet-base-v2": "High-quality general-purpose multilingual/English embeddings.",
    "all-MiniLM-L6-v2": "Lightweight, fast, suitable for large datasets and limited memory.",
    "paraphrase-multilingual-mpnet-base-v2": "Multilingual model with good performance for Chinese.",
    "all-distilroberta-v1": "Fast and effective for English short-text similarity."
}
# Example article database.
# Replace these entries with your real articles (id, title, content).
ARTICLE_DB: List[Dict] = [
    {"id": 1, "title": "Weather and Travel", "content": "The weather is nice today, perfect for a walk or cycling in the countryside."},
    {"id": 2, "title": "Programming Basics", "content": "Learning programming requires mastering syntax, data structures, and algorithms. Practical projects are important."},
    {"id": 3, "title": "Fruit Nutrition", "content": "Apples contain vitamins and dietary fiber; eating them regularly is beneficial for health."},
    {"id": 4, "title": "Introduction to Machine Learning", "content": "Machine learning includes supervised, unsupervised, and reinforcement learning. Deep learning is a key subfield."},
    {"id": 5, "title": "City Travel Guide", "content": "Cities have many photogenic spots. Walking the old town and exploring local markets is recommended."}
]
# Default parameters
DEFAULT_MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
DEFAULT_NLIST = 100  # number of coarse clusters for IVF; increase for large corpora
DEFAULT_TOP_K = 5
DEFAULT_SCORE_THRESHOLD = 0.25  # cosine similarity threshold (0-1)
# ----------------------------
# Utility functions
# ----------------------------
def choose_device() -> str:
    """Return 'cuda' if GPU available else 'cpu'."""
    return "cuda" if torch.cuda.is_available() else "cpu"
def load_model(model_name: str) -> SentenceTransformer:
    """
    Load a SentenceTransformer model onto the chosen device.
    Raises ValueError if model_name is not in MODEL_CATALOG.
    """
    if model_name not in MODEL_CATALOG:
        raise ValueError(f"Model '{model_name}' not in catalog. Options: {list(MODEL_CATALOG.keys())}")
    device = choose_device()
    print(f"[INFO] Loading model '{model_name}' on device '{device}' ...")
    model = SentenceTransformer(model_name, device=device)
    return model
def encode_texts(model: SentenceTransformer, texts: List[str], normalize: bool = True) -> np.ndarray:
    """
    Encode a list of texts to a numpy array of embeddings (dtype float32).
    If normalize=True, apply L2-normalization row-wise so that inner product == cosine.
    """
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    embeddings = embeddings.astype("float32")
    if normalize:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1e-9
        embeddings = embeddings / norms
    return embeddings
def build_faiss_index(embeddings: np.ndarray, nlist: int = DEFAULT_NLIST) -> faiss.Index:
    """
    Build and return a FAISS index for inner-product search.
    - If number of vectors < nlist, use IndexFlatIP (exact search).
    - Otherwise build IndexIVFFlat with METRIC_INNER_PRODUCT.
    The caller must ensure embeddings are L2-normalized if cosine similarity is desired.
    """
    num_vectors, dim = embeddings.shape
    if num_vectors == 0:
        raise ValueError("No embeddings provided to build the index.")
    if num_vectors < nlist:
        print("[INFO] Using IndexFlatIP (exact search) because dataset is small.")
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)
        return index
    print(f"[INFO] Building IndexIVFFlat with nlist={nlist} (num_vectors={num_vectors}, dim={dim}).")
    # quantizer for IVF must be a flat index
    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    # Training is required for IVF
    index.train(embeddings)
    index.add(embeddings)
    # Set default nprobe (number of inverted lists to search). Tune for performance vs accuracy.
    index.nprobe = max(1, nlist // 10)
    return index
def prepare_index(model: SentenceTransformer,
                  article_db: List[Dict],
                  use_faiss: bool = True,
                  nlist: int = DEFAULT_NLIST) -> Dict:
    """
    Encode article contents, build (or skip) FAISS index, and return a structure:
      {
        "db": article_db,
        "embeddings": numpy array (N x D),
        "faiss_index": faiss.Index or None
      }
    """
    contents = [entry["content"] for entry in article_db]
    embeddings = encode_texts(model, contents, normalize=True)
    faiss_index = None
    if use_faiss:
        faiss_index = build_faiss_index(embeddings, nlist=nlist)
    return {"db": article_db, "embeddings": embeddings, "faiss_index": faiss_index}
def search_title(query_title: str,
                 model: SentenceTransformer,
                 index_struct: Dict,
                 top_k: int = DEFAULT_TOP_K,
                 score_threshold: float = DEFAULT_SCORE_THRESHOLD) -> List[Dict]:
    """
    Search the corpus for the most similar articles to query_title.
    Returns a list of result dicts with keys: id, title, content, score (cosine similarity).
    """
    query_emb = encode_texts(model, [query_title], normalize=True)  # shape: (1, d)
    faiss_index = index_struct.get("faiss_index")
    db = index_struct["db"]
    if faiss_index is not None:
        distances, indices = faiss_index.search(query_emb, top_k)  # distances are inner-products
        distances = distances[0]  # shape (top_k,)
        indices = indices[0]
        results: List[Dict] = []
        for idx, score in zip(indices, distances):
            if idx < 0:
                continue
            score_float = float(score)
            if score_float < score_threshold:
                continue
            item = db[idx].copy()
            item["score"] = score_float
            results.append(item)
        return results
    else:
        # Fallback: compute exact similarities with numpy (embeddings are normalized)
        embeddings = index_struct["embeddings"]  # shape: (N, d)
        sims = np.matmul(query_emb, embeddings.T)[0]  # shape: (N,)
        top_indices = np.argsort(-sims)[:top_k]
        results = []
        for idx in top_indices:
            score = float(sims[idx])
            if score < score_threshold:
                continue
            item = db[idx].copy()
            item["score"] = score
            results.append(item)
        return results
def print_results(results: List[Dict]) -> None:
    """Nicely print the search results to stdout."""
    if not results:
        print("[INFO] No matching articles above the threshold.")
        return
    print(f"[INFO] Found {len(results)} result(s):")
    for r in results:
        print(f"- id={r['id']}  title={r['title']}  score={r['score']:.4f}")
        print(f"  content: {r['content']}")
# ----------------------------
# Main interactive loop
# ----------------------------
def main():
    # 1) Show model catalog
    print("Model catalog (name: description):")
    for name, desc in MODEL_CATALOG.items():
        print(f" - {name}: {desc}")
    print(f"\nDefault model: {DEFAULT_MODEL_NAME}")
    selected_model = DEFAULT_MODEL_NAME
    # Optionally allow passing a model name as first CLI argument
    if len(sys.argv) > 1:
        arg_model = sys.argv[1].strip()
        if arg_model in MODEL_CATALOG:
            selected_model = arg_model
        else:
            print(f"[WARN] CLI model '{arg_model}' not recognized. Using default '{DEFAULT_MODEL_NAME}'.")
    # 2) Load model
    model = load_model(selected_model)
    # 3) Prepare index (use FAISS)
    # If you have a small dataset and prefer exact search, set use_faiss=False.
    index_struct = prepare_index(model, ARTICLE_DB, use_faiss=True, nlist=min(DEFAULT_NLIST, max(1, len(ARTICLE_DB)//2)))
    print("[INFO] Index ready. Enter 'quit' to exit.")
    # 4) Interactive query loop
    try:
        while True:
            user_input = input("\nEnter a title to search (or 'quit' to exit): ").strip()
            if user_input.lower() in ("quit", "exit"):
                print("Exiting.")
                break
            if len(user_input) == 0:
                print("[WARN] Empty input; please type a title or 'quit'.")
                continue
            results = search_title(user_input, model, index_struct, top_k=DEFAULT_TOP_K, score_threshold=DEFAULT_SCORE_THRESHOLD)
            print_results(results)
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
if __name__ == "__main__":
    main()
