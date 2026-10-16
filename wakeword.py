#!/usr/bin/env python3
"""wakeword.py — snowboy 本地唤醒词「小高」。

资产来自旧项目 github.com/Jokersareme/Xiaogao_raspi（vendor/snowboy/）：
Xiaogao.pmdl 模型 + arm 版 _snowboydetect.so，纯本地识别，不上传音频。
"""
import logging
import os
import sys

log = logging.getLogger("xiaogao")

VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "vendor", "snowboy")


class SnowboyWakeup:
    """唤醒词监听。命中「小高」播放提示音后返回。"""

    def __init__(self, cfg: dict):
        if VENDOR_DIR not in sys.path:
            sys.path.insert(0, VENDOR_DIR)
        import snowboydecoder                      # noqa: F401  验证 .so 可加载
        model = cfg.get("model") or os.path.join(VENDOR_DIR, "Xiaogao.pmdl")
        self._decoder_cls = snowboydecoder.HotwordDetector
        self._play = snowboydecoder.play_audio_file
        self.model = model
        self.sensitivity = cfg.get("sensitivity", 0.5)
        self.audio_gain = cfg.get("audio_gain", 1)
        # 先构造一次：模型损坏/.so 不兼容在这里就报错（未开音频流，无需 terminate）
        self._detector = self._make_detector()
        self._button = None
        pin = cfg.get("gpio_button")
        if pin:
            try:
                from wakeup import ButtonWakeup
                self._button = ButtonWakeup({"gpio_button": pin})
            except Exception as e:
                log.warning("唤醒词模式下按钮初始化失败（无打断/提前结束）: %s", e)

    def _make_detector(self):
        return self._decoder_cls(
            self.model, sensitivity=self.sensitivity, audio_gain=self.audio_gain)

    def is_pressed(self) -> bool:
        """有按钮时可用于打断播报/提前结束录音。"""
        return self._button.is_pressed() if self._button else False

    def wait_wake(self) -> None:
        """阻塞监听麦克风，命中「小高」后播放提示音并返回。

        PortAudio 在无可录设备时可能挂起而非报错，加了看门狗：
        超过 silence_timeout 秒没有任何音频数据进来就抛 RuntimeError。
        """
        import time as _time
        detector = self._detector
        hit = []
        last_data = [_time.time()]

        class _RB:  # 给 ring_buffer 包一层，只为记录最近一次收到数据的时间
            def __init__(self, rb):
                self._rb = rb

            def extend(self, data):
                last_data[0] = _time.time()
                self._rb.extend(data)

            def get(self, *a, **k):
                return self._rb.get(*a, **k)

        detector.ring_buffer = _RB(detector.ring_buffer)

        def on_hit():
            hit.append(True)
            self._play()

        try:
            detector.start(
                detected_callback=on_hit,
                interrupt_check=lambda: _time.time() - last_data[0] > 5)
        finally:
            detector.terminate()
            # 命中后重建，保证下一次监听状态干净；异常时重建以复位音频流
            self._detector = self._make_detector()
        if not hit:
            raise RuntimeError("no_audio_data")

    def close(self):
        try:
            if hasattr(self._detector, "stream_in"):
                self._detector.terminate()
        except Exception:
            pass
        if self._button:
            self._button.close()
