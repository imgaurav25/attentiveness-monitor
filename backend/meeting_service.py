"""
meeting_service.py
--------------------
Ties together meetings.py (room/participant bookkeeping) and
participant_session.py (per-participant detection) into the API that
backend/server.py exposes over REST + WebSocket.

Deliberately shares the SAME FaceRecognizer, ExcelLogger, and config that
classroom ("Known environment") mode uses (both passed in from the
existing MonitorService) -- registering someone once, in either mode,
makes them recognizable in both, and every event lands in the same
Excel workbook.
"""

import asyncio
import os
import threading
import time
import uuid
from typing import Optional

import cv2
import numpy as np

from core.attention_detector import AttentionDetector
from meetings import MeetingRegistry
from participant_session import ParticipantAnalyzer


def decode_jpeg_b64(b64_data):
    raw = np.frombuffer(__import__("base64").b64decode(b64_data), dtype=np.uint8)
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


class RegistrationSession:
    """A short-lived capture session for someone registering while joining a
    meeting -- frames arrive over their own WebSocket, not a local camera."""
    def __init__(self, token, label_id, meta, target_count):
        self.token = token
        self.label_id = label_id
        self.meta = meta
        self.target_count = target_count
        self.frames = []
        self.detector = AttentionDetector()  # this session's own instance -- safe for concurrent registrations
        self.done = False
        self.lock = threading.Lock()

    def add_frame(self, frame_bgr):
        with self.lock:
            if self.done:
                return self.done
            readings = self.detector.analyze(frame_bgr)
            if readings:
                largest = max(readings, key=lambda r: r.box[2] * r.box[3])
                if largest.face_crop_gray.size > 0:
                    self.frames.append(largest.face_crop_gray.copy())
            if len(self.frames) >= self.target_count:
                self.done = True
        return self.done

    def close(self):
        self.detector.close()


