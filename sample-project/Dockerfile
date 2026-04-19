FROM python:3.12-slim

WORKDIR /app

# torch CPU wheels. Matches the parent's trained-model version (torch 2.11).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    torch==2.11.0 torchaudio==2.11.0

# Other iruka_cnn runtime deps. Pinning to match parent's uv.lock.
RUN pip install --no-cache-dir \
    numpy==2.3.4 \
    scikit-learn==1.8.0 \
    soundfile==0.13.1 \
    PyYAML==6.0.3 \
    tqdm==4.67.3 \
    fastapi==0.115.0 \
    "uvicorn[standard]==0.32.0"

# iruka_cnn source + trained artifacts.
COPY iruka_cnn/src /app/src
COPY iruka_cnn/data/phrases.yaml /app/data/phrases.yaml
COPY iruka_cnn/artifacts/models /app/models

COPY main.py /app/

ENV PYTHONPATH=/app/src
ENV MODEL_PATH=/app/models/best.pt
ENV DEVICE=cpu
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
