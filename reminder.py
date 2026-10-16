#!/usr/bin/env python3
"""reminder.py — 定时/倒计时/闹钟：中文口语解析 + 到点回调 + JSON 持久化。"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger("xiaogao")

CN_HOUR = {"早上": 0, "早晨": 0, "凌晨": 0, "上午": 0, "中午": 12, "下午": 12,
           "晚上": 12, "夜里": 12, "今晚": 12, "半夜": 12}

REL_RE = re.compile(r"(\d+)\s*(秒|分钟|分|小时|个小时|钟头)后")
ABS_RE = re.compile(
    r"(明天|今天)?\s*(早上|早晨|凌晨|上午|中午|下午|晚上|夜里|今晚|半夜)?\s*"
    r"(\d{1,2})\s*(?:[点:：](\d{1,2}|半)?)")
MSG_RE = re.compile(r"(?:提醒我|叫我|喊我)(.+)$")


def _msg_of(text: str, default: str) -> str:
    m = MSG_RE.search(text)
    if m:
        return m.group(1).strip(" ，。!！")
    if "闹钟" in text:
        return "闹钟时间到了"
    return default


def parse(text: str):
    """把中文口语解析成 (fire_at: datetime, message: str)；解析不了返回 None。"""
    now = datetime.now()

    m = REL_RE.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = timedelta(seconds=n) if unit == "秒" \
            else timedelta(minutes=n) if unit in ("分钟", "分") \
            else timedelta(hours=n)
        return now + delta, _msg_of(text, f"{m.group(0)}到了")

    if not ("点" in text or ":" in text or "：" in text):
        return None
    m = ABS_RE.search(text)
    if not m:
        return None
    day_word, part, hour, minute = m.group(1), m.group(2), int(m.group(3)), m.group(4)
    if hour > 24:
        return None
    minute = 30 if minute == "半" else int(minute) if minute else 0
    target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
    if part in CN_HOUR and part not in ("中午",) and hour == 12:
        pass  # “中午12点”不加
    if part in CN_HOUR and CN_HOUR[part] == 12 and hour < 12:
        target += timedelta(hours=12)
    if part == "中午" and hour == 12:
        pass
    if part in ("凌晨", "半夜") and hour >= 12:
        target = target.replace(hour=hour - 12)
    if day_word == "明天":
        target += timedelta(days=1)
    elif day_word is None and target <= now:
        target += timedelta(days=1)   # 没说哪天且时间已过 -> 明天
    return target, _msg_of(text, "闹钟时间到了")


class ReminderManager:
    def __init__(self, cfg: dict, on_fire):
        self.store = cfg.get("store_file", "reminders.json")
        self.max = int(cfg.get("max", 20))
        self.on_fire = on_fire
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._items = self._load()
        self._thread = None

    def _load(self):
        if os.path.exists(self.store):
            try:
                with open(self.store, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.error("提醒存档损坏 %s: %s，重新建空档", self.store, e)
        return []

    def _save(self):
        with self._lock:
            try:
                with open(self.store, "w", encoding="utf-8") as f:
                    json.dump(self._items, f, ensure_ascii=False, indent=1)
            except Exception as e:
                log.error("提醒存档写入失败: %s", e)

    def add(self, fire_at: datetime, message: str):
        live = [i for i in self._items if i["at"] > time.time()]
        if len(live) >= self.max:
            return False, f"提醒太多了（上限{self.max}条），先让我办掉几条吧"
        self._items = live
        self._items.append({"at": fire_at.timestamp(), "msg": message})
        self._items.sort(key=lambda i: i["at"])
        self._save()
        return True, f"好的，{fire_at.strftime('%m月%d日 %H点%M分')}，{message}"

    def pending(self):
        return [i for i in self._items if i["at"] > time.time()]

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="reminder")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(timeout=2):
            now = time.time()
            due = [i for i in self._items if i["at"] <= now]
            if due:
                with self._lock:
                    self._items = [i for i in self._items if i["at"] > now]
                self._save()
                for item in due:
                    log.info("提醒触发: %s", item["msg"])
                    try:
                        self.on_fire(item["msg"])
                    except Exception as e:
                        log.error("提醒回调失败: %s", e)
