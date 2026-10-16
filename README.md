# 小高（xiaogao）语音助手

跑在树莓派上的中文语音助手。喊一声「小高」（或按住按钮）→ 录音 → 云端转写 →
本地意图解析 / 云端大模型 → 控制家里空调、设提醒闹钟、问时间天气 → 语音播报结果。

唤醒词识别（snowboy）在本地运行，不上传音频；家居控制走本地 MQTT，断外网也能用。

## 功能一览

| 功能 | 说明 | 示例 |
|---|---|---|
| 日常对话 | 唤醒后任意聊天，多轮上下文（LLM 可配 DeepSeek 或腾讯元器） | 「小高，今天过得好无聊」 |
| 空调控制 | 通过 MQTT 对接 home-hub 红外中枢，只发已录遥控码 | 「把卧室空调调到26度」「空调制冷25度」「关掉空调」 |
| 空调状态 | 读中枢记录的最后状态（注明非实测） | 「现在空调什么状态」 |
| 提醒/闹钟 | 倒计时、定时、明早闹钟，JSON 持久化，到点播报 | 「10分钟后提醒我喝水」「明早7点闹钟」 |
| 时间/日期 | 离线可用 | 「现在几点」「今天几号星期几」 |
| 天气 | Open-Meteo 免费接口（免 key） | 「今天天气怎么样」 |
| 打断（barge-in） | 播报中按按钮立即停 | — |
| 离线兜底 | 断网时本地意图照常工作，并播报「网络不可用」 | — |

## 运行环境

**硬件**

- 树莓派（已在 Raspberry Pi 4、Raspbian 12、armv7l 32 位验证；Pi 3/Zero 理论可用，唤醒词识别更吃力）
- USB 全向麦克风（wakeword 模式与语音输入必需；button 文本路不需要）
- 扬声器：3.5mm 耳机口或 HDMI 音箱
- 轻触按钮（可选，强烈建议）：接 GPIO17（物理脚 11）与 GND，内部上拉
- 电源建议 5V/3A（挂麦克风+音箱后欠压会重启）

**系统与网络**

- Raspberry Pi OS (Debian 12+)，Python 3.11（3.9+ 均可）
- 依赖已有的本地服务（本助手只对接、不改动它们）：
  Mosquitto MQTT broker、`hub.service`（`~/WORK/smart_home/home-hub`，红外空调中枢）、`pigpiod`
- 网络要求：edge-tts（微软 TTS 端点）与所选 LLM/STT 的 API 可达即可；
  百度语音识别、腾讯元器、DeepSeek 已在目标网络实测可达

## 安装

在树莓派上：

```bash
git clone https://github.com/Jokersareme/xiaogao_raspi_kimi.git ~/WORK/xiaogao
cd ~/WORK/xiaogao
bash setup.sh        # apt 装系统组件 → 建 venv → pip 装依赖 → 生成 config.yaml → 装 systemd unit（不 enable）
```

`setup.sh` 做的事：安装 `espeak-ng / mpg123 / portaudio19-dev`；创建 `venv` 并安装
`requirements.txt`；从模板生成 `config.yaml`；安装 `xiaogao.service` 并 `daemon-reload`。

## 依赖

**系统包**（setup.sh 自动装）：`espeak-ng`（TTS 离线兜底）、`mpg123`（播放 edge-tts 音频）、
`portaudio19-dev`（PyAudio 编译头文件，唤醒词用）

**Python 包**（requirements.txt）：

| 包 | 用途 |
|---|---|
| `paho-mqtt` | 对接 Mosquitto 控制空调 |
| `requests` / `PyYAML` | HTTP API / 配置解析 |
| `edge-tts` | 在线中文 TTS（免费） |
| `pyaudio` | snowboy 唤醒词取麦克风流 |
| `baidu-aip` (+`chardet`) | 百度语音识别 provider |
| `RPi.GPIO` | 按钮（仅 armv7l 安装） |

唤醒词的二进制 `_snowboydetect.so` 已随仓库提供（32 位 ARM 重编译版），无需自行构建。

## 配置

所有配置在 `config.yaml`（由 `config.example.yaml` 复制生成，**已 gitignore，不要提交**）。
API key 只写在这里。

| 配置段 | 关键项 | 说明 |
|---|---|---|
| `wakeup` | `mode` | `button` = 按住说话；`wakeword` = 喊「小高」唤醒（需麦克风） |
| | `gpio_button` / `sensitivity` / `audio_gain` | 按钮 BCM 脚号（wakeword 下兼作打断）；唤醒灵敏度 0~1；麦克风增益 |
| `stt` | `provider` | `openai_compat`（OpenAI 兼容转写接口）或 `baidu`（百度语音识别） |
| | `base_url`/`api_key` 或 `baidu.*` | 按 provider 填；key 留空则语音输入路不可用，文本路不受影响 |
| `tts` | `voice` / `device` | edge-tts 音色；播报没声音时把 `device` 改成 `plughw:0,0` |
| `llm` | `provider` | `openai_compat`（DeepSeek 等）或 `hunyuan`（腾讯元器智能体） |
| | `api_key` 或 `hunyuan.token/assistant_id` | 按 provider 填；留空时聊天会提示未配置，其余功能正常 |
| `smart_home` | `base_topic` / `codes_file` | home-hub 的 MQTT 主题前缀与空调码表路径（按实际部署改） |
| `weather` | `latitude` / `longitude` | 所在城市坐标（默认上海） |

## 使用方法

