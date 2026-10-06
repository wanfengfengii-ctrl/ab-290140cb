FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /srv

COPY app/ ./app/
COPY tests/ ./tests/
COPY smoke.py verify.sh ./

RUN chmod +x verify.sh \
    && useradd --create-home appuser \
    && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8080
CMD ["python", "-m", "app.server"]
