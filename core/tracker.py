"""
tracker.py
----------
A lightweight centroid tracker so each person in the room keeps the same
"Member ID" across frames, instead of being re-detected as a new person
every frame. This is intentionally simple (no external dependencies like
dlib's correlation tracker) so the whole project stays pip-installable.
"""

import math


class CentroidTracker:
    def __init__(self, max_distance=80, max_missed_frames=20):
        self.next_id = 1
        self.objects = {}          # id -> (cx, cy)
        self.missed = {}           # id -> consecutive frames not matched
        self.max_distance = max_distance
        self.max_missed_frames = max_missed_frames

    def update(self, detections):
        """
        detections: list of (x, y, w, h) face boxes for the current frame.
        Returns: dict {member_id: (x, y, w, h)} matched for this frame.
        """
        input_centroids = [(x + w / 2, y + h / 2) for (x, y, w, h) in detections]

        if not self.objects:
            result = {}
            for i, box in enumerate(detections):
                mid = self.next_id
                self.next_id += 1
                self.objects[mid] = input_centroids[i]
                self.missed[mid] = 0
                result[mid] = box
            return result

        object_ids = list(self.objects.keys())
        object_centroids = [self.objects[oid] for oid in object_ids]

        # Greedy nearest-neighbour matching (fine for small meeting-room counts)
        unmatched_inputs = set(range(len(input_centroids)))
        matched_ids = {}

        for oid, ocentroid in zip(object_ids, object_centroids):
            best_idx, best_dist = None, self.max_distance
            for idx in unmatched_inputs:
                d = math.dist(ocentroid, input_centroids[idx])
                if d < best_dist:
                    best_dist, best_idx = d, idx
            if best_idx is not None:
                matched_ids[oid] = best_idx
                unmatched_inputs.discard(best_idx)

        result = {}
        for oid, idx in matched_ids.items():
            self.objects[oid] = input_centroids[idx]
            self.missed[oid] = 0
            result[oid] = detections[idx]

        # Age out objects that weren't matched this frame
        for oid in object_ids:
            if oid not in matched_ids:
                self.missed[oid] = self.missed.get(oid, 0) + 1
                if self.missed[oid] > self.max_missed_frames:
                    del self.objects[oid]
                    del self.missed[oid]

        # Register any leftover detections as new members
        for idx in unmatched_inputs:
            mid = self.next_id
            self.next_id += 1
            self.objects[mid] = input_centroids[idx]
            self.missed[mid] = 0
            result[mid] = detections[idx]

        return result
