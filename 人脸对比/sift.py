import cv2
import numpy as np

# -------------------------------------------------
# Load images and convert to grayscale
# -------------------------------------------------
img1 = cv2.imread('image1.jpg')
img2 = cv2.imread('image2.jpg')
gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

# -------------------------------------------------
# Detect SIFT keypoints and compute descriptors
# -------------------------------------------------
sift = cv2.SIFT_create()
keypoints1, descriptors1 = sift.detectAndCompute(gray1, None)
keypoints2, descriptors2 = sift.detectAndCompute(gray2, None)

# -------------------------------------------------
# Set up FLANN matcher (KD‑Tree)
# -------------------------------------------------
flann_index_params = dict(algorithm=1, trees=5)   # algorithm=1 → KD‑Tree
flann_search_params = dict(checks=50)            # number of checks
flann = cv2.FlannBasedMatcher(flann_index_params, flann_search_params)

# -------------------------------------------------
# Perform k‑NN matching (k=2)
# -------------------------------------------------
knn_matches = flann.knnMatch(descriptors1, descriptors2, k=2)

# -------------------------------------------------
# Apply Lowe's ratio test to filter good matches
# -------------------------------------------------
good_matches = []
ratio_thresh = 0.75
for m, n in knn_matches:
    if m.distance < ratio_thresh * n.distance:
        good_matches.append(m)

print(f'Number of good matches: {len(good_matches)}')

# -------------------------------------------------
# Draw matches and save the result
# -------------------------------------------------
matched_image = cv2.drawMatches(
    img1, keypoints1,
    img2, keypoints2,
    good_matches, None,
    flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS
)

cv2.imwrite('sift_match.jpg', matched_image)
print('Result saved as sift_match.jpg')
