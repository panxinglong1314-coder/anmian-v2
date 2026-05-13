# ==================== SRT Sleep Restriction Therapy Engine ====================
# 基于 Sleepio / AASM 2025 指南 / European Insomnia Guideline 2023
#
# 核心概念：
# - TIB (Time In Bed): 卧床时间
# - TST (Total Sleep Time): 实际睡眠时间
# - SE (Sleep Efficiency): 睡眠效率 = TST/TIB × 100%
# - SOL (Sleep Onset Latency): 入睡潜伏期
# - WASO (Wake After Sleep Onset): 夜间醒来总时长
#
# 算法设计原则：
# 1. 渐进式调整：每周评估一次，不频繁变动
# 2. 安全边界：TIB 5h ~ 8.5h（临床安全）
# 3. 多维度评估：SE + 趋势 + 疲劳度 + 连续糟糕夜
# 4. 固定起床时间：只在必要时推迟入睡时间
# 5. 可逆性：效果不好可回退

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum


class SRTPhase(Enum):
    """SRT 阶段"""
    LEARNING = "learning"       # 学习期：<7天数据
    RESTRICTING = "restricting" # 限制期：SE < 80%
    STABILIZING = "stabilizing"  # 稳定期：80% ≤ SE < 85%
    OPTIMIZING = "optimizing"    # 优化期：SE ≥ 85%
    MAINTENANCE = "maintenance"  # 维持期：连续稳定


class AdjustmentDirection(Enum):
    """调整方向"""
    EXTEND = "extend"    # 延长 TIB
    MAINTAIN = "maintain"  # 维持 TIB
    RESTRICT = "restrict"  # 缩短 TIB


@dataclass
class SleepNightRecord:
    """单夜睡眠数据"""
    date: str                    # "2024-04-08"
    bed_time: str                # "23:00"
    wake_time: str               # "07:00"
    tib_minutes: int             # 卧床时间（分钟）
    tst_minutes: int             # 实际睡眠时间
    se: float                   # 睡眠效率 (0-100)
    sol_minutes: int = 0        # 入睡潜伏期
    waso_minutes: int = 0       # 夜间醒来总时长
    wake_count: int = 0          # 夜间醒来次数
    sleep_quality: int = 3       # 主观质量 1-5
    fatigue_level: int = 3       # 白天疲劳 1-5
    nap_minutes: int = 0         # 午睡时长


@dataclass
class SRTAnalysisResult:
    """SRT 分析结果"""
    phase: SRTPhase
    current_tib_minutes: int
    current_tib_hours: float
    recommended_tib_minutes: int
    recommended_tib_hours: float
    recommended_bed_time: str    # "23:00"
    recommended_wake_time: str   # "07:00"
    adjustment_direction: AdjustmentDirection
    adjustment_minutes: int      # 调整量（分钟）
    
    # 统计分析
    avg_se: float
    avg_tst_minutes: int
    avg_sol_minutes: int
    avg_waso_minutes: int
    avg_fatigue: float
    
    # 趋势分析
    se_trend: str               # "improving", "stable", "declining"
    tst_trend: str
    poor_nights_count: int       # SE < 80% 的夜晚数
    consecutive_poor_nights: int # 连续糟糕夜晚
    
    # 周对比
    vs_last_week_se: float      # 与上周 SE 差异
    vs_last_week_tst: float     # 与上周 TST 差异
    
    # 详细信息
    record_count: int
    records: List[dict]         # 每夜详细数据（简化版）
    
    # 提示和建议
    message: str
    week_tip: str
    daily_tips: List[str]       # 每日建议


