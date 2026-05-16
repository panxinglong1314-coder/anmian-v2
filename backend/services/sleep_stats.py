"""
睡眠统计服务（从 main.py 提取）
连续天数、睡眠统计、睡眠日记 Redis CRUD
"""
import json
from typing import Optional
from datetime import datetime, timedelta

from infra.redis_client import redis_client


def update_streak(user_id: str) -> int:
    """更新用户连续使用天数，返回当前连续天数"""
    key = f"user:streak:{user_id}"
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        raw = redis_client.get(key)
        if raw:
            data = json.loads(raw)
            last_date = data.get("last_date", "")
            current = data.get("current_streak", 0)
            if last_date == today:
                return current
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            if last_date == yesterday:
                current += 1
            else:
                current = 1
        else:
            current = 1
        redis_client.set(key, json.dumps({"current_streak": current, "last_date": today}, ensure_ascii=False))
        return current
    except Exception as e:
        print(f"[update_streak error] {e}")
        return 0


def get_streak_days(user_id: str) -> int:
    """获取用户当前连续使用天数"""
    key = f"user:streak:{user_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw).get("current_streak", 0)
    except Exception:
        pass
    return 0


def get_sleep_diary(user_id: str, date: str) -> Optional[dict]:
    """获取指定日期的睡眠日记"""
    key = f"sleep_diary:{user_id}:{date}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return None


def save_sleep_diary(user_id: str, date: str, diary: dict):
    """保存睡眠日记，TTL 365 天"""
    key = f"sleep_diary:{user_id}:{date}"
    redis_client.set(key, json.dumps(diary, ensure_ascii=False), ex=365*24*3600)


def get_user_sleep_stats(user_id: str) -> dict:
    """获取用户睡眠统计：90 天累计 + 近 7 天分项"""
    total_minutes = 0
    total_records = 0
    latest_score = 0
    latest_score_date = ""
    recent_7d_minutes = 0
    recent_7d_records = 0
    recent_7d_latest_score = 0  # 近 7 天最新分（如果有）
    try:
        for i in range(90):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            diary = get_sleep_diary(user_id, date)
            if diary and diary.get("tst_minutes", 0) > 0:
                total_minutes += diary.get("tst_minutes", 0)
                total_records += 1
                score = diary.get("sleep_score", 0)
                if score <= 0 and diary.get("se", 0) > 0:
                    se_percent = diary.get("se", 0) * 100
                    quality = diary.get("sleep_quality", 3)
                    score = min(100, max(0, round(se_percent * 0.6 + quality * 4)))
                if score > 0 and date > latest_score_date:
                    latest_score = score
                    latest_score_date = date
                # 近 7 天专属统计
                if i < 7:
                    recent_7d_minutes += diary.get("tst_minutes", 0)
                    recent_7d_records += 1
                    if score > 0 and recent_7d_latest_score == 0:
                        recent_7d_latest_score = score
    except Exception as e:
        print(f"[get_user_sleep_stats error] {e}")
    recent_7d_avg_hours = round(recent_7d_minutes / recent_7d_records / 60, 1) if recent_7d_records > 0 else 0

    # 连续填日记的天数（从今天/昨天往前回溯，遇到第一个无日记的日子就停）
    diary_streak_days = 0
    try:
        # 允许从今天或昨天开始（用户可能还没填今天）
        start_i = 0
        # 如果今天没填，但昨天填了，从昨天起算
        today_diary = get_sleep_diary(user_id, datetime.now().strftime("%Y-%m-%d"))
        if not (today_diary and today_diary.get("tst_minutes", 0) > 0):
            start_i = 1
        for i in range(start_i, 90):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            diary = get_sleep_diary(user_id, date)
            if diary and diary.get("tst_minutes", 0) > 0:
                diary_streak_days += 1
            else:
                break
    except Exception as e:
        print(f"[diary_streak_days error] {e}")

    return {
        "total_minutes": total_minutes,
        "total_records": total_records,
        "latest_score": latest_score,
        "latest_score_date": latest_score_date,
        "recent_7d_records": recent_7d_records,
        "recent_7d_avg_hours": recent_7d_avg_hours,
        "recent_7d_latest_score": recent_7d_latest_score,
        "diary_streak_days": diary_streak_days,
    }
