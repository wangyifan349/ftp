from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

# 1) Pre-stored QA dictionary (science knowledge examples)
# Keys are questions (strings), values are answer texts (strings).
qa_dict = {
    "What is a light-year?": """A light-year is a unit of distance used in astronomy equal to the distance light travels in vacuum in one year, about 9.46 × 10^12 kilometers.""",
    "Why is the sky blue?": """The sky appears blue because atmospheric molecules scatter shorter wavelengths (blue light) more strongly than longer wavelengths (red light); this phenomenon is called Rayleigh scattering.""",
    "What is the boiling point of water?": """Under standard atmospheric pressure (1 atm), the boiling point of pure water is 100°C (212°F). Higher altitude lowers atmospheric pressure and thus reduces the boiling point.""",
    "How do plants perform photosynthesis?": """Photosynthesis is the process by which plants use light energy to convert carbon dioxide and water into organic compounds (such as glucose) and release oxygen, primarily occurring in chloroplasts with chlorophyll.""",
    "What is a black hole?": """A black hole is an astronomical object predicted by general relativity where mass is concentrated so densely that spacetime is extremely curved and not even light can escape its event horizon."""
}
# 2) Model and vectorization
# Load sentence-transformers model for multilingual semantic embeddings.
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")

# Prepare lists for questions and answers aligned by index.
questions = list(qa_dict.keys())
answers = [qa_dict[q] for q in questions]
# Encode question texts to dense vectors.
# convert_to_numpy=True returns a numpy array; show_progress_bar=False disables progress bar.
embeddings = model.encode(questions, convert_to_numpy=True, show_progress_bar=False)
# Normalize embeddings to unit length for cosine-similarity via inner product.
embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
# Create a FAISS index using inner product (dot product) for similarity search.
dimension = embeddings.shape[1]
index = faiss.IndexFlatIP(dimension)
index.add(embeddings)  # add vectors to the index
# 3) Retrieval function
def retrieve_answers(query, top_k=3, score_threshold=0.35):
    """
    Search the FAISS index for the most similar pre-stored questions.
    Args:
        query (str): User query string to encode and search.
        top_k (int): Number of nearest neighbors to retrieve from FAISS.
        score_threshold (float): Minimum similarity score (inner product) to accept.
    Returns:
        list of dict: Each dict contains:
            - "question": matched question text (str)
            - "answer": corresponding answer text (str)
            - "score": similarity score (float)
    """
    # Encode and normalize the query embedding.
    q_embedding = model.encode([query], convert_to_numpy=True)
    q_embedding = q_embedding / np.linalg.norm(q_embedding, axis=1, keepdims=True)
    # Search the FAISS index. distances contains inner-product scores.
    distances, indices = index.search(q_embedding, top_k)
    results = []
    for score, idx in zip(distances[0], indices[0]):
        # FAISS uses -1 for empty slots when fewer than top_k vectors exist.
        if idx == -1:
            continue
        # Filter out low-similarity results.
        if float(score) < score_threshold:
            continue
        results.append({
            "question": questions[idx],
            "answer": answers[idx],
            "score": float(score)
        })
    return results
# 4) Main interactive loop
def main_loop():
    """
    Run a simple command-line loop to accept user questions, retrieve matches,
    and print the best-matching pre-stored answer.
    """
    print("Enter a question (type 'exit' or 'quit' to leave):")
    while True:
        try:
            user_query = input("\nYour question: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break
        if not user_query:
            print("Please enter a question first.")
            continue
        if user_query.lower() in ("exit", "quit"):
            print("Exiting.")
            break
        # Retrieve candidate matches from the index.
        hits = retrieve_answers(user_query, top_k=3, score_threshold=0.35)
        if not hits:
            # No candidate passed the similarity threshold.
            print("Sorry, no matching pre-stored answers found.")
            continue
        # Use the highest-scoring match.
        best = hits[0]
        # Format the answer string using triple quotes (as in original script).
        answer_text = f'''"""{best["answer"]}"""'''
        # Print matched question, similarity score (rounded), and the answer.
        print("\nMatched question:", best["question"])
        print("Similarity score:", round(best["score"], 4))
        print("Answer:")
        print(answer_text)
if __name__ == "__main__":
    main_loop()
