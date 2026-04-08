"""
finetune.py — Dataset Preparation & Embedding Pre-computation Script

This script prepares your face recognition dataset for optimal accuracy:

1. DATA AUGMENTATION
   - Creates augmented copies of each training image (brightness, contrast,
     horizontal flip, slight rotation) to artificially increase dataset size.
   - This is critical when you only have 5-6 images per person.

2. FACE ALIGNMENT & QUALITY CHECK
   - Uses MTCNN to detect and extract faces from every image.
   - Saves aligned, cropped face images (removes background noise).
   - Reports any images where no face was detected.

3. EMBEDDING PRE-COMPUTATION
   - Runs DeepFace.find() once to generate the representations_*.pkl cache.
   - This makes the first real detection call much faster.

Usage:
    python finetune.py
    python finetune.py --augment         (run augmentation before embedding)
    python finetune.py --align           (run face alignment/cropping)
    python finetune.py --augment --align (both)

Notes:
    - Run this AFTER creating your dataset (capturing face images).
    - Run this BEFORE using the detection endpoint for best results.
    - The original images are preserved; augmented images are added alongside.
"""

import os
import sys
import argparse
import logging
import traceback

import cv2
import numpy as np
from PIL import Image, ImageEnhance
from deepface import DeepFace

# ─── Configuration ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")

MODEL_NAME = "Facenet"
DETECTOR_BACKEND = "mtcnn"
DISTANCE_METRIC = "cosine"

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Data Augmentation ───────────────────────────────────────────────────────

def augment_image(img_path, output_dir, prefix="aug"):
    """
    Generate augmented versions of a single image to increase dataset size.

    Augmentations applied:
      1. Horizontal flip
      2. Brightness increase (+20%)
      3. Brightness decrease (-20%)
      4. Contrast increase (+30%)
      5. Slight rotation (+10 degrees)
      6. Slight rotation (-10 degrees)

    Args:
        img_path: Path to the original image
        output_dir: Directory to save augmented images
        prefix: Prefix for augmented filenames

    Returns:
        Number of augmented images created
    """
    try:
        img = Image.open(img_path).convert("RGB")
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        count = 0

        # 1. Horizontal flip
        flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
        flipped.save(os.path.join(output_dir, f"{prefix}_{base_name}_flip.jpg"))
        count += 1

        # 2. Brightness increase
        enhancer = ImageEnhance.Brightness(img)
        bright = enhancer.enhance(1.2)
        bright.save(os.path.join(output_dir, f"{prefix}_{base_name}_bright.jpg"))
        count += 1

        # 3. Brightness decrease (simulates dim lighting)
        dim = enhancer.enhance(0.8)
        dim.save(os.path.join(output_dir, f"{prefix}_{base_name}_dim.jpg"))
        count += 1

        # 4. Contrast increase
        enhancer = ImageEnhance.Contrast(img)
        contrast = enhancer.enhance(1.3)
        contrast.save(os.path.join(output_dir, f"{prefix}_{base_name}_contrast.jpg"))
        count += 1

        # 5. Slight rotation +10 degrees
        rotated_pos = img.rotate(-10, resample=Image.BICUBIC, expand=False, fillcolor=(0, 0, 0))
        rotated_pos.save(os.path.join(output_dir, f"{prefix}_{base_name}_rot10.jpg"))
        count += 1

        # 6. Slight rotation -10 degrees
        rotated_neg = img.rotate(10, resample=Image.BICUBIC, expand=False, fillcolor=(0, 0, 0))
        rotated_neg.save(os.path.join(output_dir, f"{prefix}_{base_name}_rot-10.jpg"))
        count += 1

        return count

    except Exception as e:
        logger.error(f"  Error augmenting {img_path}: {e}")
        return 0


