"""
A/B 测试配置管理
支持运营后台动态调整 SRT 阈值、系统 Prompt、TTS 参数等
所有配置持久化到 Redis，带审计日志
"""
import json
import copy
import hashlib
from typing import Dict, Any
from datetime import datetime

from infra.redis_client import redis_client
from services.admin_audit import log_admin_action

AB_CONFIG_KEY = "admin:ab_config"
AB_CONFIG_HISTORY_KEY = "admin:ab_config:history"
AB_CONFIG_HISTORY_MAX = 50

DEFAULT_CONFIG: Dict[str, Any] = {
    "srt": {
        "se_optimizing": 90,
        "se_stable": 85,
        "min_tib_hours": 4.0,
        "max_tib_hours": 8.5,
        "buffer_minutes": 30,
        "expansion_minutes": 15,
        "max_tib_upper_hours": 9.0,
    },
    "prompt": {
        "system_prompt": None,  # None 表示使用默认 CBT_SYSTEM_PROMPT
        "enable_rag": True,
        "max_context_turns": 10,
        "anxiety_detection_enabled": True,
    },
    "tts": {
        "default_voice": "female_warm",
        "default_speed": 0.9,
        "max_text_length": 500,
    },
    "crisis": {
        "auto_escalate": True,
        "webhook_url": "",
    },
}


def _deep_merge(base: dict, updates: dict):
    """递归合并配置，不删除已有键"""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def get_ab_config() -> Dict[str, Any]:
    """从 Redis 读取配置，与默认值合并"""
    try:
        raw = redis_client.get(AB_CONFIG_KEY)
        if raw:
            stored = json.loads(raw)
            config = copy.deepcopy(DEFAULT_CONFIG)
            _deep_merge(config, stored)
            return config
    except Exception as e:
        print(f"[ABConfig] 读取失败: {e}")
    return copy.deepcopy(DEFAULT_CONFIG)


def update_ab_config(updates: Dict[str, Any], operator: str = "admin") -> Dict[str, Any]:
    """更新配置，写 Redis + 审计日志 + 历史记录"""
    config = get_ab_config()
    old_config = copy.deepcopy(config)
    _deep_merge(config, updates)

    # 校验数值范围
    _validate_config(config)

    # 写入 Redis
    redis_client.set(AB_CONFIG_KEY, json.dumps(config, ensure_ascii=False))

    # 记录变更摘要
    changes = _diff_config(old_config, config)
    log_admin_action("ab_config_update", operator, {
        "changes": changes,
        "config_hash": hashlib.sha256(json.dumps(config).encode()).hexdigest()[:16]
    })

    # 写入历史
    _save_config_history(changes, operator)

    return config


def reset_ab_config(operator: str = "admin") -> Dict[str, Any]:
    """重置为默认配置"""
    config = copy.deepcopy(DEFAULT_CONFIG)
    redis_client.set(AB_CONFIG_KEY, json.dumps(config, ensure_ascii=False))
    log_admin_action("ab_config_reset", operator, {})
    return config


def get_ab_config_history(limit: int = 20) -> list:
    """获取配置变更历史"""
    try:
        raw = redis_client.lrange(AB_CONFIG_HISTORY_KEY, 0, limit - 1)
        return [json.loads(item) for item in raw]
    except Exception:
        return []


def _validate_config(config: dict):
    """校验配置值范围，越界则抛异常"""
    srt = config.get("srt", {})
    se_opt = srt.get("se_optimizing", 90)
    se_sta = srt.get("se_stable", 85)

    if not (70 <= se_sta <= se_opt <= 100):
        raise ValueError(f"SE 阈值范围不合理: stable={se_sta}, optimizing={se_opt}")

    min_tib = srt.get("min_tib_hours", 4)
    max_tib = srt.get("max_tib_hours", 8.5)
    if not (3 <= min_tib <= max_tib <= 10):
        raise ValueError(f"TIB 范围不合理: {min_tib}h ~ {max_tib}h")

    buf = srt.get("buffer_minutes", 30)
    exp = srt.get("expansion_minutes", 15)
    if not (5 <= buf <= 120):
        raise ValueError(f"缓冲时间越界: {buf}min")
    if not (5 <= exp <= 60):
        raise ValueError(f"扩展增量越界: {exp}min")

    tts = config.get("tts", {})
    spd = tts.get("default_speed", 0.9)
    if not (0.5 <= spd <= 2.0):
        raise ValueError(f"TTS 语速越界: {spd}")

    prompt = config.get("prompt", {})
    turns = prompt.get("max_context_turns", 10)
    if not (3 <= turns <= 40):
        raise ValueError(f"上下文轮次越界: {turns}")


def _diff_config(old: dict, new: dict) -> dict:
    """提取变更的字段"""
    changes = {}
    for section, values in new.items():
        if isinstance(values, dict):
            old_section = old.get(section, {})
            section_changes = {}
            for k, v in values.items():
                if old_section.get(k) != v:
                    section_changes[k] = {"from": old_section.get(k), "to": v}
            if section_changes:
                changes[section] = section_changes
        elif old.get(section) != values:
            changes[section] = {"from": old.get(section), "to": values}
    return changes


def _save_config_history(changes: dict, operator: str):
    """保存配置变更历史到 Redis List"""
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operator": operator,
            "changes": changes,
        }
        redis_client.lpush(AB_CONFIG_HISTORY_KEY, json.dumps(entry, ensure_ascii=False))
        redis_client.ltrim(AB_CONFIG_HISTORY_KEY, 0, AB_CONFIG_HISTORY_MAX - 1)
    except Exception:
        pass
