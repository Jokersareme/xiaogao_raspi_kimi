#!/usr/bin/env python3
"""weather.py — 天气问答（Open-Meteo，免 key；不可达时抛异常由调用方兜底）。"""
import logging

import requests

log = logging.getLogger("xiaogao")

WMO = {
    0: "晴", 1: "大致晴", 2: "多云", 3: "阴",
    45: "有雾", 48: "有雾", 51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹",
}


def get_weather(cfg: dict) -> str:
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": cfg.get("latitude", 31.23),
            "longitude": cfg.get("longitude", 121.47),
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "timezone": "auto",
        },
        timeout=10,
    )
    r.raise_for_status()
    cur = r.json()["current"]
    desc = WMO.get(cur.get("weather_code"), f"天气代码{cur.get('weather_code')}")
    return (f"现在{desc}，气温{cur['temperature_2m']:.0f}度，"
            f"湿度{cur['relative_humidity_2m']:.0f}%，"
            f"风速{cur['wind_speed_10m']:.0f}公里每小时")
