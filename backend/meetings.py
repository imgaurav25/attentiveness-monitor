"""
meetings.py
------------
In-memory data model for the Google-Meet-style meeting system: a host
creates a meeting and gets a shareable link; anyone with the link joins as
a participant, either by registering fresh or selecting their existing
name from the roster.

This is intentionally simple (in-memory, not a database) -- a meeting's
data only needs to live for the duration of that meeting, and the
permanent record (who was inattentive when, who was flagged as an
impersonator/extra person, for how long) is written to the same Excel log
used everywhere else in this project via core/excel_logger.py.

If you need meetings to survive a server restart, or run more than one
backend process, swap MeetingRegistry's dict for a real datastore (Redis /
Postgres) -- the interface below is small on purpose so that's a
contained change.
"""

import threading
import time
import uuid


class Participant:
    def __init__(self, participant_id, name, claimed_label_id, is_host=False):
        self.participant_id = participant_id
        self.name = name                      # display name shown in the meeting
        self.claimed_label_id = claimed_label_id  # which roster identity they claim to be (int or None if unregistered somehow)
        self.is_host = is_host
        self.joined_at = time.time()
        self.left_at = None
        self.connected = True

    def to_dict(self):
        return {
            "participant_id": self.participant_id,
            "name": self.name,
            "claimed_label_id": self.claimed_label_id,
            "is_host": self.is_host,
            "joined_at": self.joined_at,
            "connected": self.connected,
        }


class Meeting:
    def __init__(self, meeting_id, title=None):
        self.meeting_id = meeting_id
        self.title = title or f"Meeting {meeting_id}"
        self.created_at = time.time()
        self.participants = {}  # participant_id -> Participant
        self.jitsi_room_name = f"attentiveness-{meeting_id}"  # kept for backward compatibility; meeting media no longer uses Jitsi
        # The first account that joins with is_host=True becomes the
        # permanent host identity for this meeting. This survives page refreshes
        # because the meeting object remains the source of truth on the server.
        self.host_label_id = None
        self.host_name = None
        self._lock = threading.Lock()

    def add_participant(self, name, claimed_label_id, is_host=False):
        participant_id = uuid.uuid4().hex[:12]
        with self._lock:
            # Once a host identity is established, a later join by that same
            # registered identity is automatically a host re-entry.
            effective_host = bool(is_host)
            if self.host_label_id is not None and claimed_label_id is not None:
                effective_host = effective_host or int(claimed_label_id) == int(self.host_label_id)
            p = Participant(participant_id, name, claimed_label_id, is_host=effective_host)
            self.participants[participant_id] = p
            if effective_host and self.host_label_id is None:
                self.host_label_id = claimed_label_id
                self.host_name = name
        return p

    def get_participant(self, participant_id):
        return self.participants.get(participant_id)

    def mark_left(self, participant_id):
        p = self.participants.get(participant_id)
        if p:
            p.connected = False
            p.left_at = time.time()

    def list_participants(self):
        with self._lock:
            return [p.to_dict() for p in self.participants.values()]

    def to_dict(self):
        return {
            "meeting_id": self.meeting_id,
            "title": self.title,
            "jitsi_room_name": self.jitsi_room_name,
            "created_at": self.created_at,
            "participant_count": len([p for p in self.participants.values() if p.connected]),
            "host_label_id": self.host_label_id,
            "host_name": self.host_name,
        }


class MeetingRegistry:
    def __init__(self):
        self._meetings = {}
        self._lock = threading.Lock()

    def create_meeting(self, title=None):
        meeting_id = uuid.uuid4().hex[:8]
        meeting = Meeting(meeting_id, title=title)
        with self._lock:
            self._meetings[meeting_id] = meeting
        return meeting

    def get(self, meeting_id):
        return self._meetings.get(meeting_id)

    def exists(self, meeting_id):
        return meeting_id in self._meetings
