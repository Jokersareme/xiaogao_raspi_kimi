#!/usr/bin/env python3
"""brain.py — 意图解析（本地规则，离线可用）+ LLM 对话兜底。"""
import logging
import re
from dataclasses import dataclass, field

import requests

log = logging.getLogger("xiaogao")

MODE_WORDS = {"制冷": "cool", "制热": "heat", "除湿": "dry", "送风": "fan", "自动": "auto"}

# 提醒类先匹配（“10分钟后提醒我开空调”按提醒处理，消息内容原样播报）
REMINDER_HINT = re.compile(r"提醒|闹钟|叫我|喊我")


@dataclass
class Intent:
    kind: str                      # ac_set / ac_off / ac_on / ac_status / reminder
                                   # time_query / date_query / weather_query / chat
    slots: dict = field(default_factory=dict)


def parse(text: str) -> Intent:
    t = (text or "").strip()
    if not t:
        return Intent("empty")

    if REMINDER_HINT.search(t):
        return Intent("reminder", {"text": t})

    # 空调状态
    if re.search(r"空调.*(状态|怎么样|几度|多少度|开着吗|关着吗|开没开)|(?<!调)什么状态", t):
        return Intent("ac_status")

    # 空调关机
    if re.search(r"(关掉|关闭|关了|关)\s*空调|空调.{0,4}(关掉|关闭|关了)\b", t):
        return Intent("ac_off")

    # 空调设温/设模式（“把卧室空调调到26度”“空调制冷26度”“26度”）
    m = re.search(r"(制冷|制热|除湿|送风|自动)?\s*(\d{1,2})\s*度", t)
    if m and ("空调" in t or m.group(1) or re.search(r"调|打|设|温度", t)):
        mode = MODE_WORDS.get(m.group(1)) if m.group(1) else None
        return Intent("ac_set", {"temp": int(m.group(2)), "mode": mode})
    m = re.search(r"(制冷|制热|除湿|送风|自动)\s*模式?", t)
    if m and "空调" in t:
        return Intent("ac_set", {"temp": None, "mode": MODE_WORDS[m.group(1)]})

    # 空调开机（无温度）
    if re.search(r"打开?\s*空调|开空调|空调打开", t):
        return Intent("ac_on")

    # 时间 / 日期
    if re.search(r"几点|什么时间|现在.*时间|报时", t):
        return Intent("time_query")
    if re.search(r"几号|星期几|周几|日期|今天.*(周|星期)|农历", t):
        return Intent("date_query")

    # 天气
    if re.search(r"天气|气温|下雨|下雪|冷不冷|热不热|外面.*(几度|怎样)", t):
        return Intent("weather_query")

    return Intent("chat", {"text": t})


def llm_chat(text: str, history: list, cfg: dict) -> str:
    """按 llm.provider 分流：openai_compat（默认）或 hunyuan。抛异常由调用方兜底。"""
    provider = (cfg.get("provider") or "openai_compat").strip()
    if provider == "hunyuan":
        return _hunyuan_chat(text, history, cfg)
    return _openai_chat(text, history, cfg)


def _hunyuan_chat(text: str, history: list, cfg: dict) -> str:
    """腾讯元器（混元）智能体对话。token/assistant_id 从 config 读。"""
    hcfg = cfg.get("hunyuan", {})
    token = (hcfg.get("token") or "").strip()
    assistant_id = (hcfg.get("assistant_id") or "").strip()
    if not token or not assistant_id:
        raise RuntimeError("no_api_key")
    msgs = history[-2 * int(cfg.get("max_history", 6)):]
    msgs.append({"role": "user", "content": [{"type": "text", "text": text}]})
    r = requests.post(
        "https://yuanqi.tencent.com/openapi/v1/agent/chat/completions",
        headers={"X-Source": "openapi",
                 "Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        json={"assistant_id": assistant_id,
              "user_id": hcfg.get("user_id", "xiaogao-raspi"),
              "stream": False,
              "messages": msgs},
        timeout=float(cfg.get("timeout", 25)),
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _openai_chat(text: str, history: list, cfg: dict) -> str:
    """调 DeepSeek 等 OpenAI 兼容接口。抛异常由调用方兜底。"""
    key = (cfg.get("api_key") or "").strip()
    if not key:
        raise RuntimeError("no_api_key")
    base = cfg["base_url"].rstrip("/")
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    msgs = [{"role": "system", "content":
             "你是语音助手“小高”，住在树莓派上，管家里的空调。回答用口语、简短，"
             "适合语音播报，一两句话即可。"}]
    msgs += history[-2 * int(cfg.get("max_history", 6)):]
    msgs.append({"role": "user", "content": text})
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": cfg.get("model", "deepseek-chat"),
              "messages": msgs,
              "temperature": float(cfg.get("temperature", 0.7)),
              "stream": False},
        timeout=float(cfg.get("timeout", 25)),
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()
