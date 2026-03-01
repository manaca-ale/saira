FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/
COPY templates /app/templates
COPY static /app/static

EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["/bin/sh", "-c", "exec gunicorn --bind 0.0.0.0:5000 --worker-class gthread --workers ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-90} --keep-alive ${GUNICORN_KEEPALIVE:-15} --worker-tmp-dir /dev/shm --access-logfile - --error-logfile - --log-level ${GUNICORN_LOG_LEVEL:-info} server:app"]
