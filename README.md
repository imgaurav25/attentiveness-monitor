# Meeting/Classroom Attentiveness Monitoring System

> A computer vision-based system for real-time monitoring of participant attentiveness in meetings and classrooms using a standard laptop camera.

## Overview

The **Meeting/Classroom Attentiveness Monitoring System** is a software application designed to automate the monitoring of participant attentiveness during meetings, classrooms, training sessions, and similar environments.

The system uses a laptop camera to detect and track participants and analyzes facial features such as **head position, eye gaze, and eye closure** to identify prolonged inattentive behavior.

Instead of continuously monitoring participants manually, the system provides real-time alerts and maintains a timestamped record of detected inattentiveness events.

---

## Features

- Real-time camera-based monitoring

- Multiple participant detection and tracking

- Registered participant recognition

- Unknown person detection

- Eye-gaze and eye-closure analysis

- Real-time inattentiveness alerts

- Timestamped event recording

- Web-based monitoring dashboard

- Excel-based event logging

- Configurable inattentiveness delay (5–25 seconds)

---

## Technology Stack

- Python
- OpenCV
- MediaPipe
- FastAPI
- React.js
- WebSockets
- OpenPyXL

---

## How It Works

The system follows the workflow below:

```text
Laptop Camera
      ↓
Face Detection
      ↓
Face Tracking
      ↓
Facial Landmark Analysis
      ↓
Head Position / Eye Gaze / Eye Closure
      ↓
Attentiveness Decision
      ↓
Continuous Inattentiveness Timer
      ↓
Threshold Crossed?
      ↓
Real-Time Alert
      ↓
Event Recorded
      ↓
Excel Log + Dashboard