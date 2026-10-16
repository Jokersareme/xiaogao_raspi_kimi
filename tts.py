#!/usr/bin/env python3
"""tts.py — 播报：edge-tts 云端合成为主，espeak-ng 本地兜底；支持中途打断。"""
import asyncio
import logging
import os
import subprocess
import tempfile
import threading

log = logging.getLogger("xiaogao")


class TTS:
    def __init__(self, cfg: dict, enabled: bool = True):
        self.cfg = cfg
        self.enabled = enabled and bool(cfg)
        self._proc = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 对外
    def say(self, text: str, block: bool = True):
        """播报一段文本。block=False 时在后台线程播。可随时 stop() 打断。"""
        if not self.enabled or not text:
            return
        t = threading.Thread(target=self._say_sync, args=(text,), daemon=True)
        t.start()
        if block:
            t.join()

    def stop(self):
        """打断当前播报（barge-in）。"""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1)
                except Exception:
                    self._proc.kill()
            self._proc = None

    def speaking(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    # ------------------------------------------------------------------ 内部
    def _say_sync(self, text: str):
        provider = (self.cfg.get("provider") or "edge").lower()
        if provider == "edge" and self._edge(text):
            return
        if provider == "edge":
            log.warning("edge-tts 失败，降级 espeak-ng")
        if not self._espeak(text):
            log.error("TTS 完全失败，文本只能落日志: %s", text)

    def _play(self, cmd: list) -> bool:
        """运行播放器并登记句柄，便于打断。"""
        try:
            with self._lock:
                self._proc = subprocess.Popen(cmd,
                                              stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
            self._proc.wait()
            return self._proc.returncode == 0
        except FileNotFoundError:
            log.error("播放器不存在: %s", cmd[0])
            return False
        except Exception as e:
            log.error("播放失败 %s: %s", cmd, e)
            return False
        finally:
            with self._lock:
                self._proc = None

    def _edge(self, text: str) -> bool:
        tmp = None
        try:
            import edge_tts

            async def _gen(path):
                comm = edge_tts.Communicate(
                    text, self.cfg.get("voice", "zh-CN-XiaoxiaoNeural"),
                    rate=self.cfg.get("rate", "+0%"),
                    volume=self.cfg.get("volume", "+0%"))
                await comm.save(path)

            fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="xiaogao_")
            os.close(fd)
            asyncio.run(_gen(tmp))
            cmd = ["mpg123", "-q"]
            if self.cfg.get("device"):
                cmd += ["-a", self.cfg["device"]]
            cmd.append(tmp)
            return self._play(cmd)
        except Exception as e:
            log.error("edge-tts 合成失败: %s", e)
            return False
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def _espeak(self, text: str) -> bool:
        cmd = ["espeak-ng", "-v", "cmn", "-s", "150"]
        cmd.append(text)
        return self._play(cmd)