class MeetingService:
    def __init__(self, recognizer, logger, cfg):
        self.recognizer = recognizer
        self.logger = logger
        self.cfg = cfg
        self.registry = MeetingRegistry()

        self.registration_sessions = {}  # token -> RegistrationSession
        self.analyzers = {}              # participant_id -> ParticipantAnalyzer
        self.participant_meeting = {}    # participant_id -> meeting_id

        self.host_websockets = {}        # meeting_id -> list[WebSocket]
        self.selfview_websockets = {}    # participant_id -> WebSocket
        self.meeting_websockets = {}     # meeting_id -> {participant_id: WebSocket} for custom WebRTC signaling

        self.recent_events = {}          # meeting_id -> list of event records (newest first)

        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # ---------------------------------------------------------- meetings
    def create_meeting(self, title=None):
        return self.registry.create_meeting(title=title)

    def get_meeting(self, meeting_id):
        return self.registry.get(meeting_id)

    def roster(self):
        return self.recognizer.roster()

    # ------------------------------------------------- registration flow
    def start_registration(self, meta):
        label_id = self.recognizer.next_label_id()
        token = uuid.uuid4().hex[:16]
        target = self.cfg["images_per_registration"]
        self.registration_sessions[token] = RegistrationSession(token, label_id, meta, target)
        return token, label_id

    def registration_status(self, token):
        sess = self.registration_sessions.get(token)
        if not sess:
            return None
        with sess.lock:
            return {"capturing": not sess.done, "captured": len(sess.frames), "target": sess.target_count}

    def process_registration_frame(self, token, frame_bgr):
        sess = self.registration_sessions.get(token)
        if not sess:
            return {"error": "unknown registration session"}
        done = sess.add_frame(frame_bgr)
        result = {"captured": len(sess.frames), "target": sess.target_count, "done": done}
        if done:
            self.recognizer.save_registration_images(sess.label_id, sess.frames)
            self.recognizer.register_metadata(
                sess.label_id, sess.meta["name"], sess.meta.get("roll_no", ""),
                sess.meta.get("student_class", ""), sess.meta.get("department", ""),
                sess.meta.get("year", ""),
            )
            n_people, n_images = self.recognizer.train()
            sess.close()
            del self.registration_sessions[token]
            result["label_id"] = sess.label_id
            result["trained"] = {"people": n_people, "images": n_images}
        return result

    # ---------------------------------------------------------- joining
    def join_meeting(self, meeting_id, name, claimed_label_id, is_host=False):
        meeting = self.registry.get(meeting_id)
        if not meeting:
            raise ValueError("Meeting not found")

        participant = meeting.add_participant(name, claimed_label_id, is_host=is_host)

        analyzer = ParticipantAnalyzer(
            participant_id=participant.participant_id,
            claimed_label_id=claimed_label_id,
            claimed_name=name,
            recognizer=self.recognizer,
            cfg=self.cfg,
            on_threshold_crossed=self._make_on_threshold_crossed(meeting_id),
            on_attentiveness_event=self._make_on_attentiveness_event(meeting_id),
            on_impersonation=self._make_on_impersonation(meeting_id),
            on_extra_person_event=self._make_on_extra_person_event(meeting_id),
        )
        self.analyzers[participant.participant_id] = analyzer
        self.participant_meeting[participant.participant_id] = meeting_id
        self.recent_events.setdefault(meeting_id, [])
        self.broadcast_participant_presence(meeting_id, "participant_joined", participant)
        return participant

    def leave_meeting(self, participant_id):
        meeting_id = self.participant_meeting.get(participant_id)
        if meeting_id:
            meeting = self.registry.get(meeting_id)
            if meeting:
                participant = meeting.get_participant(participant_id)
                meeting.mark_left(participant_id)
                if participant:
                    self.broadcast_participant_presence(meeting_id, "participant_left", participant)
        analyzer = self.analyzers.pop(participant_id, None)
        if analyzer:
            analyzer.state_machine.flush_all()  # don't lose an in-progress qualifying lapse
            analyzer.close()
        self.selfview_websockets.pop(participant_id, None)

    def process_participant_frame(self, participant_id, frame_bgr):
        analyzer = self.analyzers.get(participant_id)
        if not analyzer:
            return {"error": "not joined"}
        return analyzer.process_frame(frame_bgr)

    def set_delay(self, meeting_id, seconds):
        for pid, mid in self.participant_meeting.items():
            if mid == meeting_id and pid in self.analyzers:
                self.analyzers[pid].update_delay(seconds)


    # ------------------------------------------------------ WebRTC signaling
    def register_meeting_ws(self, meeting_id, participant_id, ws):
        peers = self.meeting_websockets.setdefault(meeting_id, {})
        existing = [pid for pid in peers.keys() if pid != participant_id]
        peers[participant_id] = ws
        return existing

    def unregister_meeting_ws(self, meeting_id, participant_id):
        peers = self.meeting_websockets.get(meeting_id, {})
        peers.pop(participant_id, None)
        if not peers:
            self.meeting_websockets.pop(meeting_id, None)

    def broadcast_signal(self, meeting_id, sender_id, message, target_id=None):
        if not self.loop:
            return
        asyncio.run_coroutine_threadsafe(
            self._broadcast_signal_async(meeting_id, sender_id, message, target_id), self.loop
        )

    async def _broadcast_signal_async(self, meeting_id, sender_id, message, target_id=None):
        peers = self.meeting_websockets.get(meeting_id, {})
        targets = [target_id] if target_id else [pid for pid in peers if pid != sender_id]
        dead = []
        for pid in targets:
            ws = peers.get(pid)
            if not ws:
                continue
            try:
                await ws.send_json({
                    "type": "webrtc_signal",
                    "from": sender_id,
                    "signal": message,
                })
            except Exception:
                dead.append(pid)
        for pid in dead:
            self.unregister_meeting_ws(meeting_id, pid)

    def broadcast_participant_presence(self, meeting_id, event_type, participant):
        if not self.loop:
            return
        asyncio.run_coroutine_threadsafe(
            self._broadcast_presence_async(meeting_id, event_type, participant), self.loop
        )

    async def _broadcast_presence_async(self, meeting_id, event_type, participant):
        peers = self.meeting_websockets.get(meeting_id, {})
        payload = {"type": event_type, "participant": participant.to_dict()}
        for ws in list(peers.values()):
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    # ------------------------------------------------------------ events
    def _record_and_broadcast(self, meeting_id, message):
        events = self.recent_events.setdefault(meeting_id, [])
        events.insert(0, message)
        self.recent_events[meeting_id] = events[:200]
        self._broadcast_to_host(meeting_id, message)

    def _is_self_for_host(self, meeting_id, participant_id):
        meeting = self.registry.get(meeting_id)
        participant = meeting.get_participant(participant_id) if meeting else None
        return bool(participant and participant.is_host)

    def _make_on_threshold_crossed(self, meeting_id):
        def _cb(participant_id, reason, start_ts, elapsed):
            meeting = self.registry.get(meeting_id)
            participant = meeting.get_participant(participant_id) if meeting else None
            who = participant.name if participant else "A participant"
            data = {
                "participant_id": participant_id,
                "who": who,
                "reason": reason,
                "timestamp": start_ts,
                "elapsed": round(elapsed, 1),
                "is_self_for_host": self._is_self_for_host(meeting_id, participant_id),
            }
            message = {"type": "attentiveness_alert", "data": data}
            # Save the alert immediately so the host/admin log contains the
            # participant even if they never recover before leaving.
            identity = self.recognizer.labels.get(str(participant.claimed_label_id)) if participant and participant.claimed_label_id else None
            self.logger.log_meeting_alert(participant_id, who, reason, start_ts, elapsed, identity=identity)
            self._broadcast_to_host(meeting_id, message)
            # Always send the same alert to the affected participant too, even
            # when a host is present.
            self.send_selfview(participant_id, message)
        return _cb

    def _make_on_attentiveness_event(self, meeting_id):
        def _cb(participant_id, name, claimed_label_id, reason, start_ts, duration):
            identity = self.recognizer.labels.get(str(claimed_label_id)) if claimed_label_id else None
            self.logger.log_event(participant_id, reason, start_ts, duration, identity=identity)
            self._record_and_broadcast(meeting_id, {
                "type": "attentiveness_event",
                "data": {"participant_id": participant_id, "who": name, "reason": reason,
                         "timestamp": start_ts, "duration": round(duration, 1)},
            })
        return _cb

    def _make_on_impersonation(self, meeting_id):
        def _cb(participant_id, claimed_name, recognized_meta, duration, face_path, full_path):
            recognized_name = recognized_meta["name"] if recognized_meta else None
            message = (f"Impersonation: claims to be {claimed_name} but recognized as {recognized_name}"
                       if recognized_name else
                       f"Impersonation: claims to be {claimed_name} but face does not match")
            now = time.time()
            self.logger.log_unknown_with_association(
                participant_id, duration, nearby_identity=recognized_meta,
                unknown_face_path=face_path, full_frame_path=full_path, timestamp=now, message=message,
            )
            data = {
                "participant_id": participant_id, "claimed_name": claimed_name,
                "recognized_name": recognized_name, "message": message,
                "is_self_for_host": self._is_self_for_host(meeting_id, participant_id),
                "timestamp": now, "duration": round(duration, 1),
                "face_snapshot": os.path.basename(face_path) if face_path else None,
                "full_snapshot": os.path.basename(full_path) if full_path else None,
            }
            alert = {"type": "impersonation_alert", "data": data}
            identity = self.recognizer.labels.get(str(self.registry.get(meeting_id).get_participant(participant_id).claimed_label_id)) if self.registry.get(meeting_id).get_participant(participant_id) and self.registry.get(meeting_id).get_participant(participant_id).claimed_label_id else None
            self.logger.log_meeting_alert(participant_id, claimed_name, "Identity mismatch", now, duration, identity=identity, message=message, face_snapshot=os.path.basename(face_path) if face_path else "", full_snapshot=os.path.basename(full_path) if full_path else "")
            self._record_and_broadcast(meeting_id, alert)
            self.send_selfview(participant_id, alert)
        return _cb

    def _make_on_extra_person_event(self, meeting_id):
        def _cb(participant_id, claimed_name, duration, start_ts, face_path, full_path):
            message = f"Unknown present with {claimed_name}"
            claimed_identity = None
            analyzer = self.analyzers.get(participant_id)
            if analyzer and analyzer.claimed_label_id:
                claimed_identity = self.recognizer.labels.get(str(analyzer.claimed_label_id))
            self.logger.log_unknown_with_association(
                f"{participant_id}-extra", duration, nearby_identity=claimed_identity,
                unknown_face_path=face_path, full_frame_path=full_path, timestamp=start_ts, message=message,
            )
            alert = {
                "type": "extra_person_alert",
                "data": {"participant_id": participant_id, "who": claimed_name, "message": message,
                         "timestamp": start_ts, "duration": round(duration, 1),
                         "is_self_for_host": self._is_self_for_host(meeting_id, participant_id),
                         "face_snapshot": os.path.basename(face_path) if face_path else None,
                         "full_snapshot": os.path.basename(full_path) if full_path else None},
            }
            self.logger.log_meeting_alert(participant_id, claimed_name, "Extra person present", start_ts, duration, identity=claimed_identity, message=message, face_snapshot=os.path.basename(face_path) if face_path else "", full_snapshot=os.path.basename(full_path) if full_path else "")
            self._record_and_broadcast(meeting_id, alert)
            self.send_selfview(participant_id, alert)
        return _cb

    # -------------------------------------------------------- websockets
    def register_host_ws(self, meeting_id, ws):
        self.host_websockets.setdefault(meeting_id, []).append(ws)

    def unregister_host_ws(self, meeting_id, ws):
        lst = self.host_websockets.get(meeting_id, [])
        if ws in lst:
            lst.remove(ws)

    def _broadcast_to_host(self, meeting_id, message):
        if not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_to_host_async(meeting_id, message), self.loop)

    async def _broadcast_to_host_async(self, meeting_id, message):
        dead = []
        for ws in list(self.host_websockets.get(meeting_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister_host_ws(meeting_id, ws)

    def send_selfview(self, participant_id, message):
        ws = self.selfview_websockets.get(participant_id)
        if ws and self.loop:
            asyncio.run_coroutine_threadsafe(self._send_one(ws, message), self.loop)

    async def _send_one(self, ws, message):
        try:
            await ws.send_json(message)
        except Exception:
            pass
