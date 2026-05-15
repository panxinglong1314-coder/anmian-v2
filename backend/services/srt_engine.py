"""
SRT (Sleep Restriction Therapy) 睡眠限制疗法引擎

基于 Sleepio / AASM 2025 指南 / European Insomnia Guideline 2023

核心逻辑：
- 学习期（前 7 天）：收集 TST，计算初始 TIB = avg(TST) + 30 分钟
- 每周评估：连续 7 天 SE ≥ 90% → TIB +15min；SE < 85% → 保持/限制
- TIB 范围：4h ~ 9h（临床安全边界）
- 起床时间固定，入睡时间动态调整
"""

from datetime import datetime, timedelta
from typing import Optional, List
import json

from infra.redis_client import redis_client
from services.sleep_stats import get_sleep_diary


# ===== 常量（保留作为默认值，运行时优先从 ab_config 读取）=====
PHASE_LABELS = {
    "learning": "学习期",
    "restricting": "限制期",
    "stabilizing": "稳定期",
    "optimizing": "优化期",
    "maintenance": "维持期",
}

# 硬编码默认值（当 ab_config 不可用时回退）
_DEFAULT_MIN_TIB_MINUTES = 4 * 60
_DEFAULT_MAX_TIB_MINUTES = int(8.5 * 60)
_DEFAULT_BUFFER_MINUTES = 30
_DEFAULT_EXPANSION_MINUTES = 15
_DEFAULT_SE_OPTIMIZING = 90
_DEFAULT_SE_STABLE = 85
_DEFAULT_MAX_TIB_UPPER = 9 * 60

# 向后兼容的模块级常量别名（测试代码仍可直接导入）
MIN_TIB_MINUTES = _DEFAULT_MIN_TIB_MINUTES
MAX_TIB_MINUTES = _DEFAULT_MAX_TIB_MINUTES
BUFFER_MINUTES = _DEFAULT_BUFFER_MINUTES
EXPANSION_MINUTES = _DEFAULT_EXPANSION_MINUTES
SE_OPTIMIZING = _DEFAULT_SE_OPTIMIZING
SE_STABLE = _DEFAULT_SE_STABLE
MAX_TIB_UPPER = _DEFAULT_MAX_TIB_UPPER


def _get_srt_constants():
    """从 A/B 配置读取 SRT 常量，失败则回退到默认值"""
    try:
        from services.ab_config import get_ab_config
        cfg = get_ab_config().get("srt", {})
        return {
            "MIN_TIB_MINUTES": int(cfg.get("min_tib_hours", 4) * 60),
            "MAX_TIB_MINUTES": int(cfg.get("max_tib_hours", 8.5) * 60),
            "BUFFER_MINUTES": cfg.get("buffer_minutes", 30),
            "EXPANSION_MINUTES": cfg.get("expansion_minutes", 15),
            "SE_OPTIMIZING": cfg.get("se_optimizing", 90),
            "SE_STABLE": cfg.get("se_stable", 85),
            "MAX_TIB_UPPER": int(cfg.get("max_tib_upper_hours", 9) * 60),
        }
    except Exception:
        return {
            "MIN_TIB_MINUTES": _DEFAULT_MIN_TIB_MINUTES,
            "MAX_TIB_MINUTES": _DEFAULT_MAX_TIB_MINUTES,
            "BUFFER_MINUTES": _DEFAULT_BUFFER_MINUTES,
            "EXPANSION_MINUTES": _DEFAULT_EXPANSION_MINUTES,
            "SE_OPTIMIZING": _DEFAULT_SE_OPTIMIZING,
            "SE_STABLE": _DEFAULT_SE_STABLE,
            "MAX_TIB_UPPER": _DEFAULT_MAX_TIB_UPPER,
        }


# ===== 时间工具 =====

def minutes_to_time_str(minutes: int) -> str:
    """将分钟数转换为 HH:MM 格式"""
    minutes = minutes % (24 * 60)
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


# ===== 睡眠窗口 =====

def get_sleep_window(user_id: str) -> dict:
    """获取用户当前睡眠窗口，未设置则返回默认值 23:00-07:00"""
    key = f"sleep_window:{user_id}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return {"bed_hour": 23, "bed_min": 0, "wake_hour": 7, "wake_min": 0}


