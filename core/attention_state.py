"""
attention_state.py
--------------------
Turns raw per-frame FaceReadings into logged events.

Two separate concerns live here:

1. INATTENTIVENESS TIMERS (per reason: "Looking away", "Eyes closed / drowsy",
   "Away from camera"). A reason must stay continuously true for at least
   `delay_seconds` (5-25s, configurable) before it "qualifies". The INSTANT
   it qualifies, `on_threshold_crossed` fires once so the teacher/admin can
   be notified immediately -- they shouldn't have to wait for the person to
   recover to find out. Separately, we keep tracking until the person
   actually recovers (or monitoring stops), then `on_event` fires ONE final
   time with:
     - Timestamp = the REAL/original moment the lapse started
     - Duration  = the REAL total time they were inattentive (which will
                    be >= delay_seconds, not capped at it)
   This is what was requested: an immediate heads-up when the threshold is
   crossed, AND a log entry with the true original start time and true
   total length of the lapse once it's over.

2. EAR CALIBRATION (glasses-robustness). Absolute eye-aspect-ratio varies a
   lot between people (and especially with/without glasses). Instead of one
   global "closed" threshold, each recognized member gets a personal
   baseline built from their own EAR values while they're attentive
   (rolling max). "Eyes closed" is then judged RELATIVE to that person's
   own open-eye baseline, which is far more robust across glasses/no-glasses
   and different face shapes than one fixed global number.

3. UNKNOWN-PERSON ALERTS (closed/"known" classroom mode only). A short,
   separate timer -- if a tracked face is NOT matched to the trained roster
   for a few continuous seconds, fire a one-time notification/log event
   (distinct from the attentiveness reasons above).
"""

import time


class MemberState:
    def __init__(self):
        self.reason_since = {}        # reason -> real start timestamp
        self.reason_triggered = set()  # reasons that have crossed the delay threshold (still ongoing)
        self.ear_baseline = None       # rolling "eyes open" EAR for this member
        self.unknown_since = None      # timestamp person first became unrecognized (known mode)
        self.unknown_notified = False
        self.last_seen = time.time()

    def touch(self):
        self.last_seen = time.time()

    def update_ear_baseline(self, ear_value, is_attentive):
        """Slowly track this member's own 'eyes open' EAR so drowsiness
        detection adapts per-person (helps a lot with glasses)."""
        if not is_attentive or ear_value <= 0:
            return
        if self.ear_baseline is None:
            self.ear_baseline = ear_value
        else:
            # Exponential moving average, biased toward the higher (more
            # open) values seen so it represents "eyes open", not average.
            if ear_value > self.ear_baseline:
                self.ear_baseline = 0.7 * self.ear_baseline + 0.3 * ear_value
            else:
                self.ear_baseline = 0.95 * self.ear_baseline + 0.05 * ear_value


class AttentionStateMachine:
    def __init__(self, delay_seconds=7, face_missing_seconds=5,
                 unknown_alert_delay=2, on_event=None, on_unknown=None,
                 on_threshold_crossed=None):
        self.delay_seconds = delay_seconds
        self.face_missing_seconds = face_missing_seconds
        self.unknown_alert_delay = unknown_alert_delay
        self.on_event = on_event      # callback(member_id, reason, start_ts, duration) -- fires at RECOVERY, with the real total duration
        self.on_unknown = on_unknown  # callback(member_id, duration)
        # callback(member_id, reason, start_ts, elapsed) -- fires ONCE, the
        # instant a reason crosses delay_seconds, so a teacher/admin can be
        # notified immediately instead of waiting for the person to recover.
        self.on_threshold_crossed = on_threshold_crossed
        self.members = {}

    def update_delay(self, seconds):
        self.delay_seconds = seconds

    def _get(self, member_id):
        if member_id not in self.members:
            self.members[member_id] = MemberState()
        return self.members[member_id]

    def get_ear_baseline(self, member_id):
        st = self.members.get(member_id)
        return st.ear_baseline if st else None

    def report(self, member_id, reasons_active: set, ear_value=None):
        """
        reasons_active: currently-true inattentiveness reasons this frame,
        e.g. {"Looking away"}, {"Eyes closed / drowsy"}, or empty set.
        Returns dict {reason: elapsed_seconds} for reasons currently timing,
        for live "3.2s..." UI feedback.
        """
        state = self._get(member_id)
        state.touch()
        now = time.time()

        if ear_value is not None:
            state.update_ear_baseline(ear_value, is_attentive=(len(reasons_active) == 0))

        currently_counting = {}

        for reason in reasons_active:
            if reason not in state.reason_since:
                state.reason_since[reason] = now
            elapsed = now - state.reason_since[reason]
            currently_counting[reason] = elapsed
            if elapsed >= self.delay_seconds and reason not in state.reason_triggered:
                # Crossing the threshold for the FIRST time this lapse --
                # notify immediately. The final, real total duration is
                # still logged separately once the person recovers (below).
                state.reason_triggered.add(reason)
                if self.on_threshold_crossed:
                    self.on_threshold_crossed(member_id, reason, state.reason_since[reason], elapsed)

        # Reasons that ended this frame: if they had qualified, log the
        # REAL total duration now (recovery = the event actually finishing).
        for reason in list(state.reason_since.keys()):
            if reason not in reasons_active:
                start_ts = state.reason_since[reason]
                total_duration = now - start_ts
                had_qualified = reason in state.reason_triggered
                del state.reason_since[reason]
                state.reason_triggered.discard(reason)
                if had_qualified and self.on_event:
                    self.on_event(member_id, reason, start_ts, total_duration)

        return currently_counting

    def force_flush_member(self, member_id):
        """Call when monitoring stops or a member disappears for good, so an
        in-progress qualifying lapse still gets logged instead of being lost."""
        state = self.members.get(member_id)
        if not state:
            return
        now = time.time()
        for reason, start_ts in list(state.reason_since.items()):
            if reason in state.reason_triggered and self.on_event:
                self.on_event(member_id, reason, start_ts, now - start_ts)
        state.reason_since.clear()
        state.reason_triggered.clear()

    def flush_all(self):
        for member_id in list(self.members.keys()):
            self.force_flush_member(member_id)

    # -------------------------------------------------- identity / roster
    def report_identity(self, member_id, is_known: bool):
        """Feed whether this frame's face matched the trained roster
        (known-classroom mode only). Fires on_unknown once per continuous
        unrecognized streak, after `unknown_alert_delay` seconds."""
        state = self._get(member_id)
        now = time.time()
        if is_known:
            state.unknown_since = None
            state.unknown_notified = False
            return

        if state.unknown_since is None:
            state.unknown_since = now
        elapsed = now - state.unknown_since
        if elapsed >= self.unknown_alert_delay and not state.unknown_notified:
            state.unknown_notified = True
            if self.on_unknown:
                self.on_unknown(member_id, elapsed)

    def prune_stale(self, active_member_ids, max_age_seconds=60):
        """Drop members not seen for a while, flushing any in-progress
        qualifying lapse first so it isn't silently lost."""
        now = time.time()
        for mid in list(self.members.keys()):
            if mid not in active_member_ids and now - self.members[mid].last_seen > max_age_seconds:
                self.force_flush_member(mid)
                del self.members[mid]
