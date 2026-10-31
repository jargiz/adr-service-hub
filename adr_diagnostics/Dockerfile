FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY diagnostics.py analysis.py server.py ui.html adr-logo.b64 ./
CMD ["python", "-u", "server.py"]
