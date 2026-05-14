"""
SRT (Sleep Restriction Therapy) 引擎单元测试
覆盖：
- 时间工具函数
- 提示语生成
- Redis 存取（sleep_window / baseline / morning_record）
- get_last_n_sleep_records 数据聚合（diary 优先 / morning fallback）
- 核心算法 calculate_srt_recommendation：learning / restricting / stable / optimizing 四相
- TIB 安全边界钳制（4h ~ 8.5h）
- apply_srt_restriction
"""
import pytest
import json
from datetime import datetime, timedelta


# ============================================================
# 共享 fixture：自动把 srt_engine + sleep_stats 的 redis_client
# 替换成 fakeredis，让所有测试天然隔离
# ============================================================

@pytest.fixture
def srt_redis(fake_redis):
    """Patch srt_engine 和 sleep_stats 的全局 redis_client 为 fakeredis"""
    import services.srt_engine as srt
    import services.sleep_stats as ss
    orig_srt = srt.redis_client
    orig_ss = ss.redis_client
    srt.redis_client = fake_redis
    ss.redis_client = fake_redis
    yield fake_redis
    srt.redis_client = orig_srt
    ss.redis_client = orig_ss


def _today_offset(days_ago: int = 0) -> str:
    """生成相对今天的日期字符串"""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _make_diary(se: int, tst_minutes: int = 420, bed_time: str = "23:00", wake_time: str = "07:00") -> dict:
    """构造一条睡眠日记记录"""
    return {
        "bed_time": bed_time,
        "wake_time": wake_time,
        "tst_minutes": tst_minutes,
        "se": se,
    }


# ============================================================
# 1. 纯工具函数（不依赖 Redis）
# ============================================================

class TestTimeUtils:
    """时间格式化工具"""

    def test_minutes_to_time_str_basic(self):
        from services.srt_engine import minutes_to_time_str
        assert minutes_to_time_str(0) == "00:00"
        assert minutes_to_time_str(60) == "01:00"
        assert minutes_to_time_str(23 * 60) == "23:00"
        assert minutes_to_time_str(7 * 60 + 30) == "07:30"

    def test_minutes_to_time_str_overflow(self):
        """跨日溢出应取模 24h"""
        from services.srt_engine import minutes_to_time_str
        assert minutes_to_time_str(24 * 60) == "00:00"  # 整 24h
        assert minutes_to_time_str(25 * 60) == "01:00"  # 25h → 01:00


class TestSleepAdvice:
    """睡眠建议文本生成"""

    def test_high_se_high_tst_excellent(self):
        from services.srt_engine import get_sleep_advice
        msg = get_sleep_advice(avg_se=92, avg_tst=480)
        assert "很好" in msg or "保持" in msg

    def test_high_se_low_tst_can_extend(self):
        from services.srt_engine import get_sleep_advice
        msg = get_sleep_advice(avg_se=92, avg_tst=360)
        assert "延长" in msg

    def test_low_se_long_tib_lifestyle_advice(self):
        from services.srt_engine import get_sleep_advice
        msg = get_sleep_advice(avg_se=70, avg_tst=480)
        assert "床" in msg

    def test_restriction_tip_optimizing(self):
        from services.srt_engine import build_restriction_tip
        tip = build_restriction_tip("optimizing", avg_se=92, avg_tst=420, tib=450)
        assert "🌟" in tip and ("90" in tip or "效率" in tip)

    def test_restriction_tip_restricting(self):
        from services.srt_engine import build_restriction_tip
        tip = build_restriction_tip("restricting", avg_se=78, avg_tst=360, tib=390)
        assert "📉" in tip or "压缩" in tip or "推迟" in tip


# ============================================================
# 2. Redis 存取
# ============================================================

class TestSleepWindow:
    """睡眠窗口 CRUD"""

    def test_default_window_when_not_set(self, srt_redis):
        from services.srt_engine import get_sleep_window
        win = get_sleep_window("new_user")
        # 默认 23:00 ~ 07:00
        assert win == {"bed_hour": 23, "bed_min": 0, "wake_hour": 7, "wake_min": 0}

    def test_save_and_get_window(self, srt_redis):
        from services.srt_engine import save_sleep_window, get_sleep_window
        save_sleep_window("u1", 23, 30, 6, 30)
        win = get_sleep_window("u1")
        assert win == {"bed_hour": 23, "bed_min": 30, "wake_hour": 6, "wake_min": 30}


class TestSleepBaseline:
    """睡眠基线 CRUD"""

    def test_baseline_returns_none_if_not_set(self, srt_redis):
        from services.srt_engine import get_sleep_baseline
        assert get_sleep_baseline("user_no_baseline") is None

    def test_save_and_get_baseline(self, srt_redis):
        from services.srt_engine import save_sleep_baseline, get_sleep_baseline
        data = {"baseline_tib_minutes": 450, "avg_se": 88.5, "avg_tst_minutes": 420}
        save_sleep_baseline("u1", data)
        result = get_sleep_baseline("u1")
        assert result["baseline_tib_minutes"] == 450
        assert result["avg_se"] == 88.5


