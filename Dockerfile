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

# The service runs as this unprivileged user (see app/entrypoint.py).
RUN useradd --system --create-home --uid 10001 --user-group \
    --shell /usr/sbin/nologin app

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ffmpeg temp on the working disk, never a small tmpfs
ENV RENDER_TMPDIR=/srv/.fftmp
ENV WORK_ROOT=/srv/_jobs
ENV PYTHONDONTWRITEBYTECODE=1

# Code is owned by root and not writable by `app`: a request that manages to
# write a file still cannot replace the service's own modules. Only the job
# scratch directories belong to `app`.
RUN chmod -R go-w /srv \
    && mkdir -p /srv/.fftmp /srv/_jobs \
    && chown app:app /srv/.fftmp /srv/_jobs

WORKDIR /srv/app
EXPOSE 8000

# No `USER app` line on purpose: Render mounts the persistent disk at
# /srv/_jobs owned by root, so the container starts as root, the entrypoint
# gives `app` that directory, then drops privileges before exec'ing gunicorn.
# gunicorn itself never runs as root.
ENTRYPOINT ["python", "/srv/app/entrypoint.py"]

# One worker process (renders hold per-job state in memory; scale by running
# more instances, not more workers) with a few threads so health checks and
# status polls are never stuck behind a slow upload. How many renders run at
# once is capped in server.py (MAX_ACTIVE_JOBS), not here.
CMD ["gunicorn", "-w", "1", "--worker-class", "gthread", "--threads", "4", \
     "-b", "0.0.0.0:8000", "--timeout", "300", "--graceful-timeout", "30", \
     "server:app"]
