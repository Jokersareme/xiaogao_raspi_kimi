#!/usr/bin/env python3
"""xiaogao.py — 小高语音助手主循环。

链路：唤醒（GPIO 按住说话）→ arecord 录音 → 云端 STT → brain 意图/LLM
→ 执行（空调/提醒/问答）→ TTS 播报（播报中按下按钮可打断）。
文本路（test_cli.py）复用同一套 XiaoGao.handle_text。
"""
import argparse
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime

import yaml

import brain
import reminder as reminder_mod
import smart_home
import stt
import weather
from tts import TTS


def setup_logging(log_dir: str) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    log = logging.getLogger("xiaogao")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "xiaogao.log"), maxBytes=1_000_000, backupCount=3,
        encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


class XiaoGao:
    def __init__(self, config_path: str = "config.yaml", tts_enabled: bool = True):
        with open(config_path, encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.log = logging.getLogger("xiaogao")
        self.name = self.cfg.get("assistant", {}).get("name", "小高")
        self.tts = TTS(self.cfg.get("tts", {}), enabled=tts_enabled)
        self.home = smart_home.SmartHome(self.cfg.get("smart_home", {}))
        self.reminders = reminder_mod.ReminderManager(
            self.cfg.get("reminder", {}), on_fire=self._on_reminder)
        self.reminders.start()
        self.history = []          # 多轮上下文 [{role, content}...]

    # ------------------------------------------------------------------ 提醒回调
    def _on_reminder(self, message: str):
        self.tts.say(f"时间到了：{message}", block=False)

    # ------------------------------------------------------------------ 核心入口
    def handle_text(self, text: str, speak: bool = True) -> dict:
        """文本进、同一套意图解析与执行链路。返回各环节结果便于验证。"""
        result = {"input": text}
        intent = brain.parse(text)
        result["intent"] = {"kind": intent.kind, "slots": intent.slots}
        reply = self._execute(intent, result)
        result["reply"] = reply
        self.log.info("handle_text: %s -> %s -> %s", text, intent.kind, reply)
        if speak:
            self.tts.say(reply)
        return result

    def _execute(self, intent: brain.Intent, result: dict) -> str:
        k = intent.kind

        if k == "empty":
            return "我没听清，你再说一遍？"

        if k == "reminder":
            parsed = reminder_mod.parse(intent.slots["text"])
            if not parsed:
                return "这个时间我没听懂，可以说“十分钟后提醒我喝水”或者“明早七点闹钟”"
            fire_at, message = parsed
            ok, msg = self.reminders.add(fire_at, message)
            result["action"] = {"reminder": message, "at": fire_at.isoformat()}
            return msg

        if k == "ac_set":
            temp = intent.slots.get("temp")
            if temp is None:
                presets = self.home.presets()
                if not presets:
                    return "读不到空调码表，没法调"
                names = {"cool": "制冷", "heat": "制热", "dry": "除湿", "fan": "送风"}
                mode = intent.slots.get("mode")
                have = "、".join(
                    f"{names.get(m, m)}{t}度" for m, ts in presets.items() for t in ts)
                return f"想调{names.get(mode, mode)}模式的话，报个温度就行，已录的档位有：{have}"
            ok, msg = self.home.set_temperature(temp, intent.slots.get("mode"))
            result["action"] = {"ac_set": {"temp": temp, "mode": intent.slots.get("mode")},
                                "ok": ok}
            return msg

        if k == "ac_off":
            ok, msg = self.home.turn_off()
            result["action"] = {"ac_off": ok}
            return msg

        if k == "ac_on":
            ok, msg = self.home.turn_on()
            result["action"] = {"ac_on": ok}
            return msg

        if k == "ac_status":
            msg = self.home.status()
            result["action"] = {"ac_status": msg}
            return msg

        if k == "time_query":
            return "现在是" + datetime.now().strftime("%H点%M分")

        if k == "date_query":
            now = datetime.now()
            week = "一二三四五六日"[now.weekday()]
            return now.strftime(f"今天是%Y年%m月%d日，星期{week}")

        if k == "weather_query":
            wcfg = self.cfg.get("weather", {})
            if not wcfg.get("enabled", True):
                return "天气功能没开"
            try:
                msg = weather.get_weather(wcfg)
            except Exception as e:
                self.log.warning("天气获取失败: %s", e)
                return "网络不可用，天气问不了"
            result["action"] = {"weather": msg}
            return msg

        if k == "chat":
            try:
                reply = brain.llm_chat(intent.slots["text"], self.history,
                                       self.cfg.get("llm", {}))
            except RuntimeError as e:
                if str(e) == "no_api_key":
                    return "我的云端大脑还没配置好，先在配置文件里填上 API key 吧"
                return "网络不可用，等会儿再聊吧"
            except Exception as e:
                self.log.warning("LLM 调用失败: %s", e)
                return "网络不可用，等会儿再聊吧"
            self.history.append({"role": "user", "content": intent.slots["text"]})
            self.history.append({"role": "assistant", "content": reply})
            max_h = int(self.cfg.get("llm", {}).get("max_history", 6))
            self.history = self.history[-2 * max_h:]
            result["action"] = {"llm": True}
            return reply

        return "我还不会这个"

    # ------------------------------------------------------------------ 语音主循环
    def run_voice_loop(self):
        wcfg = self.cfg.get("wakeup", {})
        mode = wcfg.get("mode", "button")
        wake = None
        try:
            if mode == "wakeword":
                from wakeword import SnowboyWakeup
                wake = SnowboyWakeup(wcfg)
                self.log.info("主循环启动：唤醒词「%s」，播报中按按钮可打断",
                              self.name)
            else:
                from wakeup import ButtonWakeup
                wake = ButtonWakeup(wcfg)
                self.log.info("主循环启动：按钮 BCM%s 按住说话，播报中可按按钮打断",
                              wcfg.get("gpio_button", 17))
        except Exception as e:
            self.log.error("唤醒初始化失败（%s 模式）: %s；接好硬件再试，或先用 "
                           "test_cli.py，也可把 wakeup.mode 改成 button", mode, e)
            self.tts.say("启动失败，请检查麦克风、按钮或配置文件")
            return
        max_secs = int(wcfg.get("max_record_seconds", 10))
        try:
            while True:
                try:
                    if mode == "wakeword":
                        wake.wait_wake()
                    else:
                        wake.wait_press()
                except Exception as e:
                    self.log.error("唤醒监听失败: %s", e)
                    self.tts.say("麦克风不可用，请检查录音设备")
                    return
                self.tts.stop()                    # barge-in：打断当前播报
                time.sleep(0.05)
                # 录音停止条件：button 模式松开即停；wakeword 模式可按按钮提前结束
                stop_check = (wake.is_pressed if mode == "wakeword"
                              else lambda: not wake.is_pressed())
                try:
                    text = stt.record_and_transcribe(
                        self.cfg.get("stt", {}), max_secs, stop_check=stop_check)
                except RuntimeError as e:
                    reason = {"no_api_key": "语音转写还没配置 key",
                              "no_arecord": "找不到录音设备",
                              "no_base_url": "语音转写地址没配"}.get(str(e))
                    if reason:
                        self.tts.say(reason)
                        continue
                    raise
                except Exception as e:
                    self.log.error("录音/识别失败: %s", e)
                    self.tts.say("没听清，再试一次")
                    continue
                if not text:
                    self.tts.say("没听到声音")
                    continue
                self.log.info("识别结果: %s", text)
                self.handle_text(text, speak=True)
        except KeyboardInterrupt:
            self.log.info("收到 Ctrl+C，退出")
        finally:
            wake.close()
            self.reminders.stop()
            self.home.close()


def main():
    ap = argparse.ArgumentParser(description="小高语音助手")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-tts", action="store_true", help="只打印不播报")
    args = ap.parse_args()
    log = setup_logging("logs")
    bot = XiaoGao(args.config, tts_enabled=not args.no_tts)
    try:
        bot.run_voice_loop()
    finally:
        bot.reminders.stop()
        bot.home.close()


if __name__ == "__main__":
    main()
