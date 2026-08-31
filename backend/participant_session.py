"""
participant_session.py
------------------------
In the meeting system, every participant streams frames from THEIR OWN
camera (not one shared classroom camera), so each participant gets their
own ParticipantAnalyzer -- but they all share the ONE roster-wide
FaceRecognizer (thread-safe, see core/face_recognizer.py) so recognition
is consistent across everyone.

This class is deliberately a thin adapter: all the actual detection math
(head pose, iris gaze, eye-closure, debounce timing, real-duration
logging) is the exact same core/attention_detector.py and
core/attention_state.py used everywhere else in this project. What's new
here is repurposing two existing mechanisms for the meeting-specific
requirements:

  1. IMPERSONATION CHECK ("someone else is in XYZ's seat"): when a
     participant joins, they claim to be a specific roster identity
     (either by registering fresh, or picking their name from the
     dropdown). Every frame, the primary (largest) face is recognized and
     compared against that CLAIM. AttentionStateMachine.report_identity()
     already does exactly the debounced "is this face matched?" timing
     the old classroom "unknown mode" used -- here it's just fed
     (recognized_label_id == claimed_label_id) instead of
     (recognized_label_id is not None), so the same one-shot-per-mismatch
     alert logic becomes an impersonation detector for free.

  2. EXTRA PERSON PRESENT ("someone else is sitting next to XYZ"): any
     face in the frame besides the primary one is fed into
     AttentionStateMachine.report() as a plain reason
     ("Extra person present"), reusing the exact same 5-25s debounce +
     immediate-notify + real-duration-on-recovery machinery that already
     handles "Looking away" / "Eyes closed". No new timing logic needed.
"""

import os

from core.attention_detector import AttentionDetector
from core.attention_state import AttentionStateMachine
from core import association

REASON_LOOKING_AWAY = "Looking away"
REASON_EYES_CLOSED = "Eyes closed / drowsy"
REASON_AWAY_FROM_CAMERA = "Away from camera"
REASON_EXTRA_PERSON = "Extra person present"


