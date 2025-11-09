# face_compare_run_simple.py
# Run: python face_compare_run_simple.py image1.jpg image2.jpg
#
# Notes:
# - This script uses the face_recognition library (based on dlib) to detect faces
#   and extract 128-d embeddings, then computes L2 distance and cosine similarity
#   to decide whether two images contain the same person.
# - The script does not catch exceptions when opening images or calling the library;
#   errors will be raised directly to help debugging in the CLI.
# - For higher-accuracy face comparison consider the suggestions at the end of the file.
import sys, json
import numpy as np
from PIL import Image
import face_recognition

# Check command-line arguments (script name + two image paths)
if len(sys.argv) != 3:
    print("Usage: python face_compare_run_simple.py image1.jpg image2.jpg")
    sys.exit(1)

# Read the two image paths from command line
path1, path2 = sys.argv[1], sys.argv[2]

# Load images and convert to RGB numpy arrays (Pillow opens the image and ensures RGB,
# avoiding issues with grayscale or alpha channels).
# Note: No exception handling here; if file is missing or not an image an error will be raised.
img1 = np.array(Image.open(path1).convert("RGB"))
img2 = np.array(Image.open(path2).convert("RGB"))

# Detect face locations in each image (returns list of bounding boxes).
# face_recognition defaults to the HOG detector (fast, decent accuracy).
# You can use model="cnn" for higher accuracy (requires dlib with CUDA / GPU).
locs1 = face_recognition.face_locations(img1)
locs2 = face_recognition.face_locations(img2)

# If no face detected in either image, return an error JSON and exit.
if not locs1 or not locs2:
    print(json.dumps({"error": "No face detected. Make sure each image contains a clear face."}, ensure_ascii=False))
    sys.exit(1)

# Compute face embeddings (128-d) for each detected face.
# face_recognition.face_encodings computes one 128-d vector per provided face_location.
encs1 = face_recognition.face_encodings(img1, known_face_locations=locs1)
encs2 = face_recognition.face_encodings(img2, known_face_locations=locs2)

# If embeddings could not be computed, return an error and exit.
if not encs1 or not encs2:
    print(json.dumps({"error": "Failed to extract embeddings."}, ensure_ascii=False))
    sys.exit(1)

# This script takes the first detected face embedding from each image.
# If images may contain multiple faces, adjust selection logic as needed.
emb1 = np.asarray(encs1[0], dtype=np.float64)
emb2 = np.asarray(encs2[0], dtype=np.float64)

# Compute L2 (Euclidean) distance between embeddings.
l2 = float(np.linalg.norm(emb1 - emb2))

# Compute cosine similarity and cosine distance (1 - similarity).
# Cosine similarity measures directional similarity independent of vector magnitude.
norm1 = np.linalg.norm(emb1)
norm2 = np.linalg.norm(emb2)
# If either embedding is a zero vector (very unlikely, might indicate failure), cosine cannot be computed.
if norm1 == 0 or norm2 == 0:
    print(json.dumps({"error": "Embedding is a zero vector; cannot compute cosine similarity."}, ensure_ascii=False))
    sys.exit(1)

cos_sim = float(np.dot(emb1, emb2) / (norm1 * norm2))
cos_dist = 1.0 - cos_sim

# Example decision thresholds:
# - threshold_cosine: cosine similarity threshold (example 0.5). Tune on your validation set.
# - threshold_l2: L2 distance threshold (example 0.6). Tune on your validation set.
threshold_cosine = 0.5
threshold_l2 = 0.6

# Result dictionary includes input paths, similarity metrics, match verdicts, and embedding length.
result = {
  "image1": path1,
  "image2": path2,
  "cosine_similarity": cos_sim,
  "cosine_distance": cos_dist,
  "l2_distance": l2,
  "verdicts": {
    "cosine_match": cos_sim >= threshold_cosine,
    "l2_match": l2 <= threshold_l2
  },
  "emb_length": len(emb1),
  "notes": "Thresholds are example values; tune on your validation set. face_recognition outputs 128-d embeddings."
}

# Print formatted JSON (ensure non-ASCII characters are preserved, if any).
print(json.dumps(result, indent=2, ensure_ascii=False))
