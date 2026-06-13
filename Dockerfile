FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# System deps: git for project bridges, ffmpeg/espeak for optional audio.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY jarvis ./jarvis
COPY config.yaml ./

# Install with web+daemon by default; voice/cloud are opt-in to keep image small.
RUN pip install --upgrade pip && pip install ".[web,daemon]" mcp

EXPOSE 8787
# Default to the web dashboard; override CMD for chat/daemon/voice.
CMD ["jarvis", "web", "--host", "0.0.0.0"]
