"""
association.py
----------------
Handles the "unknown person alongside a registered student" scenario:

  - Given an unknown person's box and the set of currently-recognized
    (registered) faces in the same frame, finds the CLOSEST registered
    student by centroid distance -- not just "the first one" or "always
    the same student". If no registered student is in frame at all, no
    association is made (the event is still logged, just without a
    "nearby student" attached).

  - Saves two images to disk when an unknown-person event qualifies:
      1. a tight crop of just the unknown person's face
      2. the complete camera frame (so a reviewer can see the unknown
         person AND the registered student together, when both are in view)
"""

import math
import os
import time

import cv2


def find_nearest_registered(unknown_box, known_members):
    """
    unknown_box: (x, y, w, h) of the unrecognized face.
    known_members: dict {member_id: {"box": (x, y, w, h), "identity": dict|None}}
                    for every OTHER tracked face in this same frame.

    Returns (member_id, identity_dict, distance_px) for the nearest face
    that IS a matched registered student, or (None, None, None) if no
    registered student is present in this frame at all.
    """
    ux, uy, uw, uh = unknown_box
    ucx, ucy = ux + uw / 2.0, uy + uh / 2.0

    best_id, best_identity, best_dist = None, None, None
    for member_id, info in known_members.items():
        identity = info.get("identity")
        if not identity:
            continue  # only associate with an actual matched, registered student
        x, y, w, h = info["box"]
        cx, cy = x + w / 2.0, y + h / 2.0
        dist = math.hypot(ucx - cx, ucy - cy)
        if best_dist is None or dist < best_dist:
            best_id, best_identity, best_dist = member_id, identity, dist

    return best_id, best_identity, best_dist


def save_unknown_snapshots(frame_bgr, unknown_box, snapshots_dir, unknown_label):
    """
    Saves a face crop and the full frame for an unknown-person event.
    Returns (face_path, full_path) -- either may be None if saving failed
    (e.g. an empty/degenerate crop).
    """
    os.makedirs(snapshots_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    x, y, w, h = unknown_box
    h_frame, w_frame = frame_bgr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_frame, x + w), min(h_frame, y + h)
    face_crop = frame_bgr[y0:y1, x0:x1]

    face_path = None
    if face_crop.size > 0:
        face_path = os.path.join(snapshots_dir, f"unknown_{unknown_label}_{ts}_face.jpg")
        cv2.imwrite(face_path, face_crop)

    full_path = os.path.join(snapshots_dir, f"unknown_{unknown_label}_{ts}_full.jpg")
    cv2.imwrite(full_path, frame_bgr)

    return face_path, full_path
