"""
config.py
----------
Central place for every tunable setting used by the Attentiveness Monitor.
Edit the values below (or change them from the GUI, which overwrites
settings.json) to tune sensitivity for your room / camera / lighting.
"""

import json
import os

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
CONFIG_PATH = os.path.join(BASE_DIR, "settings.json")

DEFAULTS = {
    # How many *consecutive* seconds a member must stay "not paying
    # attention" before an inattentiveness event starts counting.
    # Range requested: 5-25 seconds.
    "inattentive_delay_seconds": 7,
    "min_delay_seconds": 5,
    "max_delay_seconds": 25,

    # Head-turn tolerance in degrees.
    "max_yaw_degrees": 35,
    "max_pitch_degrees": 25,

    # Gaze (iris) tolerance -- catches "head straight, eyes to the side"
    # which head-pose alone misses. Value is how far the iris centre can
    # drift from the eye-socket centre (as a fraction of eye width) before
    # it counts as "looking away with the eyes".
    "max_gaze_offset_ratio": 0.35,

    # Eye Aspect Ratio (EAR) below this value = eyes considered closed.
    # This is only the STARTING/fallback value -- each recognized member
    # gets an auto-calibrated personal baseline after a few seconds of
    # attentive tracking, which makes detection far more reliable for
    # people wearing glasses (glasses shift the absolute EAR but not the
    # relative drop when eyes actually close).
    "eye_closed_ratio": 0.19,
    "eye_closed_relative_drop": 0.68,  # eyes "closed" if EAR < 68% of that member's own open-eye baseline

    # How many consecutive seconds of closed eyes count as "drowsy"
    "eyes_closed_seconds": 3,

    # If no face is detected at all for this many seconds, log as "Away".
    "face_missing_seconds": 5,

    # How many continuous seconds an unrecognized face must be present
    # (known/classroom mode only) before it's logged as an unknown-person
    # event. Kept low by default since this is a security-style alert,
    # not a normal attentiveness lapse.
    "unknown_alert_delay_seconds": 3,

    "camera_index": 0,
    "process_width": 640,

    "excel_file": os.path.join(BASE_DIR, "logs", "attentiveness_log.xlsx"),

    "save_snapshots": True,
    "snapshots_dir": os.path.join(BASE_DIR, "logs", "snapshots"),

    # ---- Recognition / registration ----
    # "unknown": open room, people are just tracked as Member 1, Member 2...
    #            (no roster needed; you can still register someone on the
    #            fly with a snapshot).
    # "known":   closed classroom -- every face is matched against the
    #            trained roster. Anyone who doesn't match is flagged as
    #            an "Unknown person" alert (e.g. someone sitting in for
    #            a registered student).
    "mode": "unknown",

    "dataset_dir": os.path.join(BASE_DIR, "dataset"),
    "model_path": os.path.join(BASE_DIR, "trained_model.yml"),
    "labels_path": os.path.join(BASE_DIR, "labels.json"),

    # LBPH confidence: LOWER = more similar. Below this = recognized;
    # at/above this = "Unknown". Typical usable range ~40-75; start
    # around 65 and tighten (lower) it if you get false-accepts.
    "recognition_confidence_threshold": 65,

    # How many face images to capture per person during Train/Register.
    "images_per_registration": 40,
}


def load_config() -> dict:
    """Load settings.json if present, otherwise fall back to DEFAULTS.
    Missing keys are backfilled from DEFAULTS so old settings files still work."""
    cfg = DEFAULTS.copy()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
