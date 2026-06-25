FROM python:3.12-slim

# System deps:
#  - ffmpeg: video assembly
#  - libcairo2 + fonts: cairosvg rendering. We install Liberation fonts, which
#    are metric-compatible with Arial so the slide layouts match what was
#    designed. Without a matching font, text widths shift and titles can clip.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ffmpeg temp on the working disk, never a small tmpfs
ENV RENDER_TMPDIR=/srv/.fftmp
ENV WORK_ROOT=/srv/_jobs

WORKDIR /srv/app
EXPOSE 8000

# 1 worker: renders are CPU-heavy and hold per-job state in memory. Scale by
# running more instances behind Render, not more workers in one instance.
# Long timeout so a multi-minute encode isn't killed mid-job.
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8000", "--timeout", "1200", "server:app"]