def save_sleep_window(user_id: str, bed_hour: int, bed_min: int, wake_hour: int, wake_min: int):
    """保存用户睡眠窗口，TTL 30 天"""
    key = f"sleep_window:{user_id}"
    data = {"bed_hour": bed_hour, "bed_min": bed_min, "wake_hour": wake_hour, "wake_min": wake_min}
    redis_client.setex(key, 30 * 86400, json.dumps(data, ensure_ascii=False))


# ===== 睡眠基线 =====

def get_sleep_baseline(user_id: str) -> Optional[dict]:
    """获取睡眠限制基线数据"""
    key = f"sleep_baseline:{user_id}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return None


def save_sleep_baseline(user_id: str, data: dict):
    """保存睡眠限制基线数据，TTL 365 天"""
    key = f"sleep_baseline:{user_id}"
    redis_client.setex(key, 365 * 86400, json.dumps(data, ensure_ascii=False))


# ===== 晨间记录（兼容旧数据） =====

def save_morning_record(user_id: str, date: str, record: dict):
    """保存晨间打卡记录，TTL 365 天"""
    key = f"morning:{user_id}:{date}"
    redis_client.set(key, json.dumps(record, ensure_ascii=False), ex=365 * 24 * 3600)


def get_morning_record(user_id: str, date: str) -> Optional[dict]:
    """获取指定日期的晨间打卡"""
    key = f"morning:{user_id}:{date}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return None


def get_last_n_morning_records(user_id: str, n: int = 7) -> list:
    """获取最近 N 天有 SE 记录的晨间打卡"""
    records = []
    for i in range(n):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        record = get_morning_record(user_id, date)
        if record and record.get("se", 0) > 0:
            records.append(record)
    return records


# ===== 统一睡眠记录（sleep_diary 优先，fallback morning_record） =====

def get_last_n_sleep_records(user_id: str, n: int = 7) -> list:
    """获取最近 N 天有 SE 记录的睡眠日记（优先从 sleep_diary 读，fallback 到 morning_record）"""
    records = []
    for i in range(n):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        diary = get_sleep_diary(user_id, date)
        if diary and diary.get("se", 0) > 0:
            records.append(diary)
        else:
            record = get_morning_record(user_id, date)
            if record and record.get("se", 0) > 0:
                records.append(record)
    return records


# ===== 提示语生成 =====

def build_restriction_tip(phase: str, avg_se: float, avg_tst: float, tib: int) -> str:
    """根据阶段生成睡眠限制提示语（CBT-I Sleep Restriction Therapy）"""
    c = _get_srt_constants()
    tib_h = round(tib / 60, 1)
    tst_h = round(avg_tst / 60, 1)
    if phase == "optimizing":
        return f"🌟 连续 7 天 SE ≥ {c['SE_OPTIMIZING']}%，本周建议卧床 {tib_h}h（实际睡眠约 {tst_h}h）。睡眠效率越高，可适度多休息。"
    elif phase == "stable":
        return f"👍 SE {avg_se}% 良好，维持 {tib_h}h 睡眠窗口。继续记录，保持规律。"
    elif phase == "restricting":
        return f"📉 SE {avg_se}% 偏低。卧床压缩至 {tib_h}h（入睡时间推迟），目标是让 SE 达到 {c['SE_STABLE']}% 以上，理想 {c['SE_OPTIMIZING']}% 。"
    else:
        return f"继续记录睡眠日记，{max(0, 7 - int(avg_se // 10))} 天后可给出精确建议。"


def get_sleep_advice(avg_se: float, avg_tst: float) -> str:
    """根据睡眠数据生成建议（avg_tst 单位：分钟）"""
    c = _get_srt_constants()
    se_opt = c["SE_OPTIMIZING"]
    se_sta = c["SE_STABLE"]
    SEVEN_HOURS = 7 * 60  # bugfix: avg_tst 单位是分钟，不是小时
    if avg_se >= se_opt and avg_tst >= SEVEN_HOURS:
        return "你的睡眠状况很好！继续保持规律的作息。"
    elif avg_se >= se_opt and avg_tst < SEVEN_HOURS:
        return "睡眠效率很高，但可以尝试稍微延长睡眠时间。"
    elif avg_se < se_sta and avg_tst >= SEVEN_HOURS:
        return "在床上的时间很长但实际睡眠效率不高，建议只在困了才上床。"
    else:
        return "睡眠效率有待提升。试试固定起床时间，建立规律的睡眠节律。"


