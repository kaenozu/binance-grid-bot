FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim

RUN groupadd -r botuser && useradd -r -g botuser -d /app botuser
WORKDIR /app

COPY --from=builder /root/.local /home/botuser/.local
COPY --chown=botuser:botuser . .

USER botuser
ENV PATH=/home/botuser/.local/bin:$PATH

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)" || exit 1

CMD ["python", "main.py"]
