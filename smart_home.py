#!/usr/bin/env python3
"""smart_home.py — 通过 MQTT 对接 hub.py 的空调控制，只发主题、只读码表，不改 hub。"""
import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

log = logging.getLogger("xiaogao")

TEMP_RANGE = (16, 30)


class SmartHome:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.base = cfg["base_topic"].rstrip("/")
        self.room = cfg.get("room", "bedroom")
        self.timeout = float(cfg.get("state_timeout", 6))
        self._client = mqtt.Client()
        if cfg.get("username"):
            self._client.username_pw_set(cfg["username"], cfg.get("password", ""))
        self._client.on_connect = self._on_connect
        self._client.connect(cfg.get("mqtt_host", "localhost"),
                             int(cfg.get("mqtt_port", 1883)), 60)
        self._client.loop_start()
        self._state_event = threading.Event()
        self._state_msg = None
        self._client.message_callback_add(f"{self.base}/+/state", self._on_state)
        self._wait_ready(5)

    def _wait_ready(self, seconds):
        for _ in range(int(seconds * 10)):
            if self._client.is_connected():
                return
            time.sleep(0.1)

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(f"{self.base}/+/state")
        log.info("smart_home MQTT 已连接 rc=%s", rc)

    def _on_state(self, client, userdata, msg):
        try:
            self._state_msg = json.loads(msg.payload.decode("utf-8", "ignore"))
        except Exception:
            self._state_msg = None
        self._state_event.set()

    # ------------------------------------------------------------------ 码表
    def presets(self) -> dict:
        """读取 hub 已录码表 -> {mode: [temps...]}，另含 off。"""
        out = {}
        try:
            with open(self.cfg["codes_file"], encoding="utf-8") as f:
                codes = json.load(f)
        except Exception as e:
            log.error("读码表失败 %s: %s", self.cfg.get("codes_file"), e)
            return out
        for name in codes:
            if name == "off":
                continue
            if "_" in name:
                mode, _, temp = name.partition("_")
                if temp.isdigit():
                    out.setdefault(mode, []).append(int(temp))
        for v in out.values():
            v.sort()
        return out

    # ------------------------------------------------------------------ 执行
    def _send_and_confirm(self, command: str) -> bool:
        """发 set 并等 hub 回执（state.command==command 且 ts 为本次）。"""
        self._state_event.clear()
        self._state_msg = None
        pub_ts = int(time.time())
        topic = f"{self.base}/{self.room}/set"
        self._client.publish(topic, command, qos=1)
        log.info("MQTT publish %s <- %s", topic, command)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self._state_event.wait(timeout=0.5):
                self._state_event.clear()
                m = self._state_msg or {}
                if m.get("command") == command and int(m.get("ts") or 0) >= pub_ts:
                    return True
        return False

    def _resolve(self, temp: int, mode: str):
        """把目标温度映射到已录档位 -> (command, note)。失败返回 (None, 原因)。"""
        presets = self.presets()
        lo, hi = TEMP_RANGE
        if not lo <= temp <= hi:
            return None, f"温度要在{lo}到{hi}度之间"
        if not presets:
            return None, "读不到已录制的空调码表"
        if mode is None:
            mode = "cool" if "cool" in presets else sorted(presets)[0]
        temps = presets.get(mode)
        if not temps:
            have = "、".join(f"{m}模式" for m in sorted(presets))
            return None, f"这个模式还没录码，目前只有{have}"
        if temp in temps:
            return f"{mode}_{temp}", None
        nearest = min(temps, key=lambda x: abs(x - temp))
        return f"{mode}_{nearest}", f"{temp}度没有现成遥控码，已按最近的{nearest}度发送"

    def set_temperature(self, temp: int, mode: str = None):
        cmd, note = self._resolve(temp, mode)
        if cmd is None:
            return False, f"办不到：{note}"
        ok = self._send_and_confirm(cmd)
        label = f"空调已调到{cmd.split('_')[1]}度" + ("（制热）" if cmd.startswith("heat") else "")
        if not ok:
            return False, f"指令已发出，但没收到中枢确认，请看一眼空调{('；' + note) if note else ''}"
        return True, label + (f"，{note}" if note else "")

    def turn_off(self):
        if "off" not in self._raw_codes():
            return False, "办不到：码表里没有关机码"
        ok = self._send_and_confirm("off")
        return (True, "空调已关掉") if ok else (False, "关机指令已发出，但没收到中枢确认")

    def turn_on(self):
        presets = self.presets()
        if not presets:
            return False, "读不到已录制的空调码表"
        mode = "cool" if "cool" in presets else sorted(presets)[0]
        temps = presets[mode]
        return self.set_temperature(temps[len(temps) // 2], mode)

    def _raw_codes(self):
        try:
            with open(self.cfg["codes_file"], encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ------------------------------------------------------------------ 查询
    def status(self) -> str:
        self._state_event.clear()
        self._state_msg = None
        self._client.publish(f"{self.base}/{self.room}/get", "query", qos=1)
        got = self._state_event.wait(timeout=self.timeout)
        st = self._state_msg
        if not got or not st:
            return "问不到空调状态，中枢没回话"
        if not st.get("command"):
            return "还没有任何空调指令记录，我也不知道它现在什么状态"
        label = st.get("label") or st["command"]
        measured = "（这是中枢记录的最后指令，不是实测）" if not st.get("measured") else ""
        return f"空调现在的状态是：{label}{measured}"

    def close(self):
        self._client.loop_stop()
        self._client.disconnect()
