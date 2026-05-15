"""
Admin 睡眠数据大盘 — 全平台睡眠指标聚合

数据来源:
- sleep_diary:{user_id}:{date}  (SE, TST, quality, planned/actual bed time)
- morning:{user_id}:{date}      (fallback SE records)
- sleep_window:{user_id}         (bed/wake time settings)
- sleep_baseline:{user_id}       (SRT baseline data)
- user:streak:{user_id}          (连续记录天数)
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

from infra.redis_client import redis_client
from services.sleep_stats import get_sleep_diary
from services.srt_engine import (
    get_sleep_window,
    get_sleep_baseline,
    get_morning_record,
    calculate_srt_recommendation,
)


def _parse_user_id_from_key(key: bytes, prefix: str) -> str:
    """从 Redis key 解析 user_id，例如 b'sleep_diary:user_123:2026-05-01' -> 'user_123'"""
    try:
        parts = key.decode().split(":")
        # sleep_diary:{user_id}:{date} -> parts[1] is user_id
        if len(parts) >= 2:
            return parts[1]
    except Exception:
        pass
    return ""


def _get_all_users_with_sleep_data(days: int = 30) -> set:
    """获取最近 N 天有睡眠数据的用户集合"""
    users = set()
    # 扫描 sleep_diary keys
    for key in redis_client.scan_iter(match="sleep_diary:*", count=1000):
        uid = _parse_user_id_from_key(key, "sleep_diary")
        if uid:
            users.add(uid)
    # 扫描 morning keys
    for key in redis_client.scan_iter(match="morning:*", count=1000):
        uid = _parse_user_id_from_key(key, "morning")
        if uid:
            users.add(uid)
    return users


def _get_user_recent_records(user_id: str, days: int = 7) -> List[dict]:
    """获取用户最近 N 天的睡眠记录（sleep_diary 优先，morning fallback）"""
    records = []
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        diary = get_sleep_diary(user_id, date)
        if diary and diary.get("se", 0) > 0:
            records.append({**diary, "date": date, "source": "diary"})
        else:
            morning = get_morning_record(user_id, date)
            if morning and morning.get("se", 0) > 0:
                records.append({**morning, "date": date, "source": "morning"})
    return records


def get_admin_sleep_dashboard(days: int = 30) -> Dict[str, Any]:
    """
    聚合全平台睡眠数据，返回运营大盘指标
    """
    users = _get_all_users_with_sleep_data(days)
    total_users = len(users)

    if not total_users:
        return {
            "total_users_with_data": 0,
            "daily_active_recorders": [],
            "avg_se": 0,
            "avg_tst_hours": 0,
            "avg_quality": 0,
            "phase_distribution": {},
            "at_risk_users": [],
            "trend": [],
            "quality_distribution": {"excellent": 0, "good": 0, "fair": 0, "poor": 0},
            "recent_records": [],
        }

    # 聚合每个用户的数据
    all_se_values = []
    all_tst_values = []
    all_quality_values = []
    phase_counts = defaultdict(int)
    at_risk_users = []
    quality_dist = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    daily_recorders = defaultdict(int)
    daily_avg_se = defaultdict(list)

    # 用于recent records
    recent_records_raw = []

    for user_id in users:
        records = _get_user_recent_records(user_id, days)
        if not records:
            continue

        # 最近 7 天记录用于 SRT 阶段计算
        recent_7 = records[:7]
        se_values = [r["se"] for r in recent_7]
        avg_se = sum(se_values) / len(se_values) if se_values else 0

        tst_values = [r.get("tst_minutes", 0) for r in recent_7 if r.get("tst_minutes", 0) > 0]
        avg_tst = sum(tst_values) / len(tst_values) if tst_values else 0

        quality_values = [r.get("sleep_quality", 0) for r in recent_7 if r.get("sleep_quality", 0) > 0]
        avg_quality = sum(quality_values) / len(quality_values) if quality_values else 0

        # 全局聚合
        all_se_values.extend(se_values)
        all_tst_values.extend(tst_values)
        all_quality_values.extend(quality_values)

        # SRT 阶段
        try:
            srt = calculate_srt_recommendation(user_id)
            phase = srt.get("phase", "learning")
            phase_counts[phase] += 1
        except Exception:
            phase_counts["learning"] += 1

        # 风险用户 (SE < 70% 或 记录很少)
        if avg_se > 0 and avg_se < 70:
            at_risk_users.append({
                "user_id": user_id,
                "avg_se": round(avg_se, 1),
                "avg_tst_hours": round(avg_tst / 60, 1),
                "record_count": len(recent_7),
                "phase": phase,
            })

        # 质量分布
        if avg_se >= 90:
            quality_dist["excellent"] += 1
        elif avg_se >= 85:
            quality_dist["good"] += 1
        elif avg_se >= 70:
            quality_dist["fair"] += 1
        else:
            quality_dist["poor"] += 1

        # 日活记录者
        for r in records:
            daily_recorders[r["date"]] += 1
            daily_avg_se[r["date"]].append(r["se"])

        # 最近记录（取最新的一条）
        if records:
            latest = records[0]
            recent_records_raw.append({
                "user_id": user_id,
                "date": latest["date"],
                "se": latest["se"],
                "tst_hours": round(latest.get("tst_minutes", 0) / 60, 1),
                "quality": latest.get("sleep_quality", 0),
                "source": latest.get("source", "diary"),
                "phase": phase,
            })

    # 构建日趋势（最近 N 天）
    trend = []
    for i in range(days - 1, -1, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({
            "date": date,
            "recorders": daily_recorders.get(date, 0),
            "avg_se": round(sum(daily_avg_se.get(date, [])) / len(daily_avg_se.get(date, [])), 1) if daily_avg_se.get(date) else 0,
        })

    # 排序风险用户（按 SE 升序）
    at_risk_users.sort(key=lambda x: x["avg_se"])

    # 最近记录按时间排序
    recent_records_raw.sort(key=lambda x: x["date"], reverse=True)

    return {
        "total_users_with_data": total_users,
        "daily_active_recorders": [
            {"date": t["date"], "count": t["recorders"]} for t in trend
        ],
        "avg_se": round(sum(all_se_values) / len(all_se_values), 1) if all_se_values else 0,
        "avg_tst_hours": round(sum(all_tst_values) / len(all_tst_values) / 60, 1) if all_tst_values else 0,
        "avg_quality": round(sum(all_quality_values) / len(all_quality_values), 1) if all_quality_values else 0,
        "phase_distribution": dict(phase_counts),
        "at_risk_users": at_risk_users[:20],  # 最多20个
        "trend": trend,
        "quality_distribution": quality_dist,
        "recent_records": recent_records_raw[:50],  # 最近50条
        "updated_at": datetime.now().isoformat(),
    }
