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

CMD ["python", "main.py"]
