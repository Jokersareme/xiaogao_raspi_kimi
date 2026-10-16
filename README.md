# 小高（xiaogao）语音助手

树莓派上的中文语音助手：唤醒词/按钮唤醒 → 录音 → 云端识别 → 意图解析/LLM → 控制空调、定时提醒、问答 → 语音播报。

## 目录结构

| 文件 | 作用 |
|---|---|
| `xiaogao.py` | 主循环与意图调度（`XiaoGao.handle_text` 是文本/语音共用的入口） |
| `wakeup.py` | GPIO 按钮「按住说话」（BCM17，内部上拉，按下接 GND） |
| `wakeword.py` | snowboy 本地唤醒词「小高」（`wakeup.mode: wakeword`，需麦克风） |
| `vendor/snowboy/` | 唤醒词资产（来自 github.com/Jokersareme/Xiaogao_raspi）：Xiaogao.pmdl、arm 版 _snowboydetect.so、提示音 |
| `stt.py` | `arecord` 录音 + 转写（`stt.provider`: openai_compat 或 baidu） |
| `tts.py` | edge-tts 合成（mpg123 播放），失败自动降级 espeak-ng；`stop()` 可打断 |
| `brain.py` | 本地规则意图解析（离线）+ LLM 对话兜底（`llm.provider`: openai_compat 或 hunyuan） |
| `smart_home.py` | MQTT 对接 hub.py 的空调控制/状态查询（只发主题、只读码表） |
| `reminder.py` | 倒计时/定时/闹钟，JSON 持久化，到点播报 |
| `weather.py` | Open-Meteo 免费天气（免 key） |
| `test_cli.py` | 文本链路测试：`--selftest` 全项自检、`--stt-file x.wav` 验证转写 |
| `tests/record_sample.wav` | 真人录音样本，供 `--stt-file` 实测 STT |
| `config.yaml` | 实际配置（含 API key，勿提交） |
| `logs/` | 运行日志（轮转） |

## 使用前必须配置

`config.yaml`：

- `wakeup.mode`：`button`（按住说话）或 `wakeword`（snowboy 唤醒词「小高」，需 USB 麦克风）。
  wakeword 模式下 `gpio_button` 仍可用于打断播报/提前结束录音。
- `llm.api_key`：填 DeepSeek key（https://platform.deepseek.com），日常对话才可用；
  留空时其余功能全部正常，聊天会提示未配置。也可用 `llm.provider: hunyuan` 接腾讯元器智能体。
- `stt.base_url` / `stt.api_key`：语音输入路的转写接口；或 `stt.provider: baidu` 填百度语音识别的
  `stt.baidu.app_id/api_key/secret_key`。没接麦克风可不配。
- `weather.latitude/longitude`：默认上海，改成所在城市。
- `tts.device`：若播报没声音，改成 `plughw:0,0`（3.5mm 耳机口）试试。

## 启动

```bash
cd ~/WORK/xiaogao
./venv/bin/python test_cli.py "现在几点"    # 文本测试
./venv/bin/python xiaogao.py                # 语音主循环（需接麦克风；按钮或唤醒词）

sudo systemctl start xiaogao     # 服务方式
sudo systemctl enable xiaogao    # 开机自启（确认稳定后再开）
```

## 硬件接线（按钮）

轻触按钮一端接 GPIO17（物理脚 11），另一端接 GND（任意 GND 脚）。
button 模式：按住说话、松开发送；wakeword 模式：喊「小高」唤醒，播报中按一下可打断。

## 已验证（2026-10-14，test_cli --selftest）

空调 26/25/23(映射24)/关机/状态查询、10 分钟提醒与 4 秒到点触发、明早 7 点闹钟、
时间/日期/天气、LLM 无 key 与断网兜底、edge-tts 与 espeak-ng 两条 TTS 路径、
systemd 拉起主循环。语音录音路待 USB 麦克风到货后验证。

## 升级记录（2026-10-16）

从旧项目 github.com/Jokersareme/Xiaogao_raspi 移植：snowboy 唤醒词「小高」、
百度语音识别（stt.provider: baidu）、腾讯元器对话（llm.provider: hunyuan）。
原仓库中硬编码的 key 已迁入 config.yaml（不入库）。

注意：旧仓库自带的 `_snowboydetect.so` 是 aarch64 的，当前 32 位系统（armv7l）
不能直接加载；已用官方 snowboy 源码树在树莓派上重新编译 32 位版
（见 `vendor/snowboy/src-build/`，含 rpi 静态库与 swig Makefile，可复现）。
唤醒词模式需要 USB 麦克风；无麦克风时进程会停留在监听状态（对着无声流），
`wakeword.py` 内置 5 秒无数据看门狗，音频通路真正损坏时会报错退出。
