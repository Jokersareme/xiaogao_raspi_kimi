#!/usr/bin/env python3
"""test_cli.py — 文本输入替代语音，走与语音路完全相同的意图解析与执行链路。

用法：
  ./venv/bin/python test_cli.py "把卧室空调调到26度"     单条测试（默认不播报）
  ./venv/bin/python test_cli.py --speak "现在几点"       单条并播报
  ./venv/bin/python test_cli.py --stt-file x.wav         转写 wav 并走意图链路（验证 STT）
  ./venv/bin/python test_cli.py --selftest               自动逐项验证（见 VERB 列表）
"""
import argparse
import json
import threading
from datetime import datetime

import xiaogao


def show(r: dict):
    print("-" * 60)
    print(f"输入   : {r['input']}")
    print(f"意图   : {r['intent']['kind']} {r['intent']['slots']}")
    if r.get("action"):
        print(f"动作   : {json.dumps(r['action'], ensure_ascii=False)}")
    print(f"回复   : {r['reply']}")


def _fork_bot(bot, cfg):
    """复制一个共用 tts/home/reminders 的 bot，仅替换 cfg（用于兜底分支测试）。"""
    b = xiaogao.XiaoGao.__new__(xiaogao.XiaoGao)
    b.cfg = cfg
    b.log = bot.log
    b.name = bot.name
    b.tts = bot.tts
    b.home = bot.home
    b.reminders = bot.reminders
    b.history = []
    return b


def selftest(bot: xiaogao.XiaoGao, speak: bool):
    print("=" * 60)
    print("小高逐项自检（文本链路，语音链路共用同一套解析与执行）")
    print("=" * 60)
    cases = [
        "把卧室空调调到26度",
        "空调制冷25度",
        "把卧室空调调到23度",      # 未录档位 -> 映射最近档 cool_24
        "关掉空调",
        "现在空调什么状态",
        "10分钟后提醒我喝水",
        "明天早上7点闹钟",
        "现在几点",
        "今天几号星期几",
        "今天天气怎么样",
    ]
    results = []
    for c in cases:
        r = bot.handle_text(c, speak=speak)
        show(r)
        results.append(r)

    # --- 提醒到点触发：注册 4 秒倒计时，验证回调真的响 -------------------------
    print("-" * 60)
    fired = threading.Event()
    bot.reminders.on_fire = lambda msg: (print(f"提醒触发: {msg}（{datetime.now():%H:%M:%S}）"),
                                         fired.set())
    r = bot.handle_text("4秒后提醒我自检完成", speak=False)
    show(r)
    ok = fired.wait(timeout=15)
    print(f"提醒到点触发: {'OK' if ok else 'FAIL（15秒内未触发）'}")

    # --- LLM 兜底分支：key 置空 -> 应提示未配置 -------------------------------
    print("-" * 60)
    nock = dict(bot.cfg)
    nock["llm"] = dict(nock.get("llm", {}))
    if nock["llm"].get("provider", "openai_compat") == "hunyuan":
        nock["llm"]["hunyuan"] = dict(nock["llm"].get("hunyuan", {}), token="")
    else:
        nock["llm"]["api_key"] = ""
    r = _fork_bot(bot, nock).handle_text("你好呀", speak=False)
    show(r)
    print(f"无 key 兜底: {'OK' if 'key' in r['reply'] else 'CHECK'}")

    # --- 离线兜底：把 LLM 指向不可达地址，家居控制仍须工作 ----------------------
    print("-" * 60)
    bad = dict(bot.cfg)
    bad["llm"] = dict(bad.get("llm", {}), provider="openai_compat",
                      api_key="invalid", base_url="http://127.0.0.1:9")
    offline = _fork_bot(bot, bad)
    r = offline.handle_text("你好", speak=False)
    show(r)
    print(f"离线聊天兜底: {'OK' if '网络不可用' in r['reply'] else 'FAIL'}")
    r = offline.handle_text("现在几点", speak=False)
    show(r)
    print(f"离线时间问答: {'OK' if '点' in r['reply'] else 'FAIL'}")

    # --- TTS：edge-tts 合成 + espeak-ng 降级 ---------------------------------
    print("-" * 60)
    from tts import TTS
    t = TTS(bot.cfg.get("tts", {}), enabled=True)
    ok_edge = t._edge("自检，你好，我是小高")
    print(f"edge-tts 合成并尝试播放: {'OK（合成成功，播放器已跑）' if ok_edge else 'FAIL'}")
    ok_es = t._espeak("自检")
    print(f"espeak-ng 兜底路径: {'OK' if ok_es else 'FAIL'}")
    print("-" * 60)
    print("自检结束。回复汇总：")
    for r in results:
        print(f"  [{r['intent']['kind']}] {r['input']}  =>  {r['reply']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="要测试的一句话")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--speak", action="store_true", help="播报回复")
    ap.add_argument("--selftest", action="store_true", help="自动逐项验证")
    ap.add_argument("--stt-file", metavar="WAV", help="转写 wav 文件并走意图链路")
    args = ap.parse_args()

    log = xiaogao.setup_logging("logs")
    bot = xiaogao.XiaoGao(args.config, tts_enabled=args.speak)
    try:
        if args.selftest:
            selftest(bot, speak=args.speak)
        elif args.stt_file:
            import stt
            text = stt.transcribe(args.stt_file, bot.cfg.get("stt", {}))
            print(f"转写结果: {text}")
            if text:
                show(bot.handle_text(text, speak=args.speak))
        elif args.text:
            show(bot.handle_text(args.text, speak=args.speak))
        else:
            print("进入交互模式，输入一句话回车测试，空行退出。")
            while True:
                try:
                    line = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    break
                show(bot.handle_text(line, speak=args.speak))
    finally:
        bot.reminders.stop()
        bot.home.close()


if __name__ == "__main__":
    main()
