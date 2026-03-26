FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    fluidsynth \
    fluid-soundfont-gm \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir psutil mido python-rtmidi

WORKDIR /app
COPY sonification_pipeline.py /app/sonification_pipeline.py

CMD ["python3", "sonification_pipeline.py", "--pitch-bend"]
