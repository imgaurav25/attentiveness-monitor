"""
app.py
-------
Entry point. A desktop GUI (Tkinter) that:
  - Opens the laptop webcam
  - Runs AttentionDetector on every frame (head pose + iris gaze + eye
    closure, calibrated per person)
  - Uses CentroidTracker to keep a stable "Member N" ID per person
  - In "Known / classroom" mode, matches each face against a trained
    roster (FaceRecognizer) and shows the student's real name/roll/etc.
    instead of "Member N"; anyone not on the roster triggers an
    unknown-person alert.
  - In "Unknown / open room" mode, people are just tracked generically,
    with an option to register someone on the fly from the live feed.
  - Feeds each member's status into AttentionStateMachine, which applies
    the configurable 5-25s delay and logs the REAL total duration of each
    lapse (not capped at the delay) once the person recovers.
  - Writes every event to an Excel file via ExcelLogger.

Run with:  python desktop_app/app.py   (see README.md for full setup instructions)
"""

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import subprocess

import cv2
from PIL import Image, ImageTk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.config import load_config, save_config
from core.attention_detector import AttentionDetector
from core.tracker import CentroidTracker
from core.attention_state import AttentionStateMachine
from core.excel_logger import ExcelLogger
from core.face_recognizer import FaceRecognizer
from core import association

GREEN = (60, 180, 75)
RED = (60, 60, 220)
ORANGE = (0, 140, 255)
PURPLE = (200, 60, 200)


class RegisterDialog(tk.Toplevel):
    """Collects Name / Roll No / Class / Department / Year for a new person."""
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Register New Person")
        self.resizable(False, False)
        self.result = None

        fields = ["Name", "Roll No", "Class", "Department", "Year"]
        self.vars = {f: tk.StringVar() for f in fields}
        for i, f in enumerate(fields):
            ttk.Label(self, text=f + ":").grid(row=i, column=0, sticky="w", padx=8, pady=6)
            ttk.Entry(self, textvariable=self.vars[f], width=30).grid(row=i, column=1, padx=8, pady=6)

        btns = ttk.Frame(self)
        btns.grid(row=len(fields), column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="Start Capturing Faces", command=self._submit).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)

        self.grab_set()

    def _submit(self):
        name = self.vars["Name"].get().strip()
        if not name:
            messagebox.showwarning("Name required", "Please enter at least a name.")
            return
        self.result = {f.lower().replace(" ", "_"): v.get().strip() for f, v in self.vars.items()}
        self.destroy()


class AttentivenessApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Meeting Attentiveness Monitor")
        self.root.geometry("1120x720")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.cfg = load_config()
        self.logger = ExcelLogger(os.path.abspath(self.cfg["excel_file"]))
        self.recognizer = FaceRecognizer(
            dataset_dir=os.path.abspath(self.cfg["dataset_dir"]),
            model_path=os.path.abspath(self.cfg["model_path"]),
            labels_path=os.path.abspath(self.cfg["labels_path"]),
            confidence_threshold=self.cfg["recognition_confidence_threshold"],
        )
        self.detector = None
        self.tracker = CentroidTracker()
        self.state_machine = AttentionStateMachine(
            delay_seconds=self.cfg["inattentive_delay_seconds"],
            face_missing_seconds=self.cfg["face_missing_seconds"],
            on_event=self.handle_event,
            on_unknown=self.handle_unknown,
            on_threshold_crossed=self.handle_threshold_crossed,
        )

        self.cap = None
        self.running = False
        self.worker_thread = None
        self.event_count = self.logger.count_events()
        self.recent_events = []

        self.mode_var = tk.StringVar(value=self.cfg.get("mode", "unknown"))
        # Tkinter variables must only be touched from the main thread. The
        # camera worker thread reads this plain attribute instead, which
        # _on_mode_change() keeps in sync.
        self.current_mode = self.mode_var.get()

        # Registration capture state (accessed from the camera thread)
        self._capture_lock = threading.Lock()
        self._capturing = False
        self._capture_frames = []
        self._capture_target = None  # metadata dict, set when a capture session starts

        self._unknown_flash_until = 0
        self._frame_context = {"frame": None, "members": {}}

        self._build_ui()

    # ---------------------------------------------------------- UI layout
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True)

        self.video_label = ttk.Label(left, background="#111")
        self.video_label.pack(fill="both", expand=True)

        controls = ttk.Frame(left)
        controls.pack(fill="x", pady=(10, 0))

        self.start_btn = ttk.Button(controls, text="Start Monitoring", command=self.start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(controls, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(controls, text="Open Excel Log", command=self.open_excel).pack(side="left", padx=4)

        controls2 = ttk.Frame(left)
        controls2.pack(fill="x", pady=(6, 0))
        ttk.Label(controls2, text="Delay (s):").pack(side="left")
        min_d, max_d = self.cfg["min_delay_seconds"], self.cfg["max_delay_seconds"]
        self.delay_var = tk.IntVar(value=self.cfg["inattentive_delay_seconds"])
        delay_scale = ttk.Scale(controls2, from_=min_d, to=max_d, orient="horizontal",
                                 variable=self.delay_var, command=self._on_delay_change, length=160)
        delay_scale.pack(side="left", padx=(4, 0))
        self.delay_value_lbl = ttk.Label(controls2, text=f"{self.delay_var.get()}s")
        self.delay_value_lbl.pack(side="left", padx=(4, 12))

        ttk.Label(controls2, text="Mode:").pack(side="left", padx=(12, 4))
        ttk.Radiobutton(controls2, text="Unknown environment", value="unknown",
                         variable=self.mode_var, command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(controls2, text="Known environment (classroom)", value="known",
                         variable=self.mode_var, command=self._on_mode_change).pack(side="left")

        controls3 = ttk.Frame(left)
        controls3.pack(fill="x", pady=(6, 0))
        ttk.Button(controls3, text="Register New Person (Train)", command=self.open_register_dialog).pack(side="left", padx=4)
        ttk.Button(controls3, text="Train Model Now", command=self.train_model).pack(side="left", padx=4)
        self.roster_lbl = ttk.Label(controls3, text=f"Roster: {self.recognizer.roster_size()} people")
        self.roster_lbl.pack(side="left", padx=12)

        right = ttk.Frame(main, width=340)
        right.pack(side="right", fill="y", padx=(12, 0))

        ttk.Label(right, text="Status", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.status_lbl = ttk.Label(right, text="Idle", foreground="#888")
        self.status_lbl.pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="Members in frame", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.members_box = tk.Listbox(right, height=8)
        self.members_box.pack(fill="x", pady=(0, 10))

        self.events_count_lbl_var = tk.StringVar(value=f"Total logged events: {self.event_count}")
        ttk.Label(right, textvariable=self.events_count_lbl_var,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")

        self.events_box = tk.Listbox(right, height=18)
        self.events_box.pack(fill="both", expand=True, pady=(4, 0))

        ttk.Label(right, text=f"Excel file:\n{os.path.abspath(self.cfg['excel_file'])}",
                  wraplength=320, foreground="#555").pack(anchor="w", pady=(10, 0))

    def _on_delay_change(self, _val):
        val = int(round(self.delay_var.get()))
        self.delay_var.set(val)
        self.delay_value_lbl.config(text=f"{val}s")
        self.state_machine.update_delay(val)
        self.cfg["inattentive_delay_seconds"] = val
        save_config(self.cfg)

    def _on_mode_change(self):
        self.current_mode = self.mode_var.get()
        self.cfg["mode"] = self.current_mode
        save_config(self.cfg)
        if self.current_mode == "known" and self.recognizer.roster_size() == 0:
            messagebox.showinfo(
                "No trained roster yet",
                "Known/classroom mode is on, but no one has been registered and trained yet.\n"
                "Everyone will show as 'Unknown' until you register students with "
                "'Register New Person' and click 'Train Model Now'.",
            )

    # ------------------------------------------------------- camera loop
    def start(self):
        if self.running:
            return
        self.cap = cv2.VideoCapture(self.cfg["camera_index"])
        if not self.cap.isOpened():
            messagebox.showerror("Camera error",
                                  "Could not open the webcam. Check camera_index in settings, "
                                  "and that no other app is using the camera.")
            return

        self.detector = AttentionDetector(
            max_yaw=self.cfg["max_yaw_degrees"],
            max_pitch=self.cfg["max_pitch_degrees"],
            max_gaze_offset=self.cfg["max_gaze_offset_ratio"],
        )
        self.running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_lbl.config(text="Monitoring...", foreground="#2a7")
        self.worker_thread = threading.Thread(target=self._loop, daemon=True)
        self.worker_thread.start()

    def stop(self):
        self.running = False
        self.state_machine.flush_all()  # don't lose an in-progress qualifying lapse
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_lbl.config(text="Idle", foreground="#888")
        if self.cap:
            self.cap.release()
        if self.detector:
            self.detector.close()

    def on_close(self):
        self.stop()
        self.root.destroy()

    def open_excel(self):
        path = os.path.abspath(self.cfg["excel_file"])
        if not os.path.exists(path):
            messagebox.showinfo("No log yet", "No events have been logged yet.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa
            elif sys.platform == "darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Could not open file", str(e))

    # --------------------------------------------------- registration UI
    def open_register_dialog(self):
        if not self.running:
            messagebox.showinfo("Start monitoring first",
                                 "Click 'Start Monitoring' so the camera is on, then register the "
                                 "person while they look at the camera.")
            return
        dialog = RegisterDialog(self.root)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        meta = dialog.result
        label_id = self.recognizer.next_label_id()
        target_count = self.cfg["images_per_registration"]

        with self._capture_lock:
            self._capture_frames = []
            self._capture_target = {"label_id": label_id, "meta": meta, "target_count": target_count}
            self._capturing = True

        messagebox.showinfo(
            "Capturing...",
            f"Now capturing face images for {meta['name']}.\n\n"
            "Ask them to look at the camera and slowly turn their head slightly "
            "left/right/up/down for a couple of seconds. This window will not "
            "update, but capture is happening live in the video feed."
        )
        # Poll until the background capture finishes
        self.root.after(300, self._check_capture_done)

    def _check_capture_done(self):
        with self._capture_lock:
            capturing = self._capturing
            frames = list(self._capture_frames)
            target = self._capture_target
        if capturing:
            self.root.after(300, self._check_capture_done)
            return
        if target is None or not frames:
            return
        label_id = target["label_id"]
        meta = target["meta"]
        self.recognizer.save_registration_images(label_id, frames)
        self.recognizer.register_metadata(
            label_id, meta["name"], meta["roll_no"], meta["class"], meta["department"], meta["year"]
        )
        messagebox.showinfo("Captured", f"Saved {len(frames)} face images for {meta['name']}.\n"
                                          "Click 'Train Model Now' to include them in recognition.")

    def train_model(self):
        try:
            n_people, n_images = self.recognizer.train()
        except RuntimeError as e:
            messagebox.showwarning("Nothing to train", str(e))
            return
        self.roster_lbl.config(text=f"Roster: {self.recognizer.roster_size()} people")
        messagebox.showinfo("Training complete",
                             f"Trained on {n_people} people ({n_images} images total).")

    # --------------------------------------------------------- callbacks
    def handle_threshold_crossed(self, member_id, reason, start_ts, elapsed):
        """Fires the INSTANT a lapse crosses the delay threshold -- shown
        immediately so the teacher knows right away, without waiting for
        the person to recover (the final real-duration row is still logged
        separately by handle_event at recovery)."""
        identity = self._frame_context.get("members", {}).get(member_id, {}).get("identity")
        who = identity["name"] if identity else f"Member {member_id}"
        self.root.after(0, lambda: self.status_lbl.config(
            text=f"\u23f0 {who} has been \"{reason}\" for {elapsed:.1f}s", foreground="#c60"))
        self.root.after(0, self.root.bell)

    def handle_event(self, member_id, reason, start_ts, duration):
        identity = self._frame_context.get("members", {}).get(member_id, {}).get("identity")
        self.logger.log_event(member_id, reason, start_ts, duration, identity=identity)
        self.event_count += 1
        ts = time.strftime("%H:%M:%S", time.localtime(start_ts))
        who = identity["name"] if identity else f"Member {member_id}"
        entry = f"[{ts}] {who} - {reason} ({duration:.1f}s)"
        self.recent_events.insert(0, entry)
        self.recent_events = self.recent_events[:200]
        self.root.after(0, self._refresh_events_ui)

    def handle_unknown(self, member_id, duration):
        frame = self._frame_context.get("frame")
        members = self._frame_context.get("members", {})
        unknown_box = members.get(member_id, {}).get("box")

        face_path, full_path, nearby_identity = "", "", None
        if frame is not None and unknown_box is not None:
            other_members = {mid: info for mid, info in members.items() if mid != member_id}
            _, nearby_identity, _ = association.find_nearest_registered(unknown_box, other_members)
            face_path, full_path = association.save_unknown_snapshots(
                frame, unknown_box, os.path.abspath(self.cfg["snapshots_dir"]), unknown_label=member_id,
            )

        # "Unknown" if nobody registered is nearby; "Unknown present with
        # <name>" when a registered student was in frame with them.
        message = f"Unknown present with {nearby_identity['name']}" if nearby_identity else "Unknown"

        self.logger.log_unknown_with_association(
            member_id, duration, nearby_identity=nearby_identity,
            unknown_face_path=face_path, full_frame_path=full_path, message=message,
        )
        self.event_count += 1
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] \u26a0 {message}"
        self.recent_events.insert(0, entry)
        self.recent_events = self.recent_events[:200]
        self._unknown_flash_until = time.time() + 4
        self.root.after(0, self._refresh_events_ui)
        self.root.after(0, lambda: self.status_lbl.config(
            text=f"\u26a0 {message}", foreground="#c00"))
        self.root.after(0, self.root.bell)

    def _refresh_events_ui(self):
        self.events_count_lbl_var.set(f"Total logged events: {self.event_count}")
        self.events_box.delete(0, tk.END)
        for e in self.recent_events[:50]:
            self.events_box.insert(tk.END, e)

    # ------------------------------------------------------------- loop
    def _loop(self):
        proc_width = self.cfg["process_width"]
        rel_drop = self.cfg["eye_closed_relative_drop"]
        fallback_ear = self.cfg["eye_closed_ratio"]
        self._frame_context = {"frame": None, "members": {}}

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

            # Registration capture: grab the largest face in frame each pass
            with self._capture_lock:
                capturing = self._capturing
            if capturing and readings:
                largest = max(readings, key=lambda r: r.box[2] * r.box[3])
                if largest.face_crop_gray.size > 0:
                    with self._capture_lock:
                        self._capture_frames.append(largest.face_crop_gray.copy())
                        done = len(self._capture_frames) >= self._capture_target["target_count"]
                        if done:
                            self._capturing = False

            mode = self.current_mode
            member_labels = []

            # ---- pass 1: resolve identity for every tracked face ----
            members = {}
            for member_id, box in tracked.items():
                reading = box_to_reading.get(box)
                if reading is None:
                    continue
                identity = None
                if mode == "known" and reading.face_crop_gray.size > 0:
                    _, identity, _ = self.recognizer.predict(reading.face_crop_gray)
                members[member_id] = {"box": box, "reading": reading, "identity": identity}

            self._frame_context = {"frame": proc_frame.copy(), "members": members}

            # ---- pass 2: attentiveness + identity debounce/logging ----
            for member_id, info in members.items():
                reading = info["reading"]
                identity = info["identity"]
                box = info["box"]

                if mode == "known":
                    self.state_machine.report_identity(member_id, is_known=identity is not None)

                baseline = self.state_machine.get_ear_baseline(member_id)
                if baseline:
                    eyes_closed = reading.ear < baseline * rel_drop
                else:
                    eyes_closed = reading.ear < fallback_ear

                reasons = set()
                if reading.looking_away_head or reading.looking_away_gaze:
                    reasons.add("Looking away")
                if eyes_closed:
                    reasons.add("Eyes closed / drowsy")

                counting = self.state_machine.report(member_id, reasons, ear_value=reading.ear)

                x, y, w, h = box
                if mode == "known" and identity is None:
                    color = PURPLE
                    label = "Unknown"
                else:
                    who = identity["name"] if identity else f"Member {member_id}"
                    color = GREEN
                    label = f"{who}: Attentive"
                    if reasons:
                        color = ORANGE
                        top_reason = max(counting, key=counting.get) if counting else next(iter(reasons))
                        secs = counting.get(top_reason, 0)
                        label = f"{who}: {top_reason} ({secs:.1f}s)"
                        if secs >= self.state_machine.delay_seconds:
                            color = RED
                cv2.rectangle(proc_frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(proc_frame, label, (x, max(15, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                member_labels.append(label)

            self.state_machine.prune_stale(set(tracked.keys()))

            if time.time() > self._unknown_flash_until and self.running:
                self.root.after(0, lambda: self.status_lbl.config(text="Monitoring...", foreground="#2a7"))

            self.root.after(0, self._update_video, proc_frame)
            self.root.after(0, self._update_members_list, member_labels)

            time.sleep(0.01)

    def _update_video(self, frame_bgr):
        if not self.running:
            return
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(image=img)
        self.video_label.imgtk = imgtk
        self.video_label.configure(image=imgtk)

    def _update_members_list(self, labels):
        self.members_box.delete(0, tk.END)
        for lbl in labels:
            self.members_box.insert(tk.END, lbl)


def main():
    root = tk.Tk()
    AttentivenessApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