# ===== SRT 核心计算 =====

def calculate_srt_recommendation(user_id: str) -> dict:
    """
    计算 SRT 推荐结果（纯函数，无 HTTP 依赖）
    返回包含 phase、recommended_tib、bed_time、message 等的字典
    """
    c = _get_srt_constants()
    records = get_last_n_sleep_records(user_id, n=7)
    window = get_sleep_window(user_id)
    baseline = get_sleep_baseline(user_id)

    # 计算当前 TIB
    current_tib = (window["wake_hour"] * 60 + window["wake_min"]) - (window["bed_hour"] * 60 + window["bed_min"])
    if current_tib < 0:
        current_tib += 24 * 60

    # 无记录：返回默认值
    if not records:
        return {
            "phase": "learning",
            "phase_label": "学习期",
            "has_baseline": False,
            "current_tib_minutes": current_tib,
            "current_tib_hours": round(current_tib / 60, 1),
            "planned_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "planned_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
            "recommended_tib_minutes": current_tib,
            "recommended_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "recommended_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
            "avg_se": None,
            "avg_tst_minutes": None,
            "record_count": 0,
            "message": "开始记录睡眠日记，我会为你计算最佳卧床时间",
            "days_needed": 7,
            "week_tip": "每晚睡前记录睡眠日记，7 天后我会给你个性化的睡眠窗口建议 🌙",
        }

    record_count = len(records)
    avg_se = round(sum(r["se"] for r in records) / record_count, 1)
    avg_tst = round(sum(r.get("tst_minutes", 0) for r in records) / record_count)

    # 计算预估 TIB（用于学习期）
    estimated_tib = min(max(avg_tst + c["BUFFER_MINUTES"], c["MIN_TIB_MINUTES"]), c["MAX_TIB_UPPER"])
    fixed_wake_min = window["wake_hour"] * 60 + window["wake_min"]
    suggested_bed_min = fixed_wake_min - estimated_tib
    if suggested_bed_min < 0:
        suggested_bed_min += 24 * 60
    suggested_bed_h = suggested_bed_min // 60
    suggested_bed_m = suggested_bed_min % 60

    if record_count < 7:
        pct = round(record_count / 7 * 100)
        return {
            "phase": "learning",
            "phase_label": "学习期",
            "has_baseline": False,
            "current_tib_minutes": current_tib,
            "current_tib_hours": round(current_tib / 60, 1),
            "planned_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "planned_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
            "estimated_tib_minutes": estimated_tib,
            "estimated_tib_hours": round(estimated_tib / 60, 1),
            "recommended_bed_time": f"{suggested_bed_h:02d}:{suggested_bed_m:02d}",
            "recommended_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
            "avg_se": avg_se,
            "avg_tst_minutes": avg_tst,
            "record_count": record_count,
            "message": f"已记录 {record_count}/7 天，继续记录获得准确建议",
            "days_needed": 7 - record_count,
            "week_tip": f"📊 当前平均睡眠效率 {avg_se}%，入睡时间 {avg_tst} 分钟。保持记录，{7 - record_count} 天后我会给出精确的睡眠窗口！",
        }

    # ========== 正式睡眠限制阶段（≥7 天记录）==========
    target_tib = min(max(avg_tst + c["BUFFER_MINUTES"], c["MIN_TIB_MINUTES"]), c["MAX_TIB_MINUTES"])

    # 检查是否连续 7 天都满足条件（用于扩展 TIB 的门槛）
    all_meet_threshold = len(records) >= 7 and all(r["se"] >= c["SE_OPTIMIZING"] for r in records)

    if avg_se >= c["SE_OPTIMIZING"] and all_meet_threshold:
        new_tib = min(target_tib + c["EXPANSION_MINUTES"], c["MAX_TIB_MINUTES"])
        phase = "optimizing"
        tib_adjustment = new_tib - target_tib
        suggestion = f"🌟 连续 7 天睡眠效率 {avg_se}% 优秀！本周可增加 {tib_adjustment:.0f} 分钟卧床时间"
    elif avg_se >= c["SE_STABLE"]:
        new_tib = target_tib
        phase = "stable"
        tib_adjustment = 0
        suggestion = f"👍 睡眠效率 {avg_se}% 良好，维持当前 {round(target_tib / 60, 1)} 小时睡眠窗口"
    else:
        if current_tib <= target_tib:
            new_tib = current_tib
            phase = "restricting"
            tib_adjustment = 0
            suggestion = f"💡 睡眠效率 {avg_se}% 偏低。当前卧床 {round(current_tib / 60, 1)} 小时已接近最优，继续保持"
        else:
            new_tib = target_tib
            phase = "restricting"
            tib_adjustment = current_tib - new_tib
            suggestion = f"📉 睡眠效率 {avg_se}% 偏低，建议将卧床时间调整为 {round(new_tib / 60, 1)} 小时（推迟入睡时间）"

    # 如果当前 TIB 已在建议值 ±15min 内，不需要调整
    diff = abs(current_tib - new_tib)
    if diff <= 15:
        final_tib = current_tib
        adjustment_needed = False
        suggestion = f"当前睡眠窗口已经很合适（{round(current_tib / 60, 1)} 小时），继续保持！"
    else:
        final_tib = new_tib
        adjustment_needed = True

    # 计算建议入睡时间（固定起床时间）
    recommended_bed_min = fixed_wake_min - final_tib
    if recommended_bed_min < 0:
        recommended_bed_min += 24 * 60
    rec_bed_h = recommended_bed_min // 60
    rec_bed_m = recommended_bed_min % 60

    # 获取基线 TIB（用于参考显示）
    baseline_tib = baseline.get("baseline_tib_minutes", estimated_tib) if baseline else estimated_tib

    return {
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "has_baseline": True,
        "current_tib_minutes": current_tib,
        "current_tib_hours": round(current_tib / 60, 1),
        "planned_bed_time": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
        "planned_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
        "baseline_tib_minutes": baseline_tib,
        "baseline_tib_hours": round(baseline_tib / 60, 1),
        "avg_se": avg_se,
        "avg_tst_minutes": avg_tst,
        "record_count": record_count,
        "tib_adjustment_minutes": tib_adjustment,
        "adjustment_needed": adjustment_needed,
        "recommended_tib_minutes": final_tib,
        "recommended_tib_hours": round(final_tib / 60, 1),
        "recommended_bed_time": f"{rec_bed_h:02d}:{rec_bed_m:02d}",
        "recommended_wake_time": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
        "message": suggestion,
        "week_tip": build_restriction_tip(phase, avg_se, avg_tst, final_tib),
    }


