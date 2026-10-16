#!/usr/bin/env python3
"""wakeup.py — GPIO 按钮「按住说话」。软件唤醒（openwakeword 等）预留接口。"""
import logging
import time

log = logging.getLogger("xiaogao")


class ButtonWakeup:
    def __init__(self, cfg: dict):
        import RPi.GPIO as GPIO
        self.GPIO = GPIO
        self.pin = int(cfg.get("gpio_button", 17))
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def is_pressed(self) -> bool:
        return self.GPIO.input(self.pin) == self.GPIO.LOW

    def wait_press(self, poll: float = 0.1):
        """阻塞等到按下。"""
        while not self.is_pressed():
            time.sleep(poll)

    def wait_release(self, poll: float = 0.05):
        """阻塞等到松开。"""
        while self.is_pressed():
            time.sleep(poll)

    def close(self):
        self.GPIO.cleanup(self.pin)


class WakewordWakeup:
    """软件唤醒占位接口：未来接 openwakeword / Porcupine 时实现同样两个方法。"""

    def __init__(self, cfg: dict):
        raise NotImplementedError("软件唤醒未启用，请用 button 模式")
