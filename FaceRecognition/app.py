"""
Flask server for Face Recognition using DeepFace (FaceNet model).

This server provides a clean, production-ready face recognition pipeline
for a Smart Attendance System. It uses:
  - FaceNet model for generating face embeddings
  - MTCNN detector for robust face detection
  - Cosine distance metric for comparing embeddings

Dataset Structure:
  dataset/
    person_name/
      img_0000.jpg
      img_0001.jpg
      ...

Student metadata (roll_number, email, classroom) is stored separately
in a CSV file and mapped via person_name as the unique key.

Endpoints:
  POST /api/createdataset/   - Save a student's face image to the dataset
  POST /api/retrainmodel/    - Build/rebuild face embeddings for a classroom
  POST /api/detectface/      - Recognize a face from a webcam frame

Runs on http://127.0.0.1:8000
"""

import os
import io
import base64
import csv
import time
import traceback
import logging

import cv2
import numpy as np
from PIL import Image
from flask import Flask, request, jsonify
from flask_cors import CORS
from deepface import DeepFace

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ─── Configuration ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")          # Training images
STUDENT_CSV = os.path.join(BASE_DIR, "students.csv")      # Metadata mapping

# DeepFace settings — FaceNet + MTCNN as specified by the user
MODEL_NAME = "Facenet"              # FaceNet provides 128-d embeddings
DETECTOR_BACKEND = "mtcnn"          # MTCNN is robust for varied poses/lighting
DISTANCE_METRIC = "cosine"          # Cosine similarity works well with FaceNet

# Recognition threshold (cosine distance)
# FaceNet default is ~0.40.  We relax to 0.50 to reduce "unknown" results
# when only 5-10 training images are available.  Lower = stricter, Higher = more lenient.
THRESHOLD = 0.50

# In-memory state: currently loaded classroom for recognition
current_classroom = {
    "name": None,
    "db_path": None,
}


# ─── Model Preloading ────────────────────────────────────────────────────────
# Pre-build the FaceNet model at startup so that the first API call is fast.
# Without this, DeepFace lazily loads the model on the first .find() call,
# which adds ~5-10 seconds of latency.

def preload_model():
    """
    Force DeepFace to download and cache the FaceNet model weights
    at server startup rather than on the first request.
    """
    logger.info("Preloading FaceNet model... (this may take a moment on first run)")
    try:
        DeepFace.build_model(MODEL_NAME)
        logger.info("FaceNet model loaded successfully!")
    except Exception as e:
        logger.warning(f"Model preload warning (non-fatal): {e}")


# ─── CSV Helpers (Student Metadata) ──────────────────────────────────────────

def ensure_dir(path):
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)


def ensure_student_csv():
    """Create the student CSV file with headers if it doesn't exist."""
    if not os.path.exists(STUDENT_CSV):
        with open(STUDENT_CSV, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "RollNumber", "Email", "ClassroomName"])
        logger.info(f"Created student metadata CSV: {STUDENT_CSV}")


