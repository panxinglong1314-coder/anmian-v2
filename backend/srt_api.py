# ==================== SRT Sleep Restriction Therapy API (Enhanced) ====================
#
# 增强功能：
# 1. SRTEngine 多维度分析（SE + 趋势 + 疲劳 + 连续糟糕夜）
# 2. Per-night 详细数据展示
# 3. 周对比分析
# 4. 渐进式调整算法
# 5. 每日个性化建议

from srt_engine import (
    srt_engine, SRTPhase, AdjustmentDirection,
    SleepNightRecord, SRTAnalysisResult
)


@app.get("/api/v1/srt/analyze")
async def srt_analyze(
    days: int = Query(14, ge=7, le=30, description="分析天数，默认14天"),
    user: AuthUser = Depends(get_current_user)
):
    """
    SRT 完整分析
    - 多维度评估：SE、趋势、疲劳、连续糟糕夜
    - 生成个性化睡眠窗口建议
    - 每日改善建议
    """
    user_id = user.user_id
    
    try:
        # 获取睡眠记录
        records = get_last_n_sleep_records(user_id, n=days)
        window = get_sleep_window(user_id)
        
        # 转换为引擎需要的格式
        window_dict = {
            "bed": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "wake": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
        }
        
        # 执行分析
        result = srt_engine.analyze(records, window_dict)
        
        return {
            # 阶段和推荐
            "phase": result.phase.value,
            "phase_label": {
                "learning": "📝 学习期",
                "restricting": "📉 限制期",
                "stabilizing": "👍 稳定期",
                "optimizing": "🌟 优化期",
                "maintenance": "✨ 维持期",
            }.get(result.phase.value, "未知"),
            
            # 当前窗口
            "current_tib_minutes": result.current_tib_minutes,
            "current_tib_hours": result.current_tib_hours,
            "current_bed_time": window_dict["bed"],
            "current_wake_time": window_dict["wake"],
            
            # 推荐窗口
            "recommended_tib_minutes": result.recommended_tib_minutes,
            "recommended_tib_hours": result.recommended_tib_hours,
            "recommended_bed_time": result.recommended_bed_time,
            "recommended_wake_time": result.recommended_wake_time,
            
            # 调整信息
            "adjustment_direction": result.adjustment_direction.value,
            "adjustment_minutes": result.adjustment_minutes,
            "adjustment_needed": result.adjustment_minutes > 0,
            
            # 统计分析
            "avg_se": result.avg_se,
            "avg_tst_minutes": result.avg_tst_minutes,
            "avg_tst_hours": round(result.avg_tst_minutes / 60, 1),
            "avg_sol_minutes": result.avg_sol_minutes,
            "avg_waso_minutes": result.avg_waso_minutes,
            "avg_fatigue": result.avg_fatigue,
            
            # 趋势分析
            "se_trend": result.se_trend,
            "tst_trend": result.tst_trend,
            "se_trend_arrow": {"improving": "↗", "stable": "→", "declining": "↘"}.get(result.se_trend, ""),
            "tst_trend_arrow": {"improving": "↗", "stable": "→", "declining": "↘"}.get(result.tst_trend, ""),
            
            # 糟糕夜晚统计
            "poor_nights_count": result.poor_nights_count,
            "consecutive_poor_nights": result.consecutive_poor_nights,
            
            # 周对比
            "vs_last_week_se": result.vs_last_week_se,
            "vs_last_week_tst": result.vs_last_week_tst,
            
            # 记录统计
            "record_count": result.record_count,
            "analysis_days": days,
            
            # 每夜详细（用于图表）
            "records": result.records,
            
            # 消息和建议
            "message": result.message,
            "week_tip": result.week_tip,
            "daily_tips": result.daily_tips,
            
            # SRT 参数
            "srt_params": {
                "min_tib_hours": 5.0,
                "max_tib_hours": 8.5,
                "ideal_tib_hours": 7.0,
                "se_excellent": 85,
                "se_good": 80,
                "se_poor": 75,
                "extend_step_minutes": 30,
                "restrict_step_minutes": 15,
            }
        }
        
    except Exception as e:
        print(f"[srt_analyze error] {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/srt/weekly")
