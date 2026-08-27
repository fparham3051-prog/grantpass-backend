# Postgres (Neon) needs psycopg2-binary - see db.py and requirements.txt.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8420

EXPOSE 8420
CMD ["python3", "server.py"]