def apply_srt_restriction(user_id: str, recommended_bed_time: str = None, recommended_wake_time: str = None) -> dict:
    """
    应用 SRT 建议，更新睡眠窗口和基线（纯函数，无 HTTP 依赖）
    """
    window = get_sleep_window(user_id)

    if recommended_bed_time and recommended_wake_time:
        bh, bm = map(int, recommended_bed_time.split(":"))
        wh, wm = map(int, recommended_wake_time.split(":"))
    else:
        bh, bm = window["bed_hour"], window["bed_min"]
        wh, wm = window["wake_hour"], window["wake_min"]

    save_sleep_window(user_id, bh, bm, wh, wm)

    # 保存基线（来自本周数据）
    c = _get_srt_constants()
    records = get_last_n_sleep_records(user_id, 7)
    if records:
        avg_se = round(sum(r["se"] for r in records) / len(records), 1)
        avg_tst = round(sum(r.get("tst_minutes", 0) for r in records) / len(records))
        save_sleep_baseline(user_id, {
            "baseline_tib_minutes": min(max(avg_tst + c["BUFFER_MINUTES"], c["MIN_TIB_MINUTES"]), c["MAX_TIB_UPPER"]),
            "avg_se": avg_se,
            "avg_tst_minutes": avg_tst,
            "established_at": datetime.now().isoformat(),
            "固定起床时间": f"{wh:02d}:{wm:02d}",
        })

    return {"status": "ok", "message": f"睡眠窗口已更新：{bh:02d}:{bm:02d} - {wh:02d}:{wm:02d}"}
