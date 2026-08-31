"""
face_recognizer.py
--------------------
Wraps OpenCV's LBPH (Local Binary Patterns Histograms) face recognizer.

Why LBPH instead of the more famous `face_recognition`/dlib library:
LBPH ships inside `opencv-contrib-python`, which has prebuilt wheels for
Windows/macOS/Linux with NO compiler/cmake needed. `face_recognition`
needs dlib compiled from source on most student laptops, which is a very
common install failure. LBPH is a little less accurate than a deep
embedding model, but for a classroom-sized roster (tens of students) with
a properly captured training set it works well and installs painlessly.

Folder layout it expects:
  dataset/
    <label_id>/            (label_id is an integer folder name, e.g. "1")
      img_0001.jpg
      img_0002.jpg
      ...

labels.json maps label_id -> student metadata:
  {
    "1": {"name": "Rohan Das", "roll_no": "23CS045", "class": "CSE-B",
          "department": "Computer Science", "year": "4th Year"}
  }
"""

import json
import os
import threading
import cv2
import numpy as np

FACE_SIZE = (200, 200)


class FaceRecognizer:
    def __init__(self, dataset_dir, model_path, labels_path, confidence_threshold=65):
        self.dataset_dir = dataset_dir
        self.model_path = model_path
        self.labels_path = labels_path
        self.confidence_threshold = confidence_threshold
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        self.labels = {}     # str(label_id) -> metadata dict
        self.trained = False
        # Guards the underlying cv2 recognizer + self.labels. Needed once
        # multiple participants' frames are analyzed concurrently (each on
        # its own thread) against this ONE shared, roster-wide recognizer --
        # cv2's LBPH object is not documented as thread-safe for concurrent
        # predict()/train() calls.
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if os.path.exists(self.labels_path):
            with open(self.labels_path, "r") as f:
                self.labels = json.load(f)
        if os.path.exists(self.model_path):
            try:
                self.recognizer.read(self.model_path)
                self.trained = True
            except Exception:
                self.trained = False

    def next_label_id(self):
        """Allocates and reserves the next label id (creates the empty
        dataset folder immediately, while holding the lock) so two people
        registering at the same moment never get the same id."""
        os.makedirs(self.dataset_dir, exist_ok=True)
        with self._lock:
            existing = [int(d) for d in os.listdir(self.dataset_dir) if d.isdigit()]
            new_id = max(existing, default=0) + 1
            os.makedirs(os.path.join(self.dataset_dir, str(new_id)), exist_ok=True)
            return new_id

    def save_registration_images(self, label_id, face_images_gray):
        """face_images_gray: list of grayscale numpy face crops."""
        folder = os.path.join(self.dataset_dir, str(label_id))
        os.makedirs(folder, exist_ok=True)
        start_idx = len(os.listdir(folder))
        for i, img in enumerate(face_images_gray):
            resized = cv2.resize(img, FACE_SIZE)
            cv2.imwrite(os.path.join(folder, f"img_{start_idx + i:04d}.jpg"), resized)

    def register_metadata(self, label_id, name, roll_no, student_class, department, year):
        with self._lock:
            self.labels[str(label_id)] = {
                "name": name,
                "roll_no": roll_no,
                "class": student_class,
                "department": department,
                "year": year,
            }
            with open(self.labels_path, "w") as f:
                json.dump(self.labels, f, indent=2)

    def train(self):
        """(Re)trains the LBPH model on everything currently in dataset_dir."""
        faces, ids = [], []
        if not os.path.exists(self.dataset_dir):
            raise RuntimeError("No dataset found yet. Register at least one person first.")

        for label_folder in sorted(os.listdir(self.dataset_dir)):
            folder_path = os.path.join(self.dataset_dir, label_folder)
            if not os.path.isdir(folder_path) or not label_folder.isdigit():
                continue
            label_id = int(label_folder)
            for fname in os.listdir(folder_path):
                fpath = os.path.join(folder_path, fname)
                img = cv2.imread(fpath, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                faces.append(cv2.resize(img, FACE_SIZE))
                ids.append(label_id)

        if not faces:
            raise RuntimeError("No training images found. Register at least one person first.")

        with self._lock:
            self.recognizer.train(faces, np.array(ids))
            self.recognizer.save(self.model_path)
            self.trained = True
        return len(set(ids)), len(faces)  # (num_people, num_images)

    def predict(self, face_gray):
        """Returns (label_id_or_None, metadata_or_None, confidence).
        label_id is None when unrecognized (confidence too high / not trained)."""
        if not self.trained:
            return None, None, None
        resized = cv2.resize(face_gray, FACE_SIZE)
        with self._lock:
            label_id, confidence = self.recognizer.predict(resized)
            meta = self.labels.get(str(label_id)) if confidence < self.confidence_threshold else None
        if confidence < self.confidence_threshold:
            return label_id, meta, confidence
        return None, None, confidence

    def roster_size(self):
        with self._lock:
            return len(self.labels)

    def roster(self):
        with self._lock:
            return [{"label_id": int(lid), **meta} for lid, meta in self.labels.items()]
