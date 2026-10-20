FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py wattbox.py sonos.py ruckus.py unifi.py araknis.py crestron.py cp4.py ./
CMD ["python", "-u", "agent.py"]
