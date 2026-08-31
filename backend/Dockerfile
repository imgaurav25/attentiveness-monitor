# Backend (FastAPI) production image.
# Build from the PROJECT ROOT so this can COPY both core/ and backend/:
#   docker build -f backend/Dockerfile -t attentiveness-backend .
# (docker-compose.yml already does this correctly.)

FROM python:3.12-slim

# opencv-contrib-python and mediapipe need these system libraries even
# though the app never opens a GUI window (they're linked at import time).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY core/ ./core/
COPY backend/ ./backend/

# Data that should persist across container restarts/rebuilds -- mounted
# as volumes by docker-compose.yml. Created here (as EMPTY files/dirs) so
# Docker recognizes these paths as files vs directories correctly when
# volumes are attached -- otherwise Docker can't tell and may create a
# directory where a file was expected (a well-known Docker gotcha for
# bind-mounting files that don't exist yet).
RUN mkdir -p /app/logs/snapshots /app/dataset && \
    touch /app/labels.json /app/trained_model.yml /app/settings.json && \
    echo '{}' > /app/labels.json

EXPOSE 8000

WORKDIR /app/backend
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
