#!/bin/bash
# 小高安装脚本：venv + 依赖 + TTS 工具 + systemd unit（不 enable）
set -e
cd "$(dirname "$0")"

echo "[setup] 安装系统组件 espeak-ng / mpg123 / portaudio（snowboy 唤醒词依赖）..."
sudo apt-get update -qq
sudo apt-get install -y -qq espeak-ng mpg123 portaudio19-dev

echo "[setup] 创建 venv ..."
python3 -m venv venv

echo "[setup] 安装 Python 依赖 ..."
./venv/bin/pip install --no-cache-dir -r requirements.txt

[ -f config.yaml ] || { cp config.example.yaml config.yaml; echo "[setup] 已从模板生成 config.yaml"; }

mkdir -p logs

echo "[setup] 安装 systemd 服务（不 enable）..."
sudo cp xiaogao.service /etc/systemd/system/xiaogao.service
sudo systemctl daemon-reload

echo
echo "完成。启动方式（任选）："
echo "  前台调试:  cd ~/WORK/xiaogao && ./venv/bin/python test_cli.py \"现在几点\""
echo "  手动服务:  sudo systemctl start xiaogao"
echo "  开机自启:  sudo systemctl enable xiaogao   （确认稳定后再执行）"