def run_augmentation():
    """
    Augment all images in the dataset.
    For each person's folder, augment every original image (skip already-augmented ones).
    """
    logger.info("=" * 50)
    logger.info("STEP 1: DATA AUGMENTATION")
    logger.info("=" * 50)

    if not os.path.exists(DATASET_DIR):
        logger.error(f"Dataset directory not found: {DATASET_DIR}")
        return

    total_augmented = 0
    person_folders = [
        d for d in os.listdir(DATASET_DIR)
        if os.path.isdir(os.path.join(DATASET_DIR, d))
    ]

    for person_name in person_folders:
        person_dir = os.path.join(DATASET_DIR, person_name)

        # Only augment original images (not previously augmented ones)
        original_images = [
            f for f in os.listdir(person_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
            and not f.startswith("aug_")     # Skip already augmented
            and not f.startswith("aligned_") # Skip already aligned
        ]

        if not original_images:
            logger.warning(f"  {person_name}: No images found, skipping")
            continue

        logger.info(f"  {person_name}: Augmenting {len(original_images)} original images...")

        person_augmented = 0
        for img_file in original_images:
            img_path = os.path.join(person_dir, img_file)
            count = augment_image(img_path, person_dir)
            person_augmented += count

        total_augmented += person_augmented
        total_now = len([
            f for f in os.listdir(person_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ])
        logger.info(f"  {person_name}: +{person_augmented} augmented → {total_now} total images")

    logger.info(f"\nAugmentation complete! Created {total_augmented} new images total.")


# ─── Face Alignment & Quality Check ──────────────────────────────────────────

def run_alignment():
    """
    Detect, crop, and align faces in all dataset images.
    This removes background noise and ensures the face occupies most of the frame.
    Bad images (no face detected) are reported.
    """
    logger.info("=" * 50)
    logger.info("STEP 2: FACE ALIGNMENT & QUALITY CHECK")
    logger.info("=" * 50)

    if not os.path.exists(DATASET_DIR):
        logger.error(f"Dataset directory not found: {DATASET_DIR}")
        return

    person_folders = [
        d for d in os.listdir(DATASET_DIR)
        if os.path.isdir(os.path.join(DATASET_DIR, d))
    ]

    bad_images = []

    for person_name in person_folders:
        person_dir = os.path.join(DATASET_DIR, person_name)

        images = [
            f for f in os.listdir(person_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
            and not f.startswith("aligned_")  # Skip already aligned
        ]

        if not images:
            continue

        logger.info(f"  {person_name}: Checking {len(images)} images...")

        good_count = 0
        for img_file in images:
            img_path = os.path.join(person_dir, img_file)
            try:
                # Use DeepFace to extract the face region
                faces = DeepFace.extract_faces(
                    img_path=img_path,
                    detector_backend=DETECTOR_BACKEND,
                    enforce_detection=True,
                    align=True,
                )

                if faces and len(faces) > 0:
                    # Save the aligned face
                    face_array = faces[0]["face"]
                    # DeepFace returns face as float [0,1] — convert to uint8
                    if face_array.max() <= 1.0:
                        face_array = (face_array * 255).astype(np.uint8)
                    face_img = Image.fromarray(face_array)
                    # Resize to a standard size for consistency
                    face_img = face_img.resize((160, 160), Image.LANCZOS)
                    aligned_path = os.path.join(
                        person_dir, f"aligned_{os.path.splitext(img_file)[0]}.jpg"
                    )
                    face_img.save(aligned_path)
                    good_count += 1

            except Exception as e:
                bad_images.append((person_name, img_file, str(e)))
                logger.warning(f"    ⚠ No face detected in {img_file}")

        logger.info(f"  {person_name}: {good_count}/{len(images)} faces extracted successfully")

    if bad_images:
        logger.warning("\n⚠ Images with no detectable face:")
        for person, img, err in bad_images:
            logger.warning(f"  - {person}/{img}")
        logger.info(
            "TIP: Re-capture these images with better lighting, "
            "face centered, and no obstructions."
        )


# ─── Embedding Pre-computation ───────────────────────────────────────────────

def run_embedding_precompute():
    """
    Pre-compute FaceNet embeddings for the entire dataset.
    This creates the representations_*.pkl cache file so that
    the first real detection call is fast.
    """
    logger.info("=" * 50)
    logger.info("STEP 3: PRE-COMPUTING EMBEDDINGS")
    logger.info("=" * 50)

    if not os.path.exists(DATASET_DIR):
        logger.error(f"Dataset directory not found: {DATASET_DIR}")
        return

    # Clear old caches
    for f in os.listdir(DATASET_DIR):
        if f.startswith("representations_") and f.endswith(".pkl"):
            os.remove(os.path.join(DATASET_DIR, f))
            logger.info(f"  Removed old cache: {f}")

    # Find first image to use as the query for dry-run
    first_img = None
    for person_name in os.listdir(DATASET_DIR):
        person_dir = os.path.join(DATASET_DIR, person_name)
        if not os.path.isdir(person_dir):
            continue
        for f in os.listdir(person_dir):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                first_img = os.path.join(person_dir, f)
                break
        if first_img:
            break

    if not first_img:
        logger.error("No images found in dataset! Cannot compute embeddings.")
        return

    logger.info(f"  Building FaceNet model and computing embeddings...")
    logger.info(f"  This may take a few minutes depending on dataset size...")

    try:
        results = DeepFace.find(
            img_path=first_img,
            db_path=DATASET_DIR,
            model_name=MODEL_NAME,
            detector_backend=DETECTOR_BACKEND,
            distance_metric=DISTANCE_METRIC,
            enforce_detection=False,
            silent=True,
        )
        logger.info("  ✅ Embeddings computed and cached successfully!")

        # Count total embeddings
        total_images = 0
        for person_name in os.listdir(DATASET_DIR):
            person_dir = os.path.join(DATASET_DIR, person_name)
            if os.path.isdir(person_dir):
                count = len([
                    f for f in os.listdir(person_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                ])
                total_images += count
                logger.info(f"    {person_name}: {count} images")

        logger.info(f"  Total images indexed: {total_images}")

    except Exception as e:
        logger.error(f"  Error computing embeddings: {e}")
        traceback.print_exc()


# ─── Dataset Statistics ──────────────────────────────────────────────────────

def print_dataset_stats():
    """Print a summary of the current dataset."""
    logger.info("=" * 50)
    logger.info("DATASET SUMMARY")
    logger.info("=" * 50)

    if not os.path.exists(DATASET_DIR):
        logger.error(f"Dataset directory not found: {DATASET_DIR}")
        return

    person_folders = [
        d for d in os.listdir(DATASET_DIR)
        if os.path.isdir(os.path.join(DATASET_DIR, d))
    ]

    if not person_folders:
        logger.info("  No person folders found in dataset/")
        return

    total_images = 0
    for person_name in sorted(person_folders):
        person_dir = os.path.join(DATASET_DIR, person_name)
        images = [
            f for f in os.listdir(person_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        total_images += len(images)

        # Categorize images
        originals = [f for f in images if not f.startswith("aug_") and not f.startswith("aligned_")]
        augmented = [f for f in images if f.startswith("aug_")]
        aligned = [f for f in images if f.startswith("aligned_")]

        logger.info(
            f"  {person_name:20s} | "
            f"Total: {len(images):3d} | "
            f"Original: {len(originals):3d} | "
            f"Augmented: {len(augmented):3d} | "
            f"Aligned: {len(aligned):3d}"
        )

    logger.info(f"\n  Total persons: {len(person_folders)}")
    logger.info(f"  Total images:  {total_images}")

    # Recommendations
    min_images = min(
        len([f for f in os.listdir(os.path.join(DATASET_DIR, p))
             if f.lower().endswith((".jpg", ".jpeg", ".png"))])
        for p in person_folders
    )
    if min_images < 15:
        logger.warning(
            f"\n  ⚠ Minimum images per person: {min_images}. "
            f"Recommended: at least 15-20 for good accuracy."
        )
        logger.info("  TIP: Run 'python finetune.py --augment' to generate more training data.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune and prepare face recognition dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python finetune.py                  Show dataset statistics only
  python finetune.py --augment        Run data augmentation
  python finetune.py --align          Run face alignment & quality check
  python finetune.py --embed          Pre-compute embeddings
  python finetune.py --all            Run everything (augment → align → embed)

Tips for Better Accuracy:
  ● Capture 15-20 images per person (minimum 5)
  ● Include varied angles: front, slight left, slight right
  ● Include varied lighting: normal, dim, bright
  ● Avoid hats, sunglasses, or masks during enrollment
  ● Ensure the face is clearly visible and centered in the frame
  ● Keep a plain background if possible
  ● After augmentation, your dataset will be ~7x larger automatically
        """,
    )
    parser.add_argument("--augment", action="store_true", help="Run data augmentation")
    parser.add_argument("--align", action="store_true", help="Run face alignment & quality check")
    parser.add_argument("--embed", action="store_true", help="Pre-compute embeddings")
    parser.add_argument("--all", action="store_true", help="Run everything")

    args = parser.parse_args()

    print("=" * 50)
    print("  Face Recognition — Dataset Preparation Tool")
    print("=" * 50)

    # Always show stats first
    print_dataset_stats()

    if args.all:
        args.augment = True
        args.align = True
        args.embed = True

    if args.augment:
        run_augmentation()

    if args.align:
        run_alignment()

    if args.embed or args.augment or args.align:
        # Always re-compute embeddings after augmentation or alignment
        run_embedding_precompute()

    if not any([args.augment, args.align, args.embed, args.all]):
        print("\nNo action specified. Use --augment, --align, --embed, or --all.")
        print("Run 'python finetune.py --help' for more info.")


if __name__ == "__main__":
    main()