async def srt_weekly_report(
    user: AuthUser = Depends(get_current_user)
):
    """
    SRT 周报：本周 vs 上周对比
    """
    user_id = user.user_id
    
    try:
        # 获取本周和上周数据
        this_week_records = get_last_n_sleep_records(user_id, n=7)
        last_week_records = []
        for i in range(7, 14):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            record = get_morning_record(user_id, date)
            if record and record.get("se", 0) > 0:
                last_week_records.append(record)
        
        if len(this_week_records) < 3:
            return {
                "status": "insufficient_data",
                "message": "本周数据不足，需至少 3 天记录",
                "this_week_count": len(this_week_records),
            }
        
        # 计算本周统计
        this_avg_se = sum(r["se"] for r in this_week_records) / len(this_week_records)
        this_avg_tst = sum(r.get("tst_minutes", 0) for r in this_week_records) / len(this_week_records)
        this_avg_tib = sum(r.get("tib_minutes", 0) for r in this_week_records) / len(this_week_records)
        
        # 计算上周统计
        last_avg_se = sum(r["se"] for r in last_week_records) / len(last_week_records) if last_week_records else 0
        last_avg_tst = sum(r.get("tst_minutes", 0) for r in last_week_records) / len(last_week_records) if last_week_records else 0
        last_avg_tib = sum(r.get("tib_minutes", 0) for r in last_week_records) / len(last_week_records) if last_week_records else 0
        
        # 对比
        se_change = this_avg_se - last_avg_se
        tst_change = this_avg_tst - last_avg_tst
        tib_change = this_avg_tib - last_avg_tib
        
        # 生成周报
        if se_change > 3:
            se_emoji = "🌟"
            se_comment = "显著改善"
        elif se_change > 0:
            se_emoji = "👍"
            se_comment = "小幅提升"
        elif se_change > -3:
            se_emoji = "➡️"
            se_comment = "基本持平"
        else:
            se_emoji = "📉"
            se_comment = "有所下降"
        
        return {
            "status": "ok",
            "week_summary": {
                "this_week": {
                    "days_recorded": len(this_week_records),
                    "avg_se": round(this_avg_se, 1),
                    "avg_tst_hours": round(this_avg_tst / 60, 1),
                    "avg_tib_hours": round(this_avg_tib / 60, 1),
                },
                "last_week": {
                    "days_recorded": len(last_week_records),
                    "avg_se": round(last_avg_se, 1),
                    "avg_tst_hours": round(last_avg_tst / 60, 1),
                    "avg_tib_hours": round(last_avg_tib / 60, 1),
                } if last_week_records else None,
                "changes": {
                    "se_change": round(se_change, 1),
                    "tst_change_minutes": round(tst_change, 0),
                    "tib_change_minutes": round(tib_change, 0),
                },
                "assessment": f"{se_emoji} SE {se_comment}（{'+' if se_change > 0 else ''}{round(se_change, 1)}%）",
            },
            "message": self._generate_weekly_message(se_change, tst_change, len(this_week_records)),
        }
        
    except Exception as e:
        print(f"[srt_weekly error] {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _generate_weekly_message(self, se_change: float, tst_change: float, days_recorded: int) -> str:
    """生成周报消息"""
    if days_recorded < 5:
        return f"本周记录 {days_recorded} 天，继续保持，目标是记录 7 天"
    
    if se_change > 5:
        return "🎉 本周睡眠效率大幅提升！继续保持当前的睡眠习惯"
    elif se_change > 2:
        return "👍 本周睡眠效率稳步提升，继续保持"
    elif se_change > -2:
        return "➡️ 本周睡眠效率基本稳定，继续保持规律"
    else:
        return "💡 本周睡眠效率有所下降，建议检查睡眠卫生习惯"


@app.post("/api/v1/srt/apply")
async def srt_apply_recommendation(
    user: AuthUser = Depends(get_current_user)
):
    """
    应用 SRT 推荐睡眠窗口
    - 更新 sleep_window
    - 保存 SRT 基线
    """
    user_id = user.user_id
    
    try:
        # 获取当前推荐
        records = get_last_n_sleep_records(user_id, n=14)
        window = get_sleep_window(user_id)
        
        window_dict = {
            "bed": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "wake": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
        }
        
        result = srt_engine.analyze(records, window_dict)
        
        # 应用推荐
        bh, bm = map(int, result.recommended_bed_time.split(":"))
        wh, wm = map(int, result.recommended_wake_time.split(":"))
        
        save_sleep_window(user_id, bh, bm, wh, wm)
        
        # 保存基线
        if len(records) >= 7:
            save_sleep_baseline(user_id, {
                "srt_phase": result.phase.value,
                "baseline_tib_minutes": result.recommended_tib_minutes,
                "avg_se": result.avg_se,
                "avg_tst_minutes": result.avg_tst_minutes,
                "established_at": datetime.now().isoformat(),
                "fixed_wake_time": result.recommended_wake_time,
            })
        
        return {
            "status": "ok",
            "message": f"睡眠窗口已更新：{result.recommended_bed_time} - {result.recommended_wake_time}",
            "new_tib_hours": result.recommended_tib_hours,
            "phase": result.phase.value,
        }
        
    except Exception as e:
        print(f"[srt_apply error] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/srt/tips")
async def srt_daily_tips(
    user: AuthUser = Depends(get_current_user)
):
    """
    获取今日 SRT 小贴士（基于最新数据）
    """
    user_id = user.user_id
    
    try:
        records = get_last_n_sleep_records(user_id, n=7)
        window = get_sleep_window(user_id)
        
        if len(records) < 3:
            return {
                "tips": [
                    "📝 记录睡眠日记是改善睡眠的第一步",
                    "💡 建议每晚同一时间睡觉、同一时间起床",
                    "🌙 睡前 1 小时避免使用手机等电子设备",
                ],
                "based_on_records": len(records),
            }
        
        window_dict = {
            "bed": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "wake": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
        }
        
        result = srt_engine.analyze(records, window_dict)
        
        return {
            "tips": result.daily_tips,
            "phase": result.phase.value,
            "avg_se": result.avg_se,
            "avg_fatigue": result.avg_fatigue,
            "based_on_records": len(records),
        }
        
    except Exception as e:
        print(f"[srt_tips error] {e}")
        return {"tips": ["记录睡眠日记，了解自己的睡眠模式"], "error": str(e)}


# ==================== 保留旧的兼容接口 ====================

@app.get("/api/v1/sleep/restriction")
async def get_sleep_restriction_compat(user: AuthUser = Depends(get_current_user)):
    """
    兼容旧接口，返回简化版 SRT 数据
    """
    user_id = user.user_id
    
    try:
        records = get_last_n_sleep_records(user_id, n=7)
        window = get_sleep_window(user_id)
        
        window_dict = {
            "bed": f"{window['bed_hour']:02d}:{window['bed_min']:02d}",
            "wake": f"{window['wake_hour']:02d}:{window['wake_min']:02d}",
        }
        
        result = srt_engine.analyze(records, window_dict)
        
        return {
            "phase": result.phase.value,
            "has_baseline": len(records) >= 7,
            "current_tib_minutes": result.current_tib_minutes,
            "current_tib_hours": result.current_tib_hours,
            "planned_bed_time": window_dict["bed"],
            "planned_wake_time": window_dict["wake"],
            "avg_se": result.avg_se,
            "avg_tst_minutes": result.avg_tst_minutes,
            "record_count": result.record_count,
            "tib_adjustment_minutes": result.adjustment_minutes,
            "adjustment_needed": result.adjustment_minutes > 0,
            "recommended_tib_minutes": result.recommended_tib_minutes,
            "recommended_tib_hours": result.recommended_tib_hours,
            "recommended_bed_time": result.recommended_bed_time,
            "recommended_wake_time": result.recommended_wake_time,
            "message": result.message,
            "week_tip": result.week_tip,
        }
        
    except Exception as e:
        print(f"[sleep_restriction compat error] {e}")
        return {"status": "error", "message": str(e)}
