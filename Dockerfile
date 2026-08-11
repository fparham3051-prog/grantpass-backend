# No dependencies to install - pure Python stdlib - so this image is tiny
# and the build is just a file copy.
FROM python:3.11-slim

WORKDIR /app
COPY . .

ENV PORT=8420
ENV GRANTPASS_DB=/app/data/grantpass.db
RUN mkdir -p /app/data

EXPOSE 8420
CMD ["python3", "server.py"]
