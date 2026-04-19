"""FastAPI app that serves iruka_cnn inference from a per-worker container."""

from __future__ import annotations

import io
import os
import socket
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request

from iruka_cnn.receiver.infer import Receiver


MODEL_PATH = os.environ.get("MODEL_PATH", "/app/models/best.pt")
DEVICE = os.environ.get("DEVICE", "cpu")

app = FastAPI(title="dolphin-poc-infer")
RECEIVER: Receiver | None = None


def _get_receiver() -> Receiver:
    global RECEIVER

    if RECEIVER is not None:
        return RECEIVER

    model_path = Path(MODEL_PATH)
    if not model_path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"model file not found at {model_path}; place trained artifacts under iruka_cnn/artifacts/models",
        )

    RECEIVER = Receiver(checkpoint_path=model_path, device_name=DEVICE)
    return RECEIVER


def _fetch_instance_id() -> str:
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        token = urllib.request.urlopen(token_req, timeout=1).read().decode()
        id_req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
        )
        return urllib.request.urlopen(id_req, timeout=1).read().decode()
    except Exception:
        return "unknown"


INSTANCE_ID = _fetch_instance_id()
HOSTNAME = socket.gethostname()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "hostname": HOSTNAME, "instance_id": INSTANCE_ID}


@app.get("/hello")
def hello() -> dict:
    receiver = _get_receiver()
    return {
        "msg": "infer worker up",
        "hostname": HOSTNAME,
        "instance_id": INSTANCE_ID,
        "model": os.path.basename(MODEL_PATH),
        "labels": len(receiver.labels),
    }


@app.post("/infer")
async def infer(request: Request) -> dict:
    wav_bytes = await request.body()
    if not wav_bytes:
        raise HTTPException(status_code=400, detail="empty body; send WAV bytes")

    try:
        waveform, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid WAV: {e!r}")

    if waveform.ndim == 2:
        waveform = waveform.mean(axis=1)  # downmix to mono
    waveform = np.ascontiguousarray(waveform, dtype=np.float32)

    try:
        receiver = _get_receiver()
        result = receiver.predict_waveform(waveform, source_rate=int(sample_rate))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"inference failed: {e!r}")

    return {
        "label": result.predicted_label,
        "text": result.predicted_text,
        "confidence": float(result.confidence),
        "raw_top_label": result.raw_top_label,
        "is_unknown": bool(result.is_unknown),
        "is_silence": bool(result.is_silence),
        "top_k": [{"label": t["label"], "score": float(t["score"])} for t in result.top_k],
        "audio_stats": {k: float(v) for k, v in result.audio_stats.items()},
        "worker": {
            "hostname": HOSTNAME,
            "instance_id": INSTANCE_ID,
        },
    }
