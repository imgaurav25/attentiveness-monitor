"""
attention_detector.py
----------------------
Per-frame face analysis:
  1. Detects every face in the frame (MediaPipe Face Mesh, multi-face,
     with iris refinement turned on).
  2. Estimates head pose (yaw / pitch) via solvePnP -> "head turned away?"
  3. Estimates GAZE direction from the iris position relative to the eye
     socket -> catches the case where the head is facing forward but the
     eyes are looking to the side (head-pose alone misses this).
  4. Computes a raw Eye Aspect Ratio (EAR) -> caller (attention_state.py)
     decides "closed" using a per-person calibrated threshold, which is
     what makes this usable for people wearing glasses (glasses shift the
     absolute EAR value but not the relative drop when the eyes close).
  5. Returns one FaceReading per detected face, with a pixel bounding box
     (for tracking) and a grayscale face crop (for the LBPH recognizer).

No frame-to-frame state lives here -- that's attention_state.py. This
module only answers "what does this single frame show for this face?".
"""

from dataclasses import dataclass
import math
import cv2
import mediapipe as mp
import numpy as np

# Landmark indices (MediaPipe Face Mesh, 468/478-point model)
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

# Eye-socket corners used to normalise iris position into a gaze offset
LEFT_EYE_CORNERS = (33, 133)
RIGHT_EYE_CORNERS = (362, 263)

# Iris centre landmarks (only present when refine_landmarks=True)
LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]

POSE_LANDMARKS = {
    "nose_tip": 1,
    "chin": 152,
    "left_eye_corner": 33,
    "right_eye_corner": 263,
    "left_mouth": 61,
    "right_mouth": 291,
}

MODEL_3D_POINTS = np.array([
    (0.0, 0.0, 0.0),
    (0.0, -63.6, -12.5),
    (-43.3, 32.7, -26.0),
    (43.3, 32.7, -26.0),
    (-28.9, -28.9, -24.1),
    (28.9, -28.9, -24.1),
], dtype=np.float64)


@dataclass
class FaceReading:
    box: tuple            # (x, y, w, h) in pixel coords
    yaw: float
    pitch: float
    ear: float             # raw eye aspect ratio (caller applies threshold)
    gaze_offset: float      # 0 = centred, higher = eyes turned to the side
    looking_away_head: bool
    looking_away_gaze: bool
    face_crop_gray: "np.ndarray"  # for face-recognition matching


