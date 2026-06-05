"""
P0-1 个人焦虑基线 (2026-06)

设计:
- 把每轮 cbt_manager 检测到的 AnxietyLevel 数字化(0-3),滚动写入 Redis 列表;
- 对每个 user_id 维护一个 14 天 / 最近 N 轮的窗口,计算 mean / std / p25 / p75;
- 暴露 `compute_deviation(user_id, current_level)` 给 process_message 用,
  当前轮焦虑分 - mean > deviation_threshold (默认 2σ) 即标记"今晚不太一样";
- **不替换** 现有 AnxietyLevel 阈值机制; 仅作为 _meta 字段额外暴露给前端,
  让小程序/web 可以选择是否提示"看你今晚跟平时不一样,要不要多陪陪?"。

Redis schema:
- `anxiety:scores:{user_id}` ZSET — score 是 unix ts ms, member 是 'ts_ms:level_int'
  (避免同一 ts ms 不同 level 冲突, 不可去重 — 同一 ts 同一 level 是合理重复)
- `anxiety:baseline:{user_id}` HASH — { mean, std, p25, p75, n, last_updated_ms }
  TTL = 365 天 (一年没用就当冷启动重来)

不依赖 cron — process_message 写入新值后,如果距离上次 baseline 更新超 1 小时
或样本量 +5, 同步重算一次 (重算成本 O(n), n 最多 ~200, 微秒级)。

兼容: Redis 不可用时全部静默无操作 (cbt_manager.process_message 不阻塞)。
"""
from __future__ import annotations

import math
import time
import uuid
from typing import Dict, List, Optional

# AnxietyLevel 值映射 — cbt_manager.AnxietyLevel 是 Enum,在这里只接受字符串/int,
# 避免循环依赖。调用方先把 level 转成 _level_to_int 再传进来。
LEVEL_TO_INT = {
    "normal": 0,
    "mild": 1,
    "moderate": 2,
    "severe": 3,
}
INT_TO_LEVEL = {v: k for k, v in LEVEL_TO_INT.items()}


# Redis key helpers
def _scores_key(user_id: str) -> str:
    return f"anxiety:scores:{user_id}"


def _baseline_key(user_id: str) -> str:
    return f"anxiety:baseline:{user_id}"


# 窗口与参数
WINDOW_DAYS = 14
MAX_SAMPLES = 200
TTL_SECONDS = 365 * 24 * 3600
RECOMPUTE_INTERVAL_SECONDS = 3600
RECOMPUTE_SAMPLE_DELTA = 5
DEVIATION_SIGMA_THRESHOLD = 2.0
MIN_SAMPLES_FOR_BASELINE = 10  # < 10 轮算冷启动,不做偏离判断


def level_to_int(level) -> int:
    """把 AnxietyLevel enum / str / int 统一成 0-3 整数。"""
    if isinstance(level, int):
        return max(0, min(3, level))
    if hasattr(level, "value"):
        level = level.value
    if isinstance(level, str):
        return LEVEL_TO_INT.get(level.lower(), 0)
    return 0


def _redis_or_none():
    try:
        from infra.redis_client import redis_client
        return redis_client if redis_client else None
    except Exception:
        return None


def record_anxiety(user_id: str, level) -> None:
    """每轮 process_message 都调一次, 写入新观测值。"""
    r = _redis_or_none()
    if not r or not user_id:
        return
    try:
        score_int = level_to_int(level)
        now_ms = int(time.time() * 1000)
        # uuid 短后缀防同毫秒内同 level 被去重 (zset member 唯一)
        member = f"{now_ms}:{score_int}:{uuid.uuid4().hex[:6]}"
        key = _scores_key(user_id)
        r.zadd(key, {member: now_ms})
        r.expire(key, TTL_SECONDS)
        # 修剪老数据 (>14 天) + 保留最近 MAX_SAMPLES 条
        cutoff_ms = now_ms - WINDOW_DAYS * 86400 * 1000
        r.zremrangebyscore(key, "-inf", cutoff_ms)
        total = r.zcard(key)
        if total and total > MAX_SAMPLES:
            r.zremrangebyrank(key, 0, total - MAX_SAMPLES - 1)
        # 触发重算 (条件式)
        _maybe_recompute(r, user_id)
    except Exception as e:
        # 永不阻塞主链路
        print(f"[anxiety_baseline.record] non-fatal: {e}")


