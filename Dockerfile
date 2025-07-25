# syntax=docker/dockerfile:1
FROM python:3.10.5-slim-buster
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY *.py /app/
COPY ./data/ /app/data/
CMD ["python", "./main.py"]