class ParticipantAnalyzer:
    def __init__(self, participant_id, claimed_label_id, claimed_name, recognizer, cfg,
                 on_threshold_crossed=None, on_attentiveness_event=None,
                 on_impersonation=None, on_extra_person_event=None):
        self.participant_id = participant_id
        self.claimed_label_id = claimed_label_id
        self.claimed_name = claimed_name
        self.recognizer = recognizer
        self.cfg = cfg

        self.detector = AttentionDetector(
            max_yaw=cfg["max_yaw_degrees"],
            max_pitch=cfg["max_pitch_degrees"],
            max_gaze_offset=cfg["max_gaze_offset_ratio"],
        )

        self._on_attentiveness_event = on_attentiveness_event
        self._on_impersonation = on_impersonation
        self._on_extra_person_event = on_extra_person_event

        self._external_on_threshold_crossed = on_threshold_crossed
        self.state_machine = AttentionStateMachine(
            delay_seconds=cfg["inattentive_delay_seconds"],
            face_missing_seconds=cfg["face_missing_seconds"],
            unknown_alert_delay=cfg["unknown_alert_delay_seconds"],
            on_event=self._handle_reason_event,
            on_unknown=self._handle_impersonation,
            on_threshold_crossed=self._handle_threshold_crossed,
        )

        self.snapshots_dir = os.path.abspath(cfg["snapshots_dir"])
        self.last_frame = None
        self.last_recognized_meta = None
        self.last_status = "Attentive"
        self._primary_box = None
        self._extra_face_box = None
        # Snapshot taken the INSTANT the extra-person threshold crosses,
        # while they're still in frame -- reused at recovery time, when
        # they've typically already left frame and there's nothing left to
        # crop from the current frame.
        self._extra_person_snapshot = ("", "")
        self.closed = False

    def close(self):
        if not self.closed:
            self.detector.close()
            self.closed = True

    def update_delay(self, seconds):
        self.state_machine.update_delay(seconds)

    # ------------------------------------------------------------ events
    def _handle_threshold_crossed(self, key, reason, start_ts, elapsed):
        """Fires the INSTANT a reason crosses the delay threshold -- while
        the frame/box are still valid, so this is where snapshots for
        'Extra person present' get captured (by the time recovery fires,
        the extra person has typically already left frame)."""
        if reason == REASON_EXTRA_PERSON and self.last_frame is not None:
            face_path, full_path = association.save_unknown_snapshots(
                self.last_frame, self._extra_face_box or (0, 0, 0, 0),
                self.snapshots_dir, unknown_label=self.participant_id,
            )
            self._extra_person_snapshot = (face_path, full_path)
        if self._external_on_threshold_crossed:
            self._external_on_threshold_crossed(key, reason, start_ts, elapsed)

    def _handle_reason_event(self, key, reason, start_ts, duration):
        """Fires at RECOVERY with the real total duration, for both
        attentiveness reasons AND 'Extra person present'."""
        if reason == REASON_EXTRA_PERSON:
            face_path, full_path = self._extra_person_snapshot
            self._extra_person_snapshot = ("", "")
            if self._on_extra_person_event:
                self._on_extra_person_event(
                    self.participant_id, self.claimed_name, duration, start_ts, face_path, full_path,
                )
        else:
            if self._on_attentiveness_event:
                self._on_attentiveness_event(
                    self.participant_id, self.claimed_name, self.claimed_label_id, reason, start_ts, duration,
                )

    def _handle_impersonation(self, key, duration):
        """Fires once the recognized face has continuously MISMATCHED the
        claimed identity for unknown_alert_delay_seconds."""
        face_path, full_path = "", ""
        if self.last_frame is not None and self._primary_box is not None:
            face_path, full_path = association.save_unknown_snapshots(
                self.last_frame, self._primary_box, self.snapshots_dir,
                unknown_label=f"impersonation-{self.participant_id}",
            )
        if self._on_impersonation:
            self._on_impersonation(
                self.participant_id, self.claimed_name, self.last_recognized_meta, duration, face_path, full_path,
            )

    # -------------------------------------------------------------- core
    def process_frame(self, frame_bgr):
        """Analyzes one frame from this participant's own camera. Returns a
        live status dict for their self-view UI."""
        self.last_frame = frame_bgr
        self._primary_box = None
        self._extra_face_box = None

        readings = self.detector.analyze(frame_bgr)

        if not readings:
            self.state_machine.report(self.participant_id, {REASON_AWAY_FROM_CAMERA})
            self.last_status = "Away from camera"
            return {"status": self.last_status, "recognized": None}

        # Largest face = assumed to be the participant themselves.
        primary = max(readings, key=lambda r: r.box[2] * r.box[3])
        self._primary_box = primary.box
        extra_readings = [r for r in readings if r is not primary]

        recognized_label_id, meta, _conf = (None, None, None)
        if primary.face_crop_gray.size > 0:
            recognized_label_id, meta, _conf = self.recognizer.predict(primary.face_crop_gray)
        self.last_recognized_meta = meta

        matches_claim = recognized_label_id is not None and recognized_label_id == self.claimed_label_id
        self.state_machine.report_identity(self.participant_id, is_known=matches_claim)

        # Eyes/gaze attentiveness, calibrated per-person (same as classroom mode).
        rel_drop = self.cfg["eye_closed_relative_drop"]
        fallback_ear = self.cfg["eye_closed_ratio"]
        baseline = self.state_machine.get_ear_baseline(self.participant_id)
        # Head/gaze movement makes EAR less reliable because the eye landmarks
        # become foreshortened. Prefer a genuine closed-eye signal only when
        # the head is roughly forward and the EAR drop is strong. This prevents
        # turning the head from being mislabeled as "Eyes closed".
        looking_away = primary.looking_away_head or primary.looking_away_gaze
        eye_threshold = baseline * rel_drop if baseline else fallback_ear
        eyes_closed = (primary.ear < eye_threshold) and not primary.looking_away_head
        # Require a stronger drop while gaze is sideways too; iris/gaze motion
        # can temporarily lower EAR without the eyes actually being closed.
        if primary.looking_away_gaze:
            eyes_closed = primary.ear < eye_threshold * 0.82

        reasons = set()
        if looking_away:
            reasons.add(REASON_LOOKING_AWAY)
        elif eyes_closed:
            reasons.add(REASON_EYES_CLOSED)
        if extra_readings:
            reasons.add(REASON_EXTRA_PERSON)
            self._extra_face_box = max((r.box for r in extra_readings), key=lambda b: b[2] * b[3])

        counting = self.state_machine.report(self.participant_id, reasons, ear_value=primary.ear)

        if not matches_claim:
            status = "Identity mismatch"
        elif reasons:
            top_reason = max(counting, key=counting.get) if counting else next(iter(reasons))
            secs = counting.get(top_reason, 0)
            status = f"{top_reason} ({secs:.1f}s)"
        else:
            status = "Attentive"
        self.last_status = status

        return {
            "status": status,
            "recognized": meta,
            "matches_claim": matches_claim,
            "extra_faces": len(extra_readings),
        }
