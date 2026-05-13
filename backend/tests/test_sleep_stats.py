"""
睡眠统计服务单元测试
重点覆盖：连续天数计算、睡眠统计回退评分、日记 CRUD
"""
import pytest
import json
from datetime import datetime, timedelta

from services.sleep_stats import (
    update_streak, get_streak_days, get_user_sleep_stats,
    get_sleep_diary, save_sleep_diary
)


class TestSleepDiaryCRUD:
    """睡眠日记 Redis CRUD"""

    def test_save_and_get_diary(self, fake_redis):
        # 临时替换全局 redis_client 为 fake_redis
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            diary = {"bed_time": "23:00", "wake_time": "07:00", "tst_minutes": 480, "se": 0.85}
            save_sleep_diary("user_1", "2026-05-01", diary)
            result = get_sleep_diary("user_1", "2026-05-01")
            assert result == diary
        finally:
            ss.redis_client = original

    def test_get_nonexistent_diary(self, fake_redis):
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            result = get_sleep_diary("user_1", "2026-01-01")
            assert result is None
        finally:
            ss.redis_client = original


class TestStreak:
    """连续使用天数计算"""

    def test_update_streak_first_time(self, fake_redis):
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            days = update_streak("user_streak_1")
            assert days == 1
            assert get_streak_days("user_streak_1") == 1
        finally:
            ss.redis_client = original

    def test_update_streak_consecutive(self, fake_redis):
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            fake_redis.set("user:streak:user_streak_2", json.dumps({"current_streak": 5, "last_date": yesterday}))
            days = update_streak("user_streak_2")
            assert days == 6
        finally:
            ss.redis_client = original

    def test_update_streak_broken(self, fake_redis):
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            fake_redis.set("user:streak:user_streak_3", json.dumps({"current_streak": 10, "last_date": two_days_ago}))
            days = update_streak("user_streak_3")
            assert days == 1
        finally:
            ss.redis_client = original

    def test_update_streak_same_day(self, fake_redis):
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            fake_redis.set("user:streak:user_streak_4", json.dumps({"current_streak": 3, "last_date": today}))
            days = update_streak("user_streak_4")
            assert days == 3
        finally:
            ss.redis_client = original


class TestSleepStats:
    """睡眠统计计算"""

    def test_get_user_sleep_stats_empty(self, fake_redis):
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            stats = get_user_sleep_stats("user_stats_1")
            assert stats["total_minutes"] == 0
            assert stats["total_records"] == 0
            assert stats["latest_score"] == 0
        finally:
            ss.redis_client = original

    def test_get_user_sleep_stats_with_fallback_score(self, fake_redis):
        import services.sleep_stats as ss
        original = ss.redis_client
        ss.redis_client = fake_redis
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            diary = {
                "bed_time": "23:00", "wake_time": "07:00",
                "tst_minutes": 480, "se": 0.85, "sleep_quality": 4,
                "sleep_score": 0
            }
            save_sleep_diary("user_stats_2", today, diary)
            stats = get_user_sleep_stats("user_stats_2")
            assert stats["total_records"] == 1
            assert stats["total_minutes"] == 480
            # 回退计算: 85 * 0.6 + 4 * 4 = 51 + 16 = 67
            assert stats["latest_score"] == 67
        finally:
            ss.redis_client = original