def student_exists_in_csv(name):
    """Check if a student with this name already exists in the CSV."""
    if not os.path.exists(STUDENT_CSV):
        return False
    with open(STUDENT_CSV, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Name"].strip().lower() == name.strip().lower():
                return True
    return False


def add_student_to_csv(name, roll_number, email, classroom_name):
    """
    Add or update a student's metadata in the CSV.
    Uses person_name as the unique key.
    """
    ensure_student_csv()

    # Read all existing rows
    rows = []
    if os.path.exists(STUDENT_CSV):
        with open(STUDENT_CSV, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    # Check if student already exists — update if so
    found = False
    for row in rows:
        if row["Name"].strip().lower() == name.strip().lower():
            row["RollNumber"] = roll_number
            row["Email"] = email
            row["ClassroomName"] = classroom_name
            found = True
            break

    if not found:
        rows.append({
            "Name": name,
            "RollNumber": roll_number,
            "Email": email,
            "ClassroomName": classroom_name,
        })

    # Write back
    with open(STUDENT_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Name", "RollNumber", "Email", "ClassroomName"])
        writer.writeheader()
        writer.writerows(rows)


def get_student_by_name(name):
    """
    Look up a student's full details from the CSV by person_name.
    Returns dict with name, roll_number, email, classroom_name or None.
    """
    if not os.path.exists(STUDENT_CSV):
        return None
    with open(STUDENT_CSV, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Name"].strip().lower() == name.strip().lower():
                return {
                    "name": row["Name"].strip(),
                    "roll_number": row["RollNumber"].strip(),
                    "email": row["Email"].strip(),
                    "classroom_name": row["ClassroomName"].strip(),
                }
    return None


def get_all_students_for_classroom(classroom_name):
    """Get all students belonging to a specific classroom."""
    students = []
    if not os.path.exists(STUDENT_CSV):
        return students
    with open(STUDENT_CSV, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["ClassroomName"].strip().lower() == classroom_name.strip().lower():
                students.append(row["Name"].strip())
    return students


# ─── Image Helpers ────────────────────────────────────────────────────────────

def decode_base64_image(image_data):
    """
    Decode a base64-encoded image string to a numpy array (BGR).
    Handles both raw base64 and data URI format (data:image/jpeg;base64,...).
    """
    # Strip data URI prefix if present
    if "," in image_data:
        image_data = image_data.split(",")[1]
    image_bytes = base64.b64decode(image_data)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    # Convert PIL Image to OpenCV BGR format
    img_array = np.array(image)
    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    return img_bgr


# ─── Endpoint 1: Create Dataset ──────────────────────────────────────────────

@app.route("/api/createdataset/", methods=["POST"])
def create_dataset():
    """
    Save a student's face image to the dataset.

    The image is saved under: dataset/{person_name}/img_XXXX.jpg
    The student metadata (roll_number, email, classroom_name) is saved
    separately in students.csv with person_name as the key.

    Expects JSON:
      - name: str              (used as folder name / unique key)
      - roll_number: str
      - email: str
      - classroom_name: str
      - image: str             (base64 encoded webcam frame)

    Returns:
      - message: str
      - total_images: int      (number of images saved for this student)
    """
    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        roll_number = data.get("roll_number", "").strip()
        email = data.get("email", "").strip()
        classroom_name = data.get("classroom_name", "").strip()
        image_data = data.get("image", "")

        # ── Validate required fields ──
        if not all([name, roll_number, email, classroom_name, image_data]):
            return jsonify({
                "error": "All fields (name, roll_number, email, classroom_name, image) are required."
            }), 400

        # ── Decode the base64 image ──
        img_bgr = decode_base64_image(image_data)

        # ── Save image to dataset/{person_name}/ ──
        # The folder is named ONLY by person_name (clean for DeepFace training)
        student_dir = os.path.join(DATASET_DIR, name)
        ensure_dir(student_dir)

        existing_count = len([
            f for f in os.listdir(student_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ])
        image_path = os.path.join(student_dir, f"img_{existing_count:04d}.jpg")
        cv2.imwrite(image_path, img_bgr)

        total_images = existing_count + 1

        # ── Save metadata to CSV (separate from dataset folders) ──
        add_student_to_csv(name, roll_number, email, classroom_name)

        logger.info(f"[CreateDataset] Saved image #{total_images} for '{name}' (classroom: {classroom_name})")

        return jsonify({
            "message": f"Image saved for {name}",
            "total_images": total_images,
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


# ─── Endpoint 2: Retrain Model ───────────────────────────────────────────────

@app.route("/api/retrainmodel/", methods=["POST"])
def retrain_model():
    """
    Prepare DeepFace for recognition by pointing it at the dataset folder.

    This endpoint:
      1. Filters the dataset to only include students from the given classroom
         (by looking up the CSV).
      2. Clears any cached .pkl representation files so embeddings are rebuilt.
      3. Optionally triggers a DeepFace.find() dry-run to pre-compute embeddings.

    Expects JSON:
      - classroom_name: str

    Returns:
      - message: str
      - students_count: int
    """
    try:
        data = request.get_json()
        classroom_name = data.get("classroom_name", "").strip()

        if not classroom_name:
            return jsonify({"error": "classroom_name is required"}), 400

        if not os.path.exists(DATASET_DIR):
            return jsonify({"error": "No dataset directory found. Please create datasets first."}), 404

        # ── Find which students belong to this classroom ──
        classroom_students = get_all_students_for_classroom(classroom_name)

        if len(classroom_students) == 0:
            return jsonify({"error": f"No students found for classroom '{classroom_name}'"}), 404

        # ── Verify their folders exist in dataset/ ──
        valid_students = []
        for student_name in classroom_students:
            student_dir = os.path.join(DATASET_DIR, student_name)
            if os.path.isdir(student_dir):
                img_count = len([
                    f for f in os.listdir(student_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                ])
                if img_count > 0:
                    valid_students.append(student_name)
                    logger.info(f"  Student '{student_name}': {img_count} images")

        if len(valid_students) == 0:
            return jsonify({"error": "No valid student image folders found in dataset/"}), 404

        # ── Clear cached representations so they are rebuilt fresh ──
        for f in os.listdir(DATASET_DIR):
            if f.startswith("representations_") and f.endswith(".pkl"):
                os.remove(os.path.join(DATASET_DIR, f))
                logger.info(f"[RetrainModel] Removed old cache: {f}")

        # Also clear any per-subfolder caches
        for student_name in valid_students:
            student_dir = os.path.join(DATASET_DIR, student_name)
            for f in os.listdir(student_dir):
                if f.startswith("representations_") and f.endswith(".pkl"):
                    os.remove(os.path.join(student_dir, f))

        # ── Set current classroom context ──
        current_classroom["name"] = classroom_name
        current_classroom["db_path"] = DATASET_DIR

        # ── Pre-compute embeddings by doing a dry-run find ──
        # This builds the representations_*.pkl file so the first real
        # detect call doesn't have a long delay.
        logger.info(f"[RetrainModel] Pre-computing embeddings for {len(valid_students)} students...")
        try:
            # Use a small dummy image (just to trigger embedding generation)
            # We'll use the first image of the first student
            first_student_dir = os.path.join(DATASET_DIR, valid_students[0])
            first_img = None
            for f in os.listdir(first_student_dir):
                if f.lower().endswith((".jpg", ".jpeg", ".png")):
                    first_img = os.path.join(first_student_dir, f)
                    break

            if first_img:
                DeepFace.find(
                    img_path=first_img,
                    db_path=DATASET_DIR,
                    model_name=MODEL_NAME,
                    detector_backend=DETECTOR_BACKEND,
                    distance_metric=DISTANCE_METRIC,
                    enforce_detection=False,
                    silent=True,
                )
                logger.info("[RetrainModel] Embeddings pre-computed and cached successfully!")
        except Exception as embed_err:
            logger.warning(f"[RetrainModel] Embedding pre-computation warning (non-fatal): {embed_err}")

        logger.info(f"[RetrainModel] Ready for classroom '{classroom_name}' with {len(valid_students)} students")

        return jsonify({
            "message": f"Model ready for {classroom_name}",
            "students_count": len(valid_students),
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


# ─── Endpoint 3: Detect Face ─────────────────────────────────────────────────

@app.route("/api/detectface/", methods=["POST"])
def detect_face():
    """
    Recognize a face from a webcam frame against the current dataset.

    This endpoint:
      1. Decodes the base64 webcam frame.
      2. Runs DeepFace.find() to search for the closest match in the dataset.
      3. Returns the recognized student's info or "unknown" / error messages.

    Expects JSON:
      - image: str (base64 encoded webcam frame)

    Returns on success:
      - name: str
      - roll_number: str
      - email: str
      - distance: float         (cosine distance — lower = better match)
      - confidence: float       (percentage — higher = better match)

    Returns on failure:
      - name: "No face detected" / "unknown" / error message
    """
    try:
        # ── Check if a classroom is loaded ──
        if not current_classroom["db_path"]:
            return jsonify({
                "name": "No classroom loaded. Please retrain first.",
                "roll_number": "",
                "email": "",
            }), 200

        data = request.get_json()
        image_data = data.get("image", "")

        if not image_data:
            return jsonify({
                "name": "No image provided",
                "roll_number": "",
                "email": "",
            }), 400

        # ── Decode the webcam frame ──
        img_bgr = decode_base64_image(image_data)

        # ── Save to a temporary file (DeepFace works best with file paths) ──
        temp_path = os.path.join(BASE_DIR, "temp_frame.jpg")
        cv2.imwrite(temp_path, img_bgr)

        try:
            start_time = time.time()

            # ── Run DeepFace.find() against the dataset ──
            results = DeepFace.find(
                img_path=temp_path,
                db_path=current_classroom["db_path"],
                model_name=MODEL_NAME,
                detector_backend=DETECTOR_BACKEND,
                distance_metric=DISTANCE_METRIC,
                enforce_detection=False,     # Don't crash if no face found
                silent=True,
            )

            elapsed = time.time() - start_time
            logger.debug(f"[DetectFace] DeepFace.find() took {elapsed:.2f}s")

            # ── Clean up temp file ──
            if os.path.exists(temp_path):
                os.remove(temp_path)

            # ── Handle multiple faces detected ──
            # results is a list of DataFrames — one per face detected in the input image
            if results and len(results) > 1:
                logger.warning(f"[DetectFace] Multiple faces detected ({len(results)} faces)")
                # We still process the first face but log a warning
                # If you want to reject multi-face frames, uncomment below:
                # return jsonify({
                #     "name": "Multiple faces detected. Please ensure only one face is visible.",
                #     "roll_number": "",
                #     "email": "",
                # }), 200

            # ── Process results ──
            if results and len(results) > 0:
                df = results[0]  # First detected face

                if not df.empty:
                    # Get the best match (lowest distance)
                    best_match = df.iloc[0]
                    distance = float(best_match.get("distance", 1.0))

                    # ── Calculate confidence as a percentage ──
                    # Cosine distance ranges from 0 (identical) to 1 (completely different)
                    # We convert to a confidence score: (1 - distance) * 100
                    confidence = round((1 - distance) * 100, 2)

                    if distance <= THRESHOLD:
                        # ── RECOGNIZED: Extract identity from folder name ──
                        identity_path = best_match["identity"]
                        # Path: dataset/{person_name}/img_0001.jpg
                        person_name = os.path.basename(os.path.dirname(identity_path))

                        # ── Look up full details from CSV ──
                        student_info = get_student_by_name(person_name)

                        if student_info:
                            logger.info(
                                f"[DetectFace] ✅ Recognized: {student_info['name']} "
                                f"(distance: {distance:.4f}, confidence: {confidence}%)"
                            )
                            return jsonify({
                                "name": student_info["name"],
                                "roll_number": student_info["roll_number"],
                                "email": student_info["email"],
                                "distance": distance,
                                "confidence": confidence,
                            }), 200
                        else:
                            # Folder exists but no CSV entry — return what we can
                            logger.warning(
                                f"[DetectFace] Folder match '{person_name}' but no CSV entry found"
                            )
                            return jsonify({
                                "name": person_name,
                                "roll_number": "Not found in database",
                                "email": "Not found in database",
                                "distance": distance,
                                "confidence": confidence,
                            }), 200
                    else:
                        # ── UNKNOWN: Distance too high ──
                        logger.info(
                            f"[DetectFace] ❌ Unknown face (distance: {distance:.4f}, "
                            f"threshold: {THRESHOLD})"
                        )
                        return jsonify({
                            "name": "unknown",
                            "roll_number": "",
                            "email": "",
                            "distance": distance,
                            "confidence": confidence,
                        }), 200

            # ── No face detected at all ──
            logger.info("[DetectFace] No face detected in the frame")
            return jsonify({
                "name": "No face detected",
                "roll_number": "",
                "email": "",
            }), 200

        except ValueError as ve:
            # DeepFace raises ValueError when no face is found with enforce_detection=True
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logger.info(f"[DetectFace] No face in frame: {ve}")
            return jsonify({
                "name": "No face detected",
                "roll_number": "",
                "email": "",
            }), 200

        except Exception as inner_e:
            # Clean up temp file on any error
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise inner_e

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "name": "No face detected",
            "roll_number": "",
            "email": "",
        }), 200


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health_check():
    """Simple health check endpoint."""
    return jsonify({
        "status": "ok",
        "model": MODEL_NAME,
        "detector": DETECTOR_BACKEND,
        "distance_metric": DISTANCE_METRIC,
        "threshold": THRESHOLD,
        "current_classroom": current_classroom["name"],
    }), 200


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ensure_dir(DATASET_DIR)
    ensure_student_csv()

    # Pre-load the FaceNet model so first API call is fast
    preload_model()

    print("=" * 60)
    print("  Smart Attendance — Face Recognition Server (DeepFace)")
    print(f"  Dataset directory : {DATASET_DIR}")
    print(f"  Student CSV       : {STUDENT_CSV}")
    print(f"  Model             : {MODEL_NAME}")
    print(f"  Detector          : {DETECTOR_BACKEND}")
    print(f"  Distance metric   : {DISTANCE_METRIC}")
    print(f"  Threshold         : {THRESHOLD}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8000, debug=True)