def _maybe_recompute(r, user_id: str) -> None:
    """满足触发条件就重算 baseline。"""
    try:
        b = r.hgetall(_baseline_key(user_id))
        if isinstance(next(iter(b.keys()), b""), bytes):
            b = {k.decode(): v.decode() for k, v in b.items()}
        now_ms = int(time.time() * 1000)
        last = int(b.get("last_updated_ms", "0") or 0)
        n_prev = int(b.get("n", "0") or 0)
        n_now = r.zcard(_scores_key(user_id))
        need = (now_ms - last > RECOMPUTE_INTERVAL_SECONDS * 1000) \
               or (n_now - n_prev >= RECOMPUTE_SAMPLE_DELTA) \
               or n_prev == 0
        if not need:
            return
        recompute_baseline(user_id)
    except Exception as e:
        print(f"[anxiety_baseline._maybe_recompute] non-fatal: {e}")


def recompute_baseline(user_id: str) -> Optional[Dict[str, float]]:
    """强制重算并写回 hash。返回 baseline dict, 或 None 若 Redis 不可用。"""
    r = _redis_or_none()
    if not r:
        return None
    scores = _load_scores(r, user_id)
    if not scores:
        return None
    n = len(scores)
    mean = sum(scores) / n
    if n >= 2:
        var = sum((s - mean) ** 2 for s in scores) / (n - 1)
        std = math.sqrt(var)
    else:
        std = 0.0
    sorted_s = sorted(scores)
    p25 = sorted_s[max(0, int(n * 0.25) - 1)] if n else 0.0
    p75 = sorted_s[max(0, int(n * 0.75) - 1)] if n else 0.0
    baseline = {
        "mean": round(mean, 3),
        "std": round(std, 3),
        "p25": float(p25),
        "p75": float(p75),
        "n": n,
        "last_updated_ms": int(time.time() * 1000),
    }
    try:
        r.hset(_baseline_key(user_id), mapping={k: str(v) for k, v in baseline.items()})
        r.expire(_baseline_key(user_id), TTL_SECONDS)
    except Exception as e:
        print(f"[anxiety_baseline.recompute write] non-fatal: {e}")
    return baseline


def _load_scores(r, user_id: str) -> List[float]:
    """从 zset 还原最近 N 轮的整数 level 列表。"""
    raw = r.zrange(_scores_key(user_id), 0, -1) or []
    out: List[float] = []
    for m in raw:
        if isinstance(m, bytes):
            m = m.decode()
        try:
            parts = m.split(":")
            # 兼容老格式 'ts:level' 和新格式 'ts:level:uuid6'
            lvl = parts[1] if len(parts) >= 2 else "0"
            out.append(float(int(lvl)))
        except Exception:
            continue
    return out


def get_baseline(user_id: str) -> Optional[Dict[str, float]]:
    """返回 baseline dict; 缺失 或 样本 < MIN_SAMPLES_FOR_BASELINE 返 None。"""
    r = _redis_or_none()
    if not r:
        return None
    try:
        b = r.hgetall(_baseline_key(user_id))
        if not b:
            return None
        if isinstance(next(iter(b.keys()), b""), bytes):
            b = {k.decode(): v.decode() for k, v in b.items()}
        n = int(b.get("n", "0") or 0)
        if n < MIN_SAMPLES_FOR_BASELINE:
            return None
        return {
            "mean": float(b.get("mean", "0") or 0),
            "std": float(b.get("std", "0") or 0),
            "p25": float(b.get("p25", "0") or 0),
            "p75": float(b.get("p75", "0") or 0),
            "n": n,
            "last_updated_ms": int(b.get("last_updated_ms", "0") or 0),
        }
    except Exception as e:
        print(f"[anxiety_baseline.get] non-fatal: {e}")
        return None


def compute_deviation(user_id: str, current_level) -> Optional[Dict]:
    """与 baseline 对比, 返回偏离信息或 None (冷启动 / 无 redis)。

    Returns dict with:
      - z_score: 当前分 - mean / max(std, 0.5)  (std 太小用 0.5 兜底防除 0)
      - deviation_class: 'within' | 'higher' | 'lower'  (是否超 2σ)
      - alert: bool  (是否值得前端提示)
      - baseline: {mean, std, n}
    """
    baseline = get_baseline(user_id)
    if not baseline:
        return None
    score = float(level_to_int(current_level))
    sigma = max(baseline["std"], 0.5)
    z = (score - baseline["mean"]) / sigma
    deviation_class = "within"
    if abs(z) >= DEVIATION_SIGMA_THRESHOLD:
        deviation_class = "higher" if z > 0 else "lower"
    return {
        "z_score": round(z, 2),
        "deviation_class": deviation_class,
        "alert": deviation_class != "within",
        "baseline": {
            "mean": baseline["mean"],
            "std": baseline["std"],
            "n": baseline["n"],
        },
    }
