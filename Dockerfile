# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
WORKDIR /app

# Install system dependencies and update SQLite to version >= 3.35.0
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install newer SQLite from source (3.40.1 for compatibility with ChromaDB)
RUN wget https://www.sqlite.org/2022/sqlite-autoconf-3400100.tar.gz \
    && tar xzf sqlite-autoconf-3400100.tar.gz \
    && cd sqlite-autoconf-3400100 \
    && ./configure --prefix=/usr/local \
    && make && make install \
    && cd .. && rm -rf sqlite-autoconf-3400100* \
    && ldconfig

# Set environment variable to use the new SQLite
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# Force unbuffered stdout/stderr so `print()` lines reach `docker logs -f`
# immediately (Python defaults to block-buffering when stdout is not a TTY,
# which delays data-watcher reload events and similar telemetry).
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY *.py /app/
COPY ./data/ /app/data/
CMD ["python", "./main.py"]
