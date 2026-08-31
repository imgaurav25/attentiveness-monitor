"""
server.py
----------
FastAPI backend for the React dashboard. This does NOT reimplement any
detection logic -- it imports and drives the exact same modules the
desktop app uses (core/attention_detector.py, tracker.py,
attention_state.py, face_recognizer.py, excel_logger.py, association.py).
Only the "front end" of the pipeline changes: instead of drawing into a
Tkinter window, frames/status are pushed to connected browsers over a
WebSocket, and controls (start/stop/register/train/mode/delay) are REST
endpoints instead of button clicks.

Run with:  uvicorn server:app --reload --port 8000   (from the backend/ folder)
"""

import asyncio
import base64
import os
import sys
import threading
import time
from typing import Optional

import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.config import load_config, save_config
from core.attention_detector import AttentionDetector
from core.tracker import CentroidTracker
from core.attention_state import AttentionStateMachine
from core.excel_logger import ExcelLogger
from core.face_recognizer import FaceRecognizer
from core import association
from meeting_service import MeetingService, decode_jpeg_b64

app = FastAPI(title="Attentiveness Monitor API")

# In production, set ALLOWED_ORIGINS to a comma-separated list of your real
# domain(s), e.g. "https://meet.example.com". Defaults to the Vite dev
# server origins so local development works with zero configuration.
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------- request models
class ModeRequest(BaseModel):
    mode: str  # "unknown" | "known"


class DelayRequest(BaseModel):
    seconds: int


class RegisterRequest(BaseModel):
    name: str
    roll_no: str = ""
    student_class: str = ""
    department: str = ""
    year: str = ""


class AttendeesRequest(BaseModel):
    label_ids: list[int]


class CreateMeetingRequest(BaseModel):
    title: str = ""


class MeetingRegisterRequest(BaseModel):
    name: str
    roll_no: str = ""
    student_class: str = ""
    department: str = ""
    year: str = ""


class JoinMeetingRequest(BaseModel):
    name: str
    claimed_label_id: Optional[int] = None
    is_host: bool = False


class LeaveMeetingRequest(BaseModel):
    participant_id: str