class TestMorningRecord:
    """晨间打卡（旧数据兼容路径）"""

    def test_morning_record_roundtrip(self, srt_redis):
        from services.srt_engine import save_morning_record, get_morning_record
        rec = {"se": 85, "tst_minutes": 420, "bed_time": "23:00"}
        save_morning_record("u1", "2026-05-01", rec)
        assert get_morning_record("u1", "2026-05-01") == rec

    def test_morning_record_missing_returns_none(self, srt_redis):
        from services.srt_engine import get_morning_record
        assert get_morning_record("u1", "2099-01-01") is None


class TestGetLastNSleepRecords:
    """统一睡眠记录读取（diary 优先，morning fallback）"""

    def test_no_records_returns_empty(self, srt_redis):
        from services.srt_engine import get_last_n_sleep_records
        assert get_last_n_sleep_records("nobody", n=7) == []

    def test_diary_takes_priority_over_morning(self, srt_redis):
        """同一天既有 diary 也有 morning → 取 diary"""
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import save_morning_record, get_last_n_sleep_records

        today = _today_offset(0)
        diary = _make_diary(se=92, tst_minutes=450)
        morning = {"se": 70, "tst_minutes": 300}  # 不应被采用
        save_sleep_diary("u1", today, diary)
        save_morning_record("u1", today, morning)

        records = get_last_n_sleep_records("u1", n=7)
        assert len(records) == 1
        # diary 的 se=92 应优先于 morning 的 se=70
        assert records[0]["se"] == 92

    def test_morning_used_as_fallback(self, srt_redis):
        """只有 morning 没有 diary → 使用 morning"""
        from services.srt_engine import save_morning_record, get_last_n_sleep_records

        today = _today_offset(0)
        save_morning_record("u1", today, {"se": 85, "tst_minutes": 420})
        records = get_last_n_sleep_records("u1", n=7)
        assert len(records) == 1
        assert records[0]["se"] == 85

    def test_se_zero_excluded(self, srt_redis):
        """se=0 的记录应被排除（视为未填写）"""
        from services.srt_engine import save_morning_record, get_last_n_sleep_records
        save_morning_record("u1", _today_offset(0), {"se": 0, "tst_minutes": 0})
        save_morning_record("u1", _today_offset(1), {"se": 88, "tst_minutes": 420})
        records = get_last_n_sleep_records("u1", n=7)
        assert len(records) == 1
        assert records[0]["se"] == 88


# ============================================================
# 3. 核心 SRT 算法：calculate_srt_recommendation
# ============================================================

class TestSRTLearningPhase:
    """学习期：记录 < 7 天"""

    def test_zero_records_phase_learning(self, srt_redis):
        from services.srt_engine import calculate_srt_recommendation
        result = calculate_srt_recommendation("brand_new_user")
        assert result["phase"] == "learning"
        assert result["has_baseline"] is False
        assert result["record_count"] == 0
        assert result["days_needed"] == 7
        # 推荐窗口应等于默认 23:00 ~ 07:00（共 8h = 480 分钟）
        assert result["recommended_tib_minutes"] == 480

    def test_three_records_phase_learning(self, srt_redis):
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation

        for i in range(3):
            save_sleep_diary("u_three", _today_offset(i), _make_diary(se=85, tst_minutes=420))

        result = calculate_srt_recommendation("u_three")
        assert result["phase"] == "learning"
        assert result["record_count"] == 3
        assert result["days_needed"] == 4  # 7 - 3

    def test_six_records_phase_learning(self, srt_redis):
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation

        for i in range(6):
            save_sleep_diary("u_six", _today_offset(i), _make_diary(se=87, tst_minutes=420))

        result = calculate_srt_recommendation("u_six")
        assert result["phase"] == "learning"
        assert result["record_count"] == 6
        assert result["days_needed"] == 1


