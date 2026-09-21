# -*- coding: utf-8 -*-
"""模型配置的读写

配置存放于 backend/data/settings.json：

    {
      "llm_mode": "local",
      "local":  { "base_url": "...", "model": "MiniCPM5-1B" },
      "cloud":  { "base_url": "...", "api_key": "...", "model": "..." },
      "top_k": 3
    }

安全提示：API Key 以明文存于本地文件，仅适用于单机自用场景。
对外分发时需要改为系统凭据库或加密存储。
"""

import json
from pathlib import Path

from core.config import LLM_PROFILES, SETTINGS_PATH, TOP_K

# 允许持久化的字段，避免前端写入无关内容
_ALLOWED_KEYS = {"llm_mode", "local", "cloud", "top_k"}


def _defaults() -> dict:
    """默认配置：以 config.py 中的档案为基准"""
    return {
        "llm_mode": "local",
        "local": {
            "base_url": LLM_PROFILES["local"]["base_url"],
            "model": LLM_PROFILES["local"]["model"],
        },
        "cloud": {
            "base_url": LLM_PROFILES["cloud"]["base_url"],
            "api_key": LLM_PROFILES["cloud"]["api_key"],
            "model": LLM_PROFILES["cloud"]["model"],
        },
        "top_k": TOP_K,
    }


class SettingsStore:
    """模型配置的持久化"""

    def __init__(self, path: Path | str = SETTINGS_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict:
        """读取配置，缺失字段用默认值补齐"""
        data = _defaults()
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                saved = {}
            for key, value in saved.items():
                if key not in _ALLOWED_KEYS:
                    continue
                # 嵌套字典做合并，避免旧配置缺字段导致前端读取异常
                if isinstance(value, dict) and isinstance(data.get(key), dict):
                    data[key].update(value)
                else:
                    data[key] = value
        return data

    def save(self, payload: dict) -> dict:
        """保存配置，仅接受白名单字段"""
        data = self.get()
        for key, value in payload.items():
            if key not in _ALLOWED_KEYS:
                continue
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data

    def get_llm_profile(self) -> dict:
        """返回当前生效模式对应的连接参数，供 LLMClient 使用"""
        data = self.get()
        mode = data.get("llm_mode", "local")
        profile = data.get(mode, {})
        return {
            "mode": mode,
            "base_url": profile.get("base_url") or LLM_PROFILES[mode]["base_url"],
            "api_key": profile.get("api_key") or LLM_PROFILES[mode]["api_key"],
            "model": profile.get("model") or LLM_PROFILES[mode]["model"],
        }
