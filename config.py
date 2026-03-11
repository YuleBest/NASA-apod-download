"""
config.py — 读取 config.yaml，提供全局配置
优先级：config.yaml > 内置默认值；CLI 参数 > config.yaml
"""

import os

import yaml

_DEFAULTS: dict = {
    "api_key_file":     "api-key.txt",
    "data_dir":         "data",
    "dist_dir":         "dist",
    "workers":          4,
    "apod_start":       "1995-06-16",
    "api_rate_limit":   1000,
    "max_retry_rounds": 3,
    "start_date":       "2024-01-01",
    "end_date":         "2026-03-10",
}

_CONFIG_FILE = "config.yaml"
_cache: dict | None = None


def load() -> dict:
    """加载并缓存配置，返回最终配置字典。"""
    global _cache
    if _cache is not None:
        return _cache

    cfg = dict(_DEFAULTS)
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                overrides = yaml.safe_load(f) or {}
            cfg.update(overrides)
        except Exception as e:
            print(f"[config] 读取 {_CONFIG_FILE} 失败，使用默认值：{e}")

    _cache = cfg
    return cfg
