"""
backend/hmi/verifier.py
Visual comparison of HMI screenshots against baselines using numpy pixel diff.
"""

from __future__ import annotations

from typing import Optional

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from PIL import Image, ImageChops
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def compare_images(actual, baseline, threshold: float = 0.95) -> dict:
    """
    Compare two PIL Images. Returns match result with score.
    score = 1.0 means identical, 0.0 means completely different.
    threshold: minimum score to consider a match.
    """
    if not NUMPY_AVAILABLE or not PIL_AVAILABLE:
        raise RuntimeError("numpy and Pillow required: pip install numpy pillow")

    # Resize actual to match baseline if needed
    if actual.size != baseline.size:
        actual = actual.resize(baseline.size, Image.LANCZOS)

    # Convert to numpy arrays
    arr_actual = np.array(actual.convert("RGB"), dtype=np.float32)
    arr_baseline = np.array(baseline.convert("RGB"), dtype=np.float32)

    # Compute mean absolute difference per pixel (normalized 0-1)
    diff = np.abs(arr_actual - arr_baseline) / 255.0
    mean_diff = float(np.mean(diff))
    score = 1.0 - mean_diff

    # Generate diff image
    diff_img = ImageChops.difference(actual.convert("RGB"), baseline.convert("RGB"))

    return {
        "match": score >= threshold,
        "score": round(score, 4),
        "threshold": threshold,
        "mean_diff": round(mean_diff, 4),
        "actual_size": list(actual.size),
        "baseline_size": list(baseline.size),
    }


def compare_images_by_name(actual, baseline_name: str, threshold: float = 0.95) -> dict:
    """Compare a PIL Image against a named baseline file."""
    from backend.hmi.capturer import load_baseline
    try:
        baseline = load_baseline(baseline_name)
        return compare_images(actual, baseline, threshold)
    except FileNotFoundError:
        return {
            "match": False,
            "score": 0.0,
            "threshold": threshold,
            "error": f"Baseline '{baseline_name}' not found. Run a baseline capture first.",
        }
