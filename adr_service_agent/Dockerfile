FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py wattbox.py sonos.py ruckus.py unifi.py araknis.py crestron.py cp4.py control4.py service_report.py bluesound.py sense.py dashboard.py dashboard_visuals.py presentation.py monitoring.py internet_test.py ruckus_controller.py dashboard.css adr-logo.b64 ./
CMD ["python", "-u", "agent.py"]