class SRTEngine:
    """睡眠限制疗法引擎"""
    
    # SRT 参数常量
    MIN_TIB_MINUTES = 5 * 60      # 270 min = 5h（临床安全下限）
    MAX_TIB_MINUTES = 8.5 * 60    # 510 min = 8.5h（优化上限）
    IDEAL_TIB_MINUTES = 7 * 60    # 420 min = 7h（理想目标）
    
    # SE 阈值
    SE_EXCELLENT = 85             # 优秀：可扩展 TIB
    SE_GOOD = 80                  # 良好：维持
    SE_POOR = 75                  # 较差：需注意
    SE_CRITICAL = 70              # 危险：需严格限制
    
    # 调整量（分钟）
    EXTEND_STEP = 30              # 延长步长
    RESTRICT_STEP = 15            # 限制步长（首次从严）
    MAINTENANCE_STEP = 0          # 维持
    
    # 连续糟糕夜阈值
    CONSECUTIVE_POOR_THRESHOLD = 3
    
    def __init__(self):
        pass
    
    def calculate_tib_from_times(self, bed_time: str, wake_time: str) -> int:
        """计算 TIB（分钟）"""
        bh, bm = map(int, bed_time.split(":"))
        wh, wm = map(int, wake_time.split(":"))
        bed_total = bh * 60 + bm
        wake_total = wh * 60 + wm
        if wake_total <= bed_total:  # 跨天
            wake_total += 24 * 60
        return wake_total - bed_total
    
    def calculate_se(self, tst_minutes: int, tib_minutes: int) -> float:
        """计算睡眠效率"""
        if tib_minutes <= 0:
            return 0.0
        return round((tst_minutes / tib_minutes) * 100, 1)
    
    def minutes_to_time_str(self, total_minutes: int) -> str:
        """分钟转换为时间字符串"""
        total_minutes = total_minutes % (24 * 60)
        hours = total_minutes // 60
        mins = total_minutes % 60
        return f"{hours:02d}:{mins:02d}"
    
    def time_str_to_minutes(self, time_str: str) -> int:
        """时间字符串转换为分钟"""
        h, m = map(int, time_str.split(":"))
        return h * 60 + m
    
    def parse_records(self, raw_records: List[dict]) -> List[SleepNightRecord]:
        """解析原始记录为 SleepNightRecord"""
        records = []
        for r in raw_records:
            bed = r.get("sleep_window_start", r.get("bed_time", "23:00"))
            wake = r.get("sleep_window_end", r.get("wake_time", "07:00"))
            tib = self.calculate_tib_from_times(bed, wake)
            tst = r.get("tst_minutes", 0)
            se = r.get("se", self.calculate_se(tst, tib) if tib > 0 else 0)
            
            records.append(SleepNightRecord(
                date=r.get("date", ""),
                bed_time=bed,
                wake_time=wake,
                tib_minutes=tib,
                tst_minutes=tst,
                se=se,
                sol_minutes=r.get("sol_minutes", r.get("sleep_latency_minutes", 0)),
                waso_minutes=r.get("waso_minutes", 0),
                wake_count=r.get("wake_count", 0),
                sleep_quality=r.get("sleep_quality", r.get("quality", 3)),
                fatigue_level=r.get("fatigue_level", 3),
                nap_minutes=r.get("nap_minutes", 0),
            ))
        return records
    
    def calculate_trend(self, values: List[float], window: int = 3) -> str:
        """计算趋势：improving / stable / declining"""
        if len(values) < 2:
            return "stable"
        
        # 比较最近 window 天与之前 window 天
        recent = values[:window] if len(values) >= window else values
        older = values[window:2*window] if len(values) >= 2*window else values[window:]
        
        if not older:
            return "stable"
        
        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)
        
        diff = avg_recent - avg_older
        if diff > 3:  # 上升超过3%
            return "improving"
        elif diff < -3:
            return "declining"
        return "stable"
    
    def count_poor_nights(self, records: List[SleepNightRecord], threshold: float = 80) -> Tuple[int, int]:
        """统计糟糕夜晚数和连续糟糕夜晚数"""
        poor_count = 0
        consecutive = 0
        max_consecutive = 0
        
        for r in records:
            if r.se < threshold:
                poor_count += 1
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0
        
        return poor_count, max_consecutive
    
    def calculate_fatigue_score(self, records: List[SleepNightRecord]) -> float:
        """计算综合疲劳指数（考虑夜间睡眠质量和白天疲劳）"""
        if not records:
            return 3.0
        
        # 夜间恢复因子：SE 越高，恢复越好
        avg_se = sum(r.se for r in records) / len(records)
        recovery = avg_se / 100  # 0-1
        
        # 白天疲劳因子：疲劳度越高，疲劳指数越高
        avg_fatigue = sum(r.fatigue_level for r in records) / len(records)
        
        # 午睡补偿：适量午睡可以减轻疲劳（但不能太多）
        avg_nap = sum(r.nap_minutes for r in records) / len(records)
        nap_factor = 1.0
        if avg_nap > 30:
            nap_factor = 0.8  # 午睡过长反而不好
        elif 15 <= avg_nap <= 30:
            nap_factor = 1.1  # 适量午睡有益
        
        # 综合疲劳指数：越高越疲劳
        fatigue_score = (avg_fatigue * (2 - recovery)) * nap_factor
        return round(min(max(fatigue_score, 1), 5), 1)
    
    def calculate_recommended_tib(self, records: List[SleepNightRecord], current_tib: int) -> Tuple[int, AdjustmentDirection, int]:
        """
        计算推荐 TIB 及调整方向
        Returns: (recommended_tib_minutes, adjustment_direction, adjustment_minutes)
        """
        if not records:
            return current_tib, AdjustmentDirection.MAINTAIN, 0
        
        avg_se = sum(r.se for r in records) / len(records)
        avg_tst = sum(r.tst_minutes for r in records) / len(records)
        avg_fatigue = sum(r.fatigue_level for r in records) / len(records)
        poor_nights, consecutive_poor = self.count_poor_nights(records)
        
        # 基础目标 TIB = avg(TST) + 30 分钟缓冲
        target_tib = int(avg_tst + 30)
        target_tib = max(target_tib, self.MIN_TIB_MINUTES)
        target_tib = min(target_tib, self.MAX_TIB_MINUTES)
        
        # 如果当前 TIB 已经接近目标，不需要调整
        if abs(current_tib - target_tib) <= 15:
            return current_tib, AdjustmentDirection.MAINTAIN, 0
        
        # 根据 SE 和趋势决定调整方向
        se_trend = self.calculate_trend([r.se for r in records])
        
        # 特殊情况处理
        if consecutive_poor >= self.CONSECUTIVE_POOR_THRESHOLD:
            # 连续糟糕夜 ≥ 3 天：严格执行限制
            # 目标 TIB = avg(TST)，不额外加缓冲
            target_tib = int(avg_tst)
            target_tib = max(target_tib, self.MIN_TIB_MINUTES)
            adjustment = current_tib - target_tib
            if adjustment > 0:
                return target_tib, AdjustmentDirection.RESTRICT, adjustment
            return current_tib, AdjustmentDirection.MAINTAIN, 0
        
        # 正常调整逻辑
        if avg_se >= self.SE_EXCELLENT:
            # SE ≥ 85%：可以扩展 TIB
            if se_trend == "improving" and avg_fatigue <= 2.5:
                # 趋势向好 + 疲劳度低：扩展 +30min
                new_tib = min(target_tib + self.EXTEND_STEP, self.MAX_TIB_MINUTES)
                adjustment = new_tib - current_tib
                if adjustment > 0:
                    return new_tib, AdjustmentDirection.EXTEND, adjustment
            # 趋势稳定或下降：维持
            return current_tib, AdjustmentDirection.MAINTAIN, 0
        
        elif self.SE_GOOD <= avg_se < self.SE_EXCELLENT:
            # SE 80-85%：稳定维持
            # 如果 TIB 偏离目标过大，微调
            diff = abs(current_tib - target_tib)
            if diff > 30:
                adjustment = target_tib - current_tib
                direction = AdjustmentDirection.EXTEND if adjustment > 0 else AdjustmentDirection.RESTRICT
                return target_tib, direction, abs(adjustment)
            return current_tib, AdjustmentDirection.MAINTAIN, 0
        
        elif self.SE_POOR <= avg_se < self.SE_GOOD:
            # SE 75-80%：需要关注，可能需要轻微限制
            if se_trend == "declining":
                # 趋势下降：轻微限制
                new_tib = max(target_tib - self.RESTRICT_STEP, self.MIN_TIB_MINUTES)
                adjustment = current_tib - new_tib
                if adjustment > 0:
                    return new_tib, AdjustmentDirection.RESTRICT, adjustment
            return current_tib, AdjustmentDirection.MAINTAIN, 0
        
        else:
            # SE < 75%：严格限制
            new_tib = max(target_tib - self.RESTRICT_STEP, self.MIN_TIB_MINUTES)
            adjustment = current_tib - new_tib
            if adjustment > 0:
                return new_tib, AdjustmentDirection.RESTRICT, adjustment
            return current_tib, AdjustmentDirection.MAINTAIN, 0
    
    def determine_phase(self, records: List[SleepNightRecord], adjustment: AdjustmentDirection) -> SRTPhase:
        """根据数据和调整方向确定当前阶段"""
        if len(records) < 7:
            return SRTPhase.LEARNING
        
        avg_se = sum(r.se for r in records) / len(records)
        
        if adjustment == AdjustmentDirection.EXTEND:
            return SRTPhase.OPTIMIZING
        elif adjustment == AdjustmentDirection.RESTRICT:
            return SRTPhase.RESTRICTING
        elif avg_se >= self.SE_EXCELLENT:
            return SRTPhase.MAINTENANCE
        else:
            return SRTPhase.STABILIZING
    
    def generate_weekly_tips(self, records: List[SleepNightRecord], phase: SRTPhase) -> List[str]:
        """生成每日建议（针对本周问题）"""
        tips = []
        
        # 基于 SOL 分析
        avg_sol = sum(r.sol_minutes for r in records) / len(records) if records else 0
        if avg_sol > 30:
            tips.append("💡 入睡困难（>30分钟）？尝试：睡前 1 小时不看手机、卧室保持凉爽、起床时间固定")
        
        # 基于 WASO 分析
        avg_waso = sum(r.waso_minutes for r in records) / len(records) if records else 0
        if avg_waso > 60:
            tips.append("🌙 夜间易醒？避免睡前喝水、下午不喝咖啡、尝试 PMR 放松")
        
        # 基于 wake_count
        avg_wakes = sum(r.wake_count for r in records) / len(records) if records else 0
        if avg_wakes >= 3:
            tips.append("⚠️ 每晚醒来 3+ 次？可能是睡眠呼吸问题，建议咨询医生")
        
        # 基于质量评分
        avg_quality = sum(r.sleep_quality for r in records) / len(records) if records else 3
        if avg_quality < 3:
            tips.append("📊 主观睡眠质量偏低：尝试睡前仪式（洗澡、拉伸、阅读）")
        
        # 基于疲劳度
        avg_fatigue = sum(r.fatigue_level for r in records) / len(records) if records else 3
        if avg_fatigue >= 4:
            tips.append("😴 白天疲劳感强：确保早起接受光照、适量运动、避免长时间午睡")
        
        # 阶段特定建议
        if phase == SRTPhase.LEARNING:
            tips.append("📝 本周继续记录睡眠日记，了解自己的睡眠模式")
        elif phase == SRTPhase.RESTRICTING:
            tips.append("⏰ 睡眠窗口调整期间，可能会感觉疲劳，这是正常的适应过程")
        elif phase == SRTPhase.OPTIMIZING:
            tips.append("🌟 睡眠效率提升！可以适当延长卧床时间，但仍要保持规律")
        
        return tips[:3]  # 最多3条建议
    
    def analyze(self, records: List[dict], current_window: dict) -> SRTAnalysisResult:
        """
        完整分析睡眠数据，返回 SRTAnalysisResult
        """
        # 解析记录
        night_records = self.parse_records(records)
        night_records.sort(key=lambda x: x.date, reverse=True)  # 最新在前
        
        # 计算当前 TIB
        current_tib = self.calculate_tib_from_times(
            current_window.get("bed", "23:00"),
            current_window.get("wake", "07:00")
        )
        
        # 如果没有足够数据，返回默认值
        if not night_records:
            return SRTAnalysisResult(
                phase=SRTPhase.LEARNING,
                current_tib_minutes=current_tib,
                current_tib_hours=round(current_tib / 60, 1),
                recommended_tib_minutes=current_tib,
                recommended_tib_hours=round(current_tib / 60, 1),
                recommended_bed_time=current_window.get("bed", "23:00"),
                recommended_wake_time=current_window.get("wake", "07:00"),
                adjustment_direction=AdjustmentDirection.MAINTAIN,
                adjustment_minutes=0,
                avg_se=0, avg_tst_minutes=0, avg_sol_minutes=0, avg_waso_minutes=0, avg_fatigue=0,
                se_trend="stable", tst_trend="stable",
                poor_nights_count=0, consecutive_poor_nights=0,
                vs_last_week_se=0, vs_last_week_tst=0,
                record_count=0, records=[],
                message="开始记录睡眠日记，我会为你计算最佳卧床时间",
                week_tip="每晚睡前记录睡眠日记，7 天后我会给你个性化的睡眠窗口建议 🌙",
                daily_tips=["📝 开始记录睡眠日记"]
            )
        
        # 计算统计数据
        avg_se = round(sum(r.se for r in night_records) / len(night_records), 1)
        avg_tst = int(sum(r.tst_minutes for r in night_records) / len(night_records))
        avg_sol = int(sum(r.sol_minutes for r in night_records) / len(night_records))
        avg_waso = int(sum(r.waso_minutes for r in night_records) / len(night_records))
        avg_fatigue = round(sum(r.fatigue_level for r in night_records) / len(night_records), 1)
        
        # 趋势分析
        se_trend = self.calculate_trend([r.se for r in night_records])
        tst_trend = self.calculate_trend([float(r.tst_minutes) for r in night_records])
        
        # 糟糕夜晚统计
        poor_nights, consecutive_poor = self.count_poor_nights(night_records)
        
        # 周对比（如果有 14 天数据）
        vs_last_week_se = 0
        vs_last_week_tst = 0
        if len(night_records) >= 14:
            this_week = night_records[:7]
            last_week = night_records[7:14]
            vs_last_week_se = round(
                (sum(r.se for r in this_week) / len(this_week)) - 
                (sum(r.se for r in last_week) / len(last_week)), 1
            )
            vs_last_week_tst = round(
                (sum(r.tst_minutes for r in this_week) / len(this_week)) - 
                (sum(r.tst_minutes for r in last_week) / len(last_week)), 1
            )
        
        # 计算推荐 TIB
        recommended_tib, adjustment_dir, adjustment_minutes = self.calculate_recommended_tib(
            night_records, current_tib
        )
        
        # 确定阶段
        phase = self.determine_phase(night_records, adjustment_dir)
        
        # 计算推荐时间（固定起床时间，只调入睡）
        recommended_bed = self.minutes_to_time_str(
            self.time_str_to_minutes(current_window.get("wake", "07:00")) - recommended_tib
        )
        recommended_wake = current_window.get("wake", "07:00")
        
        # 生成消息
        message = self._build_message(phase, avg_se, recommended_tib, current_tib, adjustment_minutes, poor_nights, len(night_records))
        week_tip = self._build_week_tip(phase, avg_se, avg_fatigue, recommended_tib, poor_nights)
        daily_tips = self.generate_weekly_tips(night_records, phase)
        
        # 简化记录（用于返回）
        simple_records = [
            {
                "date": r.date,
                "tib_hours": round(r.tib_minutes / 60, 1),
                "tst_hours": round(r.tst_minutes / 60, 1),
                "se": r.se,
                "quality": r.sleep_quality,
                "fatigue": r.fatigue_level,
            }
            for r in night_records
        ]
        
        return SRTAnalysisResult(
            phase=phase,
            current_tib_minutes=current_tib,
            current_tib_hours=round(current_tib / 60, 1),
            recommended_tib_minutes=recommended_tib,
            recommended_tib_hours=round(recommended_tib / 60, 1),
            recommended_bed_time=recommended_bed,
            recommended_wake_time=recommended_wake,
            adjustment_direction=adjustment_dir,
            adjustment_minutes=adjustment_minutes,
            avg_se=avg_se,
            avg_tst_minutes=avg_tst,
            avg_sol_minutes=avg_sol,
            avg_waso_minutes=avg_waso,
            avg_fatigue=avg_fatigue,
            se_trend=se_trend,
            tst_trend=tst_trend,
            poor_nights_count=poor_nights,
            consecutive_poor_nights=consecutive_poor,
            vs_last_week_se=vs_last_week_se,
            vs_last_week_tst=vs_last_week_tst,
            record_count=len(night_records),
            records=simple_records,
            message=message,
            week_tip=week_tip,
            daily_tips=daily_tips,
        )
    
    def _build_message(self, phase: SRTPhase, avg_se: float, recommended_tib: int, 
                       current_tib: int, adjustment: int, poor_nights: int, record_count: int) -> str:
        """构建主消息"""
        tib_h = round(recommended_tib / 60, 1)
        current_h = round(current_tib / 60, 1)
        
        if phase == SRTPhase.LEARNING:
            return f"已记录 {record_count} 天，继续记录获得准确建议"
        elif phase == SRTPhase.RESTRICTING:
            if adjustment > 0:
                return f"📉 SE {avg_se}% 偏低，建议将卧床调整为 {tib_h}h（推迟入睡）"
            return f"💡 SE {avg_se}% 偏低，当前 {current_h}h 已接近最优"
        elif phase == SRTPhase.STABILIZING:
            return f"👍 SE {avg_se}% 良好，维持 {tib_h}h 睡眠窗口"
        elif phase == SRTPhase.OPTIMIZING:
            if adjustment > 0:
                return f"🌟 SE {avg_se}% 优秀！可增加 {adjustment} 分钟卧床时间"
            return f"🌟 SE {avg_se}% 优秀，继续保持！"
        else:
            return f"当前睡眠窗口 {current_h}h，适合你"
    
    def _build_week_tip(self, phase: SRTPhase, avg_se: float, avg_fatigue: float,
                        recommended_tib: int, poor_nights: int) -> str:
        """构建周提示"""
        tib_h = round(recommended_tib / 60, 1)
        
        if phase == SRTPhase.LEARNING:
            return f"继续记录睡眠日记，7 天后给出精确建议。当前 SE {avg_se}%，目标 85%+"
        elif phase == SRTPhase.RESTRICTING:
            tip = f"SE {avg_se}% 偏低。卧床压缩至 {tib_h}h，目标提高 SE 至 85%+"
            if avg_fatigue >= 4:
                tip += "。适应期疲劳感是正常的，2-3 天后会好转"
            if poor_nights >= 3:
                tip += f"。本周 {poor_nights} 晚效率偏低，坚持记录观察趋势"
            return tip
        elif phase == SRTPhase.STABILIZING:
            return f"SE {avg_se}% 良好！维持 {tib_h}h 睡眠窗口，记录观察 SE 能否突破 85%"
        elif phase == SRTPhase.OPTIMIZING:
            return f"🌟 SE {avg_se}% 优秀！可尝试扩展至 {tib_h}h，但仍要保持固定起床时间"
        else:
            return f"维持 {tib_h}h 睡眠窗口，保持规律是最好的助眠"


# 全局 SRT 引擎实例
srt_engine = SRTEngine()
