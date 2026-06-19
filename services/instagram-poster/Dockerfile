FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY instagram_poster ./instagram_poster
COPY main.py .

ENV PYTHONUNBUFFERED=1
ENV IG_OUTPUT_DIR=/data/output
ENV IG_SNS_DIR=/data/output/sns
ENV IG_STATE_DB=/data/instagram/state.db

CMD ["python", "main.py"]