# --------------------------------------------------------------- the service
class MonitorService:
    def __init__(self):
        self.cfg = load_config()
        self.logs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
        self.snapshots_dir = os.path.abspath(self.cfg["snapshots_dir"])
        self.logger = ExcelLogger(os.path.abspath(self.cfg["excel_file"]))
        self.recognizer = FaceRecognizer(
            dataset_dir=os.path.abspath(self.cfg["dataset_dir"]),
            model_path=os.path.abspath(self.cfg["model_path"]),
            labels_path=os.path.abspath(self.cfg["labels_path"]),
            confidence_threshold=self.cfg["recognition_confidence_threshold"],
        )
        self.tracker = CentroidTracker()
        self.state_machine = AttentionStateMachine(
            delay_seconds=self.cfg["inattentive_delay_seconds"],
            face_missing_seconds=self.cfg["face_missing_seconds"],
            unknown_alert_delay=self.cfg["unknown_alert_delay_seconds"],
            on_event=self._on_attentiveness_event,
            on_unknown=self._on_unknown_person,
            on_threshold_crossed=self._on_threshold_crossed,
        )

        self.detector: Optional[AttentionDetector] = None
        self.cap = None
        self.running = False
        self.mode = self.cfg.get("mode", "unknown")
        self.worker_thread: Optional[threading.Thread] = None

        # Updated every frame; read by the on_unknown callback so it knows
        # who else is in frame right now (for proximity association).
        self._frame_context = {"frame": None, "members": {}}

        self.recent_attentiveness_events = []  # newest first
        self.recent_unknown_events = []
        self.member_labels = []  # live per-frame status strings for the dashboard

        # Session attendee list (known/classroom mode pre-meeting step) --
        # purely informational bookkeeping of who the teacher expects, does
        # not gate recognition itself (recognition still matches anyone in
        # the trained roster, present or not).
        self.session_attendees = []

        # Registration capture state
        self._capture_lock = threading.Lock()
        self._capturing = False
        self._capture_frames = []
        self._capture_target = None

        # asyncio bridge for pushing to websockets from the camera thread
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.websockets: list[WebSocket] = []
        self._frame_counter = 0

    # ----------------------------------------------------------- lifecycle
    def start(self):
        if self.running:
            return True, "already running"
        self.cap = cv2.VideoCapture(self.cfg["camera_index"])
        if not self.cap.isOpened():
            return False, "Could not open the webcam (camera_index=%s)" % self.cfg["camera_index"]
        self.detector = AttentionDetector(
            max_yaw=self.cfg["max_yaw_degrees"],
            max_pitch=self.cfg["max_pitch_degrees"],
            max_gaze_offset=self.cfg["max_gaze_offset_ratio"],
        )
        self.running = True
        self.worker_thread = threading.Thread(target=self._loop, daemon=True)
        self.worker_thread.start()
        return True, "started"

    def stop(self):
        self.running = False
        self.state_machine.flush_all()
        if self.cap:
            self.cap.release()
            self.cap = None
        if self.detector:
            self.detector.close()
            self.detector = None
        return True, "stopped"

    def set_mode(self, mode: str):
        if mode not in ("unknown", "known"):
            raise ValueError("mode must be 'unknown' or 'known'")
        self.mode = mode
        self.cfg["mode"] = mode
        save_config(self.cfg)

    def set_delay(self, seconds: int):
        seconds = max(self.cfg["min_delay_seconds"], min(self.cfg["max_delay_seconds"], seconds))
        self.state_machine.update_delay(seconds)
        self.cfg["inattentive_delay_seconds"] = seconds
        save_config(self.cfg)
        return seconds

    # ------------------------------------------------------- registration
    def begin_registration(self, meta: dict):
        if not self.running:
            raise RuntimeError("Start monitoring before registering a new person.")
        label_id = self.recognizer.next_label_id()
        with self._capture_lock:
            self._capture_frames = []
            self._capture_target = {
                "label_id": label_id, "meta": meta,
                "target_count": self.cfg["images_per_registration"],
            }
            self._capturing = True
        return label_id

    def registration_status(self):
        with self._capture_lock:
            capturing = self._capturing
            n = len(self._capture_frames)
            target = self._capture_target["target_count"] if self._capture_target else 0
            done_meta = None
            if not capturing and self._capture_target and n > 0:
                done_meta = self._capture_target["meta"]
        return {"capturing": capturing, "captured": n, "target": target, "last_registered": done_meta}

    def finalize_registration_if_done(self):
        """Called by the poller once capture finishes; saves images + metadata."""
        with self._capture_lock:
            if self._capturing or not self._capture_target or not self._capture_frames:
                return None
            target = self._capture_target
            frames = self._capture_frames
            self._capture_target = None
            self._capture_frames = []
        label_id = target["label_id"]
        meta = target["meta"]
        self.recognizer.save_registration_images(label_id, frames)
        self.recognizer.register_metadata(
            label_id, meta["name"], meta.get("roll_no", ""), meta.get("student_class", ""),
            meta.get("department", ""), meta.get("year", ""),
        )
        return {"label_id": label_id, "meta": meta, "images": len(frames)}

    def train(self):
        n_people, n_images = self.recognizer.train()
        return {"people": n_people, "images": n_images}

    def roster(self):
        return [
            {"label_id": int(lid), **meta}
            for lid, meta in self.recognizer.labels.items()
        ]

    # ------------------------------------------------------------ events
    def _on_threshold_crossed(self, member_id, reason, start_ts, elapsed):
        """Fires the INSTANT a lapse crosses the delay threshold -- pushed
        immediately so the teacher/admin finds out right away, without
        waiting for the person to recover (the final real-duration row is
        still logged separately by _on_attentiveness_event at recovery)."""
        identity = self._frame_context["members"].get(member_id, {}).get("identity")
        who = identity["name"] if identity else f"Member {member_id}"
        record = {
            "member_id": member_id, "who": who, "identity": identity,
            "reason": reason, "timestamp": start_ts, "elapsed": round(elapsed, 1),
        }
        self._broadcast({"type": "attentiveness_alert", "data": record})

    def _on_attentiveness_event(self, member_id, reason, start_ts, duration):
        identity = self._frame_context["members"].get(member_id, {}).get("identity")
        self.logger.log_event(member_id, reason, start_ts, duration, identity=identity)
        who = identity["name"] if identity else f"Member {member_id}"
        record = {
            "member_id": member_id, "who": who, "identity": identity,
            "reason": reason, "timestamp": start_ts, "duration": round(duration, 1),
        }
        self.recent_attentiveness_events.insert(0, record)
        self.recent_attentiveness_events = self.recent_attentiveness_events[:200]
        self._broadcast({"type": "attentiveness_event", "data": record})

    def _on_unknown_person(self, member_id, duration):
        frame = self._frame_context["frame"]
        members = self._frame_context["members"]
        unknown_box = members.get(member_id, {}).get("box")

        face_path, full_path, nearby_identity = "", "", None
        if frame is not None and unknown_box is not None:
            other_members = {mid: info for mid, info in members.items() if mid != member_id}
            _, nearby_identity, _ = association.find_nearest_registered(unknown_box, other_members)
            face_path, full_path = association.save_unknown_snapshots(
                frame, unknown_box, self.snapshots_dir, unknown_label=member_id,
            )

        # "Unknown" if nobody registered is nearby; "Unknown present with
        # <name>" when a registered student was in frame with them.
        message = f"Unknown present with {nearby_identity['name']}" if nearby_identity else "Unknown"

        now = time.time()
        self.logger.log_unknown_with_association(
            member_id, duration, nearby_identity=nearby_identity,
            unknown_face_path=face_path, full_frame_path=full_path, timestamp=now,
            message=message,
        )
        record = {
            "unknown_id": f"UNKNOWN-{member_id:02d}",
            "member_id": member_id,
            "nearby_student": nearby_identity,
            "message": message,
            "timestamp": now,
            "duration": round(duration, 1),
            "face_snapshot": os.path.basename(face_path) if face_path else None,
            "full_snapshot": os.path.basename(full_path) if full_path else None,
        }
        self.recent_unknown_events.insert(0, record)
        self.recent_unknown_events = self.recent_unknown_events[:200]
        self._broadcast({"type": "unknown_event", "data": record})

    # --------------------------------------------------------------- loop
    def _loop(self):
        proc_width = self.cfg["process_width"]
        rel_drop = self.cfg["eye_closed_relative_drop"]
        fallback_ear = self.cfg["eye_closed_ratio"]

        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            h0, w0 = frame.shape[:2]
            scale = proc_width / w0
            proc_frame = cv2.resize(frame, (proc_width, int(h0 * scale)))

            readings = self.detector.analyze(proc_frame)
            boxes = [r.box for r in readings]
            tracked = self.tracker.update(boxes)
            box_to_reading = {r.box: r for r in readings}

            # ---- registration capture (grab the largest face each pass) ----
            with self._capture_lock:
                capturing = self._capturing
            if capturing and readings:
                largest = max(readings, key=lambda r: r.box[2] * r.box[3])
                if largest.face_crop_gray.size > 0:
                    with self._capture_lock:
                        self._capture_frames.append(largest.face_crop_gray.copy())
                        if len(self._capture_frames) >= self._capture_target["target_count"]:
                            self._capturing = False

            # ---- pass 1: resolve identity for every tracked face ----
            members = {}
            for member_id, box in tracked.items():
                reading = box_to_reading.get(box)
                if reading is None:
                    continue
                identity = None
                if self.mode == "known" and reading.face_crop_gray.size > 0:
                    _, identity, _ = self.recognizer.predict(reading.face_crop_gray)
                members[member_id] = {"box": box, "reading": reading, "identity": identity}

            self._frame_context = {"frame": proc_frame.copy(), "members": members}

            # ---- pass 2: attentiveness + identity debounce/logging ----
            member_labels = []
            for member_id, info in members.items():
                reading = info["reading"]
                identity = info["identity"]
                box = info["box"]

                if self.mode == "known":
                    self.state_machine.report_identity(member_id, is_known=identity is not None)

                baseline = self.state_machine.get_ear_baseline(member_id)
                looking_away = reading.looking_away_head or reading.looking_away_gaze
                eye_threshold = baseline * rel_drop if baseline else fallback_ear
                eyes_closed = (reading.ear < eye_threshold) and not reading.looking_away_head
                if reading.looking_away_gaze:
                    eyes_closed = reading.ear < eye_threshold * 0.82

                reasons = set()
                if looking_away:
                    reasons.add("Looking away")
                elif eyes_closed:
                    reasons.add("Eyes closed / drowsy")

                counting = self.state_machine.report(member_id, reasons, ear_value=reading.ear)

                x, y, w, h = box
                if self.mode == "known" and identity is None:
                    who, status, color = "Unknown", "", (200, 60, 200)
                    display_label = "Unknown"
                else:
                    who = identity["name"] if identity else f"Member {member_id}"
                    if reasons:
                        top_reason = max(counting, key=counting.get) if counting else next(iter(reasons))
                        secs = counting.get(top_reason, 0)
                        status = f"{top_reason} ({secs:.1f}s)"
                        color = (0, 60, 220) if secs >= self.state_machine.delay_seconds else (0, 140, 255)
                    else:
                        status, color = "Attentive", (60, 180, 75)
                    display_label = f"{who}: {status}"

                cv2.rectangle(proc_frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(proc_frame, display_label, (x, max(15, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                member_labels.append({
                    "member_id": member_id, "who": who, "identity": identity,
                    "status": status, "known": identity is not None if self.mode == "known" else None,
                })

            self.state_machine.prune_stale(set(tracked.keys()))
            self.member_labels = member_labels

            # ---- push to browser(s) ----
            self._frame_counter += 1
            if self._frame_counter % 2 == 0:  # ~throttle to reduce bandwidth
                ok2, buf = cv2.imencode(".jpg", proc_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok2:
                    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
                    self._broadcast({"type": "frame", "data": b64})
            self._broadcast({"type": "members", "data": member_labels})

            time.sleep(0.01)

    # ------------------------------------------------------------ ws push
    def _broadcast(self, message: dict):
        if not self.loop or not self.websockets:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_async(message), self.loop)

    async def _broadcast_async(self, message: dict):
        dead = []
        for ws in list(self.websockets):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.websockets:
                self.websockets.remove(ws)


service = MonitorService()

# Shares the SAME roster/recognizer, Excel log, and config as classroom
# ("Known environment") mode -- register someone once, anywhere, and
# they're recognizable everywhere.
meeting_service = MeetingService(service.recognizer, service.logger, service.cfg)


@app.on_event("startup")
async def on_startup():
    service.loop = asyncio.get_event_loop()
    meeting_service.loop = service.loop


# --------------------------------------------------------------- REST API
@app.get("/api/status")
def get_status():
    return {
        "running": service.running,
        "mode": service.mode,
        "delay_seconds": service.state_machine.delay_seconds,
        "min_delay": service.cfg["min_delay_seconds"],
        "max_delay": service.cfg["max_delay_seconds"],
        "roster_size": service.recognizer.roster_size(),
        "attentiveness_event_count": service.logger.count_attentiveness_events(),
        "unknown_event_count": service.logger.count_unknown_events(),
        "members": service.member_labels,
    }


@app.post("/api/start")
def api_start():
    ok, msg = service.start()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@app.post("/api/stop")
def api_stop():
    ok, msg = service.stop()
    return {"ok": ok, "message": msg}


@app.post("/api/mode")
def api_set_mode(req: ModeRequest):
    try:
        service.set_mode(req.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "mode": service.mode}


@app.post("/api/delay")
def api_set_delay(req: DelayRequest):
    seconds = service.set_delay(req.seconds)
    return {"ok": True, "delay_seconds": seconds}


@app.post("/api/register/start")
def api_register_start(req: RegisterRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        label_id = service.begin_registration(req.model_dump())
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "label_id": label_id}


@app.get("/api/register/status")
def api_register_status():
    finalized = service.finalize_registration_if_done()
    status = service.registration_status()
    status["finalized"] = finalized
    return status


@app.post("/api/train")
def api_train():
    try:
        return {"ok": True, **service.train()}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/roster")
def api_roster():
    return service.roster()


@app.post("/api/session/attendees")
def api_set_session_attendees(req: AttendeesRequest):
    roster_by_id = {r["label_id"]: r for r in service.roster()}
    service.session_attendees = [roster_by_id[lid] for lid in req.label_ids if lid in roster_by_id]
    return {"ok": True, "attendees": service.session_attendees}


@app.get("/api/session/attendees")
def api_get_session_attendees():
    return service.session_attendees


@app.get("/api/events/attentiveness")
def api_events_attentiveness(limit: int = 50):
    return service.recent_attentiveness_events[:limit]


@app.get("/api/events/unknown")
def api_events_unknown(limit: int = 50):
    return service.recent_unknown_events[:limit]


@app.get("/api/download/log")
def api_download_log():
    path = os.path.abspath(service.logger.path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        filename="attentiveness_log.xlsx")


@app.get("/api/snapshots/{filename}")
def api_snapshot(filename: str):
    path = os.path.join(service.snapshots_dir, filename)
    if not os.path.abspath(path).startswith(os.path.abspath(service.snapshots_dir)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename=os.path.basename(path))


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    service.websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive / ignore client pings
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in service.websockets:
            service.websockets.remove(websocket)


# ============================================================================
# MEETING SYSTEM -- Google-Meet-style link-based meetings. Each participant
# streams frames from THEIR OWN camera (not one shared classroom camera);
# see meeting_service.py / participant_session.py for the detection side.
# The actual audio/video call itself is NOT handled by this backend -- the
# frontend embeds Jitsi Meet's free public infrastructure for that. This
# backend only handles: meeting links, mandatory registration-before-join,
# and the attentiveness/impersonation/extra-person analysis.
# ============================================================================

@app.post("/api/meetings")
def api_create_meeting(req: CreateMeetingRequest):
    meeting = meeting_service.create_meeting(title=req.title or None)
    return meeting.to_dict()


@app.get("/api/meetings/{meeting_id}")
def api_get_meeting(meeting_id: str):
    meeting = meeting_service.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting.to_dict()


@app.get("/api/meetings/{meeting_id}/roster")
def api_meeting_roster(meeting_id: str):
    """The roster is global (shared with classroom mode) -- used to
    populate the 'select your name' dropdown on the pre-join screen."""
    if not meeting_service.get_meeting(meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting_service.roster()


@app.post("/api/meetings/{meeting_id}/register/start")
def api_meeting_register_start(meeting_id: str, req: MeetingRegisterRequest):
    if not meeting_service.get_meeting(meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    token, label_id = meeting_service.start_registration(req.model_dump())
    return {"ok": True, "token": token, "label_id": label_id}


@app.get("/api/meetings/register/status")
def api_meeting_register_status(token: str):
    status = meeting_service.registration_status(token)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown or already-finished registration session")
    return status


@app.post("/api/meetings/{meeting_id}/join")
def api_join_meeting(meeting_id: str, req: JoinMeetingRequest):
    try:
        participant = meeting_service.join_meeting(
            meeting_id, req.name, req.claimed_label_id, is_host=req.is_host,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    meeting = meeting_service.get_meeting(meeting_id)
    return {
        "ok": True,
        "participant_id": participant.participant_id,
        "jitsi_room_name": meeting.jitsi_room_name,
        "is_host": participant.is_host,
        "name": participant.name,
    }


@app.post("/api/meetings/{meeting_id}/leave")
def api_leave_meeting(meeting_id: str, req: LeaveMeetingRequest):
    meeting_service.leave_meeting(req.participant_id)
    return {"ok": True}


@app.get("/api/meetings/{meeting_id}/events")
def api_meeting_events(meeting_id: str, limit: int = 50):
    return meeting_service.recent_events.get(meeting_id, [])[:limit]


@app.websocket("/ws/meetings/register/{token}")
async def ws_register_capture(websocket: WebSocket, token: str):
    """The joining participant's browser streams frames here purely to
    capture face images for a NEW registration (before they've joined the
    meeting itself). Closes automatically once enough images are captured."""
    await websocket.accept()
    if token not in meeting_service.registration_sessions:
        await websocket.send_json({"type": "error", "data": "Unknown registration session"})
        await websocket.close()
        return
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") != "frame":
                continue
            frame = decode_jpeg_b64(msg["data"])
            if frame is None:
                continue
            result = await asyncio.to_thread(meeting_service.process_registration_frame, token, frame)
            await websocket.send_json({"type": "progress", "data": result})
            if result.get("done"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/meetings/{meeting_id}/participant/{participant_id}")
async def ws_meeting_participant(websocket: WebSocket, meeting_id: str, participant_id: str):
    """The participant's own browser streams frames from THEIR camera here
    throughout the meeting. Analysis results are sent straight back for
    their self-view; alerts are separately broadcast to the host's socket."""
    await websocket.accept()
    if participant_id not in meeting_service.analyzers:
        await websocket.send_json({"type": "error", "data": "Not joined"})
        await websocket.close()
        return
    meeting_service.selfview_websockets[participant_id] = websocket
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") != "frame":
                continue
            frame = decode_jpeg_b64(msg["data"])
            if frame is None:
                continue
            result = await asyncio.to_thread(meeting_service.process_participant_frame, participant_id, frame)
            await websocket.send_json({"type": "self_status", "data": result})
    except WebSocketDisconnect:
        pass
    finally:
        meeting_service.selfview_websockets.pop(participant_id, None)


@app.websocket("/ws/meetings/{meeting_id}/host")
async def ws_meeting_host(websocket: WebSocket, meeting_id: str):
    """The host dashboard connects here to receive every attentiveness /
    impersonation / extra-person alert for the whole meeting, live."""
    await websocket.accept()
    if not meeting_service.get_meeting(meeting_id):
        await websocket.send_json({"type": "error", "data": "Meeting not found"})
        await websocket.close()
        return
    meeting_service.register_host_ws(meeting_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive / ignore client pings
    except WebSocketDisconnect:
        pass
    finally:
        meeting_service.unregister_host_ws(meeting_id, websocket)


@app.websocket("/ws/meetings/{meeting_id}/signal/{participant_id}")
async def ws_meeting_signal(websocket: WebSocket, meeting_id: str, participant_id: str):
    """Custom WebRTC signaling channel. Media is peer-to-peer between browsers;
    this socket only relays SDP offers/answers and ICE candidates."""
    await websocket.accept()
    meeting = meeting_service.get_meeting(meeting_id)
    participant = meeting.get_participant(participant_id) if meeting else None
    if not participant:
        await websocket.send_json({"type": "error", "data": "Not joined"})
        await websocket.close()
        return
    existing = meeting_service.register_meeting_ws(meeting_id, participant_id, websocket)
    try:
        await websocket.send_json({
            "type": "webrtc_peers",
            "participants": [
                meeting.get_participant(pid).to_dict()
                for pid in existing if meeting.get_participant(pid) and meeting.get_participant(pid).connected
            ],
        })
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") != "webrtc_signal":
                continue
            meeting_service.broadcast_signal(
                meeting_id, participant_id, msg.get("signal") or {}, msg.get("target")
            )
    except WebSocketDisconnect:
        pass
    finally:
        meeting_service.unregister_meeting_ws(meeting_id, participant_id)
        # A signaling disconnect can happen during refresh/network changes
        # before the REST leave call reaches the server. Tell existing peers
        # to tear down the stale WebRTC connection so the grid never keeps a
        # ghost tile. The participant remains registered server-side so a
        # reconnect with the same participant id can re-establish the peer.
        current = meeting.get_participant(participant_id) if meeting else None
        if current and current.connected:
            meeting_service.broadcast_participant_presence(meeting_id, "participant_left", current)