```bash
cd ~/WORK/xiaogao

# 文本链路测试（与语音路共用同一套意图解析与执行，不需要麦克风）
./venv/bin/python test_cli.py "现在几点"
./venv/bin/python test_cli.py --speak "把卧室空调调到26度"     # 并播报
./venv/bin/python test_cli.py --stt-file tests/record_sample.wav  # 真实转写一条录音样本
./venv/bin/python test_cli.py --selftest                     # 全项自检

# 语音主循环（需麦克风）
./venv/bin/python xiaogao.py            # 加 --no-tts 只打印不播报

# systemd 服务
sudo systemctl start xiaogao            # 启动
sudo systemctl status xiaogao           # 看状态
journalctl -u xiaogao -f                # 跟日志
sudo systemctl enable xiaogao           # 开机自启（确认稳定后再执行）
```

**两种交互模式**

- `button`：按住按钮说话，松开发送；播报中按一下打断。
- `wakeword`：喊「小高」→ 播提示音 → 直接说指令（最长录 10 秒，按按钮可提前结束）；
  播报中按按钮打断。

## 目录结构

| 路径 | 作用 |
|---|---|
| `xiaogao.py` | 主循环与意图调度（`XiaoGao.handle_text` 是文本/语音共用的入口） |
| `wakeup.py` | GPIO 按钮「按住说话」 |
| `wakeword.py` | snowboy 本地唤醒词「小高」（含无数据看门狗） |
| `vendor/snowboy/` | 唤醒词资产：Xiaogao.pmdl、32 位 `_snowboydetect.so`、提示音、`src-build/` 重编译工程 |
| `stt.py` | `arecord` 录音 + 转写（provider 可切换） |
| `tts.py` | edge-tts 合成（mpg123 播放），失败自动降级 espeak-ng；`stop()` 打断 |
| `brain.py` | 本地规则意图解析（离线）+ LLM 对话（provider 可切换） |
| `smart_home.py` | MQTT 对接 home-hub 的空调控制/状态查询 |
| `reminder.py` | 倒计时/定时/闹钟，JSON 持久化，到点播报 |
| `weather.py` | Open-Meteo 免费天气 |
| `test_cli.py` | 测试入口：`--selftest` / `--stt-file` / 单条 / 交互模式 |
| `tests/record_sample.wav` | 真人录音样本，供 `--stt-file` 实测转写 |
| `xiaogao.service` | systemd unit（崩溃自动重启） |
| `setup.sh` / `requirements.txt` / `config.example.yaml` | 安装脚本 / 依赖清单 / 配置模板 |
| `config.yaml` / `logs/` | 实际配置（含 key，勿提交）/ 运行日志（自动轮转） |

## 维护方法

**日志**：运行日志在 `logs/xiaogao.log`（1MB × 3 份轮转）；服务方式用
`journalctl -u xiaogao -f`。识别文本、MQTT 收发、LLM 调用都有记录。

**常见问题**

| 现象 | 排查 |
|---|---|
| 播报没声音 | `config.yaml` 的 `tts.device` 改成 `plughw:0,0`；`aplay -l` 确认声卡 |
| 唤醒词没反应 | 确认 `wakeup.mode: wakeword` 且 `arecord -l` 能看到麦克风；调高 `sensitivity`/`audio_gain`；安静环境重试 |
| 语音转写失败 | 看日志里 baidu_asr_error 码；确认网络可达 aip.baidubce.com；key 是否过期 |
| 空调控制无响应 | 确认 `hub.service` active、码表路径存在、`base_topic` 与 home-hub 配置一致 |
| wakeword 模式启动即报「麦克风不可用」 | 音频通路损坏或设备被占用，`wakeword.py` 看门狗已触发，检查麦克风插拔/占用进程 |

**唤醒词 .so 重编译**（系统大版本升级后如加载失败）：

```bash
cd ~/WORK/xiaogao/vendor/snowboy/src-build/swig/Python3
sudo apt-get install -y swig g++ python3-dev libatlas-base-dev
make
cp _snowboydetect.so snowboydetect.py ../..
```

**补录空调遥控码**：在 home-hub 目录用 `python record.py cool_23` 之类的命令补录新档位，
xiaogao 会自动识别码表里的新档位（无需改代码）。

**更换 LLM / STT**：只改 `config.yaml` 的 `provider` 和对应 key 即可切换
百度↔OpenAI 兼容转写、混元↔DeepSeek 对话；切换后跑一遍 `--selftest` 回归。

**安全**：`config.yaml` 已 gitignore；key 泄露（如曾硬编码进公开仓库）后请去对应平台
重置，再改 `config.yaml`，不要改代码。

## 验证记录

- 2026-10-14（首次部署，`--selftest`）：空调 26/25/23(映射最近档)/关机/状态查询、
  10 分钟提醒与 4 秒到点真实触发、明早 7 点闹钟、时间/日期/天气、LLM 无 key 与断网兜底、
  edge-tts 与 espeak-ng 两条 TTS 路径、systemd 拉起主循环。
- 2026-10-16（本次升级）：snowboy 32 位 .so 加载与模型构造、百度 STT 转写真实录音样本、
  混元对话返回人设回答、selftest 全项回归、systemd start/stop；现有
  mosquitto/hub/web_control/pigpiod/cloudflared 服务未动、全部 active。

## 来源与许可

- 唤醒词与百度/混元接入移植自早期原型 [Jokersareme/Xiaogao_raspi](https://github.com/Jokersareme/Xiaogao_raspi)；
  snowboy 底层来自已归档的 [Kitt-AI/snowboy](https://github.com/Kitt-AI/snowboy)，
  `_snowboydetect.so` 由官方 rpi 静态库重编译（aarch64 原版不兼容 32 位系统）。
- snowboy 模型与音频资源遵循其原作者的许可；其余代码随意使用。
