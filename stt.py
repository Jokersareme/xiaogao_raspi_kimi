#!/usr/bin/env python3
"""stt.py — 录音（arecord 子进程，免 PortAudio）+ 云端转写（OpenAI 兼容接口）。"""
import logging
import os
import shutil
import subprocess
import tempfile
import time

import requests

log = logging.getLogger("xiaogao")


def has_input_device() -> bool:
    r = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    return "card" in r.stdout


def record_wav(path: str, max_seconds: int, stop_check=None,
               sample_rate: int = 16000) -> float:
    """按住录音：直到 stop_check() 为真或到 max_seconds。返回实际秒数。"""
    cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(sample_rate), "-c", "1",
           "-t", "wav", path]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    start = time.time()
    while proc.poll() is None and time.time() - start < max_seconds:
        if stop_check and stop_check():
            proc.terminate()
            break
        time.sleep(0.05)
    if proc.poll() is None:
        proc.terminate()
    proc.wait(timeout=3)
    return time.time() - start


def transcribe(wav_path: str, cfg: dict) -> str:
    """按 stt.provider 分流：openai_compat（默认）或 baidu。抛异常由调用方兜底。"""
    provider = (cfg.get("provider") or "openai_compat").strip()
    if provider == "baidu":
        return _transcribe_baidu(wav_path, cfg)
    return _transcribe_openai(wav_path, cfg)


def _transcribe_baidu(wav_path: str, cfg: dict) -> str:
    """百度语音识别（AipSpeech，16000Hz wav）。key 从 config 读。"""
    bcfg = cfg.get("baidu", {})
    app_id = (bcfg.get("app_id") or "").strip()
    api_key = (bcfg.get("api_key") or "").strip()
    secret_key = (bcfg.get("secret_key") or "").strip()
    if not (app_id and api_key and secret_key):
        raise RuntimeError("no_api_key")
    from aip import AipSpeech
    client = AipSpeech(app_id, api_key, secret_key)
    client.setConnectionTimeoutInMillis(int(float(cfg.get("timeout", 20)) * 1000))
    with open(wav_path, "rb") as f:
        result = client.asr(f.read(), "wav", 16000, {"dev_pid": bcfg.get("dev_pid", 1537)})
    if result.get("err_no") != 0:
        raise RuntimeError(f"baidu_asr_error_{result.get('err_no')}: {result.get('err_msg')}")
    return (result.get("result") or [""])[-1].strip()


def _transcribe_openai(wav_path: str, cfg: dict) -> str:
    """调用 OpenAI 兼容 /audio/transcriptions。抛异常由调用方兜底。"""
    key = (cfg.get("api_key") or "").strip()
    if not key:
        raise RuntimeError("no_api_key")
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("no_base_url")
    url = base + ("/audio/transcriptions" if base.endswith("/v1")
                  else "/v1/audio/transcriptions")
    with open(wav_path, "rb") as f:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            files={"file": ("speech.wav", f, "audio/wav")},
            data={"model": cfg.get("model", "whisper-1"),
                  "language": cfg.get("lang", "zh")},
            timeout=float(cfg.get("timeout", 20)),
        )
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


def record_and_transcribe(cfg: dict, max_seconds: int, stop_check=None) -> str:
    """录音并转写为文本（主循环按钮路使用）。设备/配置缺失时抛异常。"""
    if shutil.which("arecord") is None:
        raise RuntimeError("no_arecord")
    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="xiaogao_")
    os.close(fd)
    try:
        secs = record_wav(tmp, max_seconds, stop_check)
        if secs < 0.4:
            return ""
        return transcribe(tmp, cfg)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