class TestSRTRestrictionPhase:
    """≥ 7 天记录后，按 SE 分相"""

    def test_seven_records_se_optimizing_expands_tib(self, srt_redis):
        """连续 7 天 SE ≥ 90% → optimizing，TIB 扩展 +15min"""
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation

        for i in range(7):
            save_sleep_diary("u_opt", _today_offset(i), _make_diary(se=92, tst_minutes=420))

        result = calculate_srt_recommendation("u_opt")
        assert result["phase"] == "optimizing"
        assert result["avg_se"] == 92
        # tib_adjustment_minutes 应为正（扩展）
        assert result["tib_adjustment_minutes"] > 0

    def test_seven_records_se_stable_keeps_tib(self, srt_redis):
        """7 天 SE 在 [85, 90) → stable，TIB 不变"""
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation

        for i in range(7):
            save_sleep_diary("u_stable", _today_offset(i), _make_diary(se=87, tst_minutes=420))

        result = calculate_srt_recommendation("u_stable")
        assert result["phase"] == "stable"
        assert 85 <= result["avg_se"] < 90
        assert result["tib_adjustment_minutes"] == 0

    def test_seven_records_se_low_restricts(self, srt_redis):
        """7 天 SE < 85% → restricting，建议缩窗"""
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation

        # SE 80%，TST 360min（6h）→ 目标 TIB = 360 + 30 = 390min（6.5h）
        # 默认窗口是 480min（8h），所以应建议缩到 390min
        for i in range(7):
            save_sleep_diary("u_restrict", _today_offset(i),
                             _make_diary(se=80, tst_minutes=360))

        result = calculate_srt_recommendation("u_restrict")
        assert result["phase"] == "restricting"
        assert result["avg_se"] == 80
        # 推荐 TIB 应小于当前 TIB（缩窗）
        assert result["recommended_tib_minutes"] < result["current_tib_minutes"]


class TestSRTSafetyBoundaries:
    """TIB 临床安全边界钳制"""

    def test_tib_lower_bound_4h(self, srt_redis):
        """极端低 TST（如 60min）应钳到 MIN_TIB_MINUTES = 240min（4h）"""
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation, MIN_TIB_MINUTES

        for i in range(7):
            save_sleep_diary("u_short", _today_offset(i),
                             _make_diary(se=70, tst_minutes=60))

        result = calculate_srt_recommendation("u_short")
        # 不管推荐还是基线，TIB 都不应低于 4h
        assert result["recommended_tib_minutes"] >= MIN_TIB_MINUTES

    def test_tib_upper_bound_clamp(self, srt_redis):
        """极端高 TST（如 600min/10h）应钳到 MAX_TIB_MINUTES = 510min（8.5h）"""
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation, MAX_TIB_MINUTES

        for i in range(7):
            save_sleep_diary("u_long", _today_offset(i),
                             _make_diary(se=92, tst_minutes=600))

        result = calculate_srt_recommendation("u_long")
        # 算法 target_tib = min(TST+30, MAX_TIB_MINUTES) = 510min
        # optimizing 还会 +15 但仍被 MAX 钳制
        assert result["recommended_tib_minutes"] <= MAX_TIB_MINUTES


class TestSRTAdjustmentNeeded:
    """adjustment_needed 标志"""

    def test_no_adjustment_when_diff_le_15min(self, srt_redis):
        """如果当前 TIB 与建议 TIB 差异 ≤ 15 分钟 → adjustment_needed=False"""
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import calculate_srt_recommendation, save_sleep_window

        # 把窗口设为 6.5h（390min），目标 TIB 也是 390 (TST 360 + 30 buffer)
        save_sleep_window("u_aligned", 0, 30, 7, 0)  # 00:30 ~ 07:00 = 390min

        for i in range(7):
            save_sleep_diary("u_aligned", _today_offset(i),
                             _make_diary(se=87, tst_minutes=360))

        result = calculate_srt_recommendation("u_aligned")
        # 当前 TIB = 390，目标 TIB ~= 390，diff 应 ≤ 15
        if abs(result["current_tib_minutes"] - 390) <= 15:
            assert result["adjustment_needed"] is False


# ============================================================
# 4. apply_srt_restriction
# ============================================================

class TestApplyRestriction:
    """应用 SRT 建议（更新 sleep_window + 写入 baseline）"""

    def test_apply_updates_sleep_window(self, srt_redis):
        from services.srt_engine import apply_srt_restriction, get_sleep_window
        apply_srt_restriction("u_apply", recommended_bed_time="00:00", recommended_wake_time="07:00")
        win = get_sleep_window("u_apply")
        assert win == {"bed_hour": 0, "bed_min": 0, "wake_hour": 7, "wake_min": 0}

    def test_apply_persists_baseline_when_records_exist(self, srt_redis):
        from services.sleep_stats import save_sleep_diary
        from services.srt_engine import apply_srt_restriction, get_sleep_baseline

        for i in range(3):
            save_sleep_diary("u_b", _today_offset(i), _make_diary(se=88, tst_minutes=420))

        apply_srt_restriction("u_b", recommended_bed_time="23:30", recommended_wake_time="07:00")
        baseline = get_sleep_baseline("u_b")
        assert baseline is not None
        assert baseline["avg_se"] == 88
        # baseline TIB 不超过临床上限
        from services.srt_engine import MAX_TIB_UPPER
        assert baseline["baseline_tib_minutes"] <= MAX_TIB_UPPER