class AttentionDetector:
    def __init__(self, max_faces=8, max_yaw=35, max_pitch=25, max_gaze_offset=0.35):
        self.max_yaw = max_yaw
        self.max_pitch = max_pitch
        self.max_gaze_offset = max_gaze_offset
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=max_faces,
            refine_landmarks=True,   # enables iris landmarks for gaze tracking
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def close(self):
        self.mesh.close()

    @staticmethod
    def _ear(landmarks, idxs, w, h):
        pts = np.array([(landmarks[i].x * w, landmarks[i].y * h) for i in idxs])
        v1 = np.linalg.norm(pts[1] - pts[5])
        v2 = np.linalg.norm(pts[2] - pts[4])
        h_dist = np.linalg.norm(pts[0] - pts[3])
        if h_dist == 0:
            return 0.3
        return (v1 + v2) / (2.0 * h_dist)

    @staticmethod
    def _gaze_offset_for_eye(landmarks, iris_idxs, corner_idxs, w, h):
        """How far the iris centre is from the eye-socket centre, normalised
        by eye width. ~0 = looking straight ahead through that eye socket."""
        iris_pts = np.array([(landmarks[i].x * w, landmarks[i].y * h) for i in iris_idxs])
        iris_center = iris_pts.mean(axis=0)
        c1 = np.array((landmarks[corner_idxs[0]].x * w, landmarks[corner_idxs[0]].y * h))
        c2 = np.array((landmarks[corner_idxs[1]].x * w, landmarks[corner_idxs[1]].y * h))
        eye_center = (c1 + c2) / 2.0
        eye_width = np.linalg.norm(c1 - c2)
        if eye_width == 0:
            return 0.0
        return float(np.linalg.norm(iris_center - eye_center) / eye_width)

    def _head_pose(self, landmarks, w, h):
        image_points = np.array([
            (landmarks[POSE_LANDMARKS["nose_tip"]].x * w, landmarks[POSE_LANDMARKS["nose_tip"]].y * h),
            (landmarks[POSE_LANDMARKS["chin"]].x * w, landmarks[POSE_LANDMARKS["chin"]].y * h),
            (landmarks[POSE_LANDMARKS["left_eye_corner"]].x * w, landmarks[POSE_LANDMARKS["left_eye_corner"]].y * h),
            (landmarks[POSE_LANDMARKS["right_eye_corner"]].x * w, landmarks[POSE_LANDMARKS["right_eye_corner"]].y * h),
            (landmarks[POSE_LANDMARKS["left_mouth"]].x * w, landmarks[POSE_LANDMARKS["left_mouth"]].y * h),
            (landmarks[POSE_LANDMARKS["right_mouth"]].x * w, landmarks[POSE_LANDMARKS["right_mouth"]].y * h),
        ], dtype=np.float64)

        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1],
        ], dtype=np.float64)
        dist_coeffs = np.zeros((4, 1))

        ok, rotation_vec, _ = cv2.solvePnP(
            MODEL_3D_POINTS, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            return 0.0, 0.0

        rmat, _ = cv2.Rodrigues(rotation_vec)
        sy = math.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        pitch = math.degrees(math.atan2(-rmat[2, 0], sy))
        yaw = math.degrees(math.atan2(rmat[1, 0], rmat[0, 0]))
        return yaw, pitch

    def analyze(self, frame_bgr):
        """Returns a list of FaceReading, one per detected face."""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self.mesh.process(rgb)
        gray_full = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        readings = []
        if not results.multi_face_landmarks:
            return readings

        for face_landmarks in results.multi_face_landmarks:
            landmarks = face_landmarks.landmark
            xs = [lm.x * w for lm in landmarks]
            ys = [lm.y * h for lm in landmarks]
            x_min, x_max = max(0, min(xs)), min(w, max(xs))
            y_min, y_max = max(0, min(ys)), min(h, max(ys))
            box = (int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min))

            yaw, pitch = self._head_pose(landmarks, w, h)
            left_ear = self._ear(landmarks, LEFT_EYE, w, h)
            right_ear = self._ear(landmarks, RIGHT_EYE, w, h)
            ear = (left_ear + right_ear) / 2.0

            try:
                left_gaze = self._gaze_offset_for_eye(landmarks, LEFT_IRIS, LEFT_EYE_CORNERS, w, h)
                right_gaze = self._gaze_offset_for_eye(landmarks, RIGHT_IRIS, RIGHT_EYE_CORNERS, w, h)
                gaze_offset = (left_gaze + right_gaze) / 2.0
            except IndexError:
                # Iris landmarks unavailable for this frame (e.g. eyes fully closed)
                gaze_offset = 0.0

            looking_away_head = abs(yaw) > self.max_yaw or abs(pitch) > self.max_pitch
            # Only trust gaze-based "looking away" when the head is roughly
            # forward -- once the head itself is turned, the head-pose check
            # already covers it, and iris geometry gets unreliable at steep angles.
            looking_away_gaze = (not looking_away_head) and (gaze_offset > self.max_gaze_offset)

            bx, by, bw, bh = box
            face_crop_gray = gray_full[max(0, by):by + bh, max(0, bx):bx + bw]

            readings.append(FaceReading(
                box=box, yaw=yaw, pitch=pitch, ear=ear, gaze_offset=gaze_offset,
                looking_away_head=looking_away_head, looking_away_gaze=looking_away_gaze,
                face_crop_gray=face_crop_gray,
            ))
        return readings
