"""
会话日志记录器
知眠 L2: 记录有效对话 → 用于 L3 Fine-tuning 数据积累
"""

import json
import time
import uuid
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import redis
import os
from dialogue_evaluator import dialogue_evaluator
from alert_manager import send_alert, send_daily_report

# ============ 配置 ============

LOG_DIR = Path(__file__).parent.parent / "conversation_logs"
LOG_DIR.mkdir(exist_ok=True)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
REDIS_DB = 1  # 分离主会话和日志用的DB

_log_redis = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
    password=REDIS_PASSWORD, decode_responses=True
)

# ============ 数据模型 ============

@dataclass
class ConversationTurn:
    role: str          # "user" | "assistant"
    content: str
    timestamp: str
    technique_used: Optional[str] = None  # CBT技术名称
    anxiety_level: Optional[int] = None    # 当时检测的焦虑等级


@dataclass
class SessionLog:
    session_id: str
    user_id: str
    start_time: str
    end_time: Optional[str]
    turns: List[ConversationTurn]
    scenario_id: Optional[str] = None      # 匹配的担忧场景
    insomnia_subtype: Optional[str] = None # 失眠亚型
    initial_anxiety: Optional[int] = None  # 入会话焦虑等级
    final_anxiety: Optional[int] = None    # 出会话焦虑等级（如果有）
    outcome: Optional[str] = None          # "completed_closure" | "dropped" | "sleep_reported"
    sleep_quality: Optional[int] = None   # 晨间打分的睡眠质量 1-5
    rating: Optional[int] = None           # 用户满意度 1-5
    notes: Optional[str] = None
    stage: Optional[str] = None      # intake / skill_building / cognitive_restructuring / relapse_prevention

    def to_dict(self) -> dict:
        d = asdict(self)
        d["turns"] = [asdict(t) for t in self.turns]
        return d


# ============ 会话日志管理器 ============

class SessionLogger:
    """会话日志：内存缓冲 + Redis持久化 + 文件备份"""

    def __init__(self):
        self._current_session: Optional[SessionLog] = None
        self._buffer: List[Dict] = []
        self._buffer_size = 10  # 攒10条再写

    # ---------- 会话生命周期 ----------

    def start_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        insomnia_subtype: Optional[str] = None,
        stage: Optional[str] = None
    ) -> str:
        """开始一个新会话"""
        if self._current_session:
            # 防止漏存：自动结束上一个
            self.end_session(outcome="interrupted")

        session_id = session_id or f"sess_{int(time.time())}"
        self._current_session = SessionLog(
            session_id=session_id,
            user_id=user_id,
            start_time=datetime.now().isoformat(),
            end_time=None,
            turns=[],
            insomnia_subtype=insomnia_subtype,
            initial_anxiety=None,
            final_anxiety=None,
            outcome=None,
            stage=stage,
        )
        return session_id

    def add_turn(
        self,
        role: str,
        content: str,
        technique_used: Optional[str] = None,
        anxiety_level: Optional[int] = None,
        scenario_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """记录一轮对话（无当前会话时自动创建）"""
        if not self._current_session and user_id and session_id:
            self.start_session(user_id=user_id, session_id=session_id)
        if not self._current_session:
            return
        # 如果 session_id 变化，结束旧的并创建新的
        if session_id and self._current_session.session_id != session_id:
            self.end_session(outcome="interrupted")
            self.start_session(user_id=user_id or self._current_session.user_id, session_id=session_id)

        turn = ConversationTurn(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            technique_used=technique_used,
            anxiety_level=anxiety_level,
        )
        self._current_session.turns.append(turn)

        # 如果是第一轮，设置初始焦虑等级
        if len(self._current_session.turns) == 1 and anxiety_level:
            self._current_session.initial_anxiety = anxiety_level

        # 记录场景路由
        if scenario_id:
            self._current_session.scenario_id = scenario_id

    def update_anxiety(self, level: int):
        """更新当前焦虑等级"""
        if self._current_session and self._current_session.turns:
            self._current_session.turns[-1].anxiety_level = level
            self._current_session.final_anxiety = level

    def update_rating(self, session_id: str, rating: int, notes: Optional[str] = None) -> bool:
        """会话结束后补录用户评分（用于延迟收集方案）"""
        # 如果当前会话匹配，直接更新并保存
        if self._current_session and self._current_session.session_id == session_id:
            self._current_session.rating = rating
            if notes:
                self._current_session.notes = notes
            self._save_log(self._current_session.to_dict())
            return True

        # 否则从文件读取并更新
        log_file = LOG_DIR / f"sess_{session_id}.json"
        if not log_file.exists():
            return False
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                log = json.load(f)
            log['rating'] = rating
            if notes:
                log['notes'] = notes
            # 重新计算 effect_score
            old_effect = log.get('effect_score', 5.0)
            log['effect_score'] = self._recompute_effect_score_from_log(log)
            log.setdefault('effect_breakdown', {})['rating_score'] = rating / 5.0
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
            # 更新 Redis
            key = f"session_log:{log['user_id']}:{session_id}"
            try:
                _log_redis.setex(key, 90 * 86400, json.dumps(log, ensure_ascii=False))
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[SessionLogger] update_rating error: {e}")
            return False

    def _recompute_effect_score_from_log(self, log: dict) -> float:
        s = log
        score = 5.0
        if s.get('outcome') in ('completed_closure', 'sleep_reported'):
            score += 2.0
        if s.get('sleep_quality', 0) >= 4:
            score += 1.0
        if s.get('rating'):
            score += (s['rating'] - 3) * 0.5
        init_anx = s.get('initial_anxiety', 5)
        final_anx = s.get('final_anxiety', 5)
        score += max(0, init_anx - final_anx) * 0.3
        techniques = set(t.get('technique_used') for t in s.get('turns', []) if t.get('technique_used'))
        if techniques:
            score += 0.5
        return round(min(10.0, max(0.0, score)), 2)

    def end_session(
        self,
        outcome: str = "completed",
        sleep_quality: Optional[int] = None,
        rating: Optional[int] = None,
        notes: Optional[str] = None
    ):
        """结束会话"""
        if not self._current_session:
            return

        self._current_session.end_time = datetime.now().isoformat()
        self._current_session.outcome = outcome
        if sleep_quality:
            self._current_session.sleep_quality = sleep_quality
        if rating:
            self._current_session.rating = rating
        if notes:
            self._current_session.notes = notes

        # 计算效果分数（用于L3训练排序）
        effect_score = self._compute_effect_score()

        # 运行对话质量评估
        eval_result = dialogue_evaluator.evaluate_session(self._current_session.to_dict())
        quality_eval = dialogue_evaluator.to_dict(eval_result)

        log_entry = {
            **self._current_session.to_dict(),
            "effect_score": effect_score,
            "effect_breakdown": {
                "outcome_score": 1.0 if outcome in ("completed_closure", "sleep_reported") else 0.0,
                "rating_score": (rating or 3) / 5.0,
                "anxiety_reduction": max(0, (int(self._current_session.initial_anxiety or 5)) - (int(self._current_session.final_anxiety or 5))) / 10.0,
            },
            "quality_evaluation": quality_eval,
        }

        self._save_log(log_entry)

        # 触发告警（不合格/需改进）
        try:
            report = quality_eval.get("report", {})
            if report:
                send_alert(report, self._current_session.to_dict())
        except Exception as e:
            print(f"[SessionLogger] 告警发送失败: {e}")

        self._current_session = None

    # ---------- 效果评分（用于L3训练数据筛选）----------

    def _compute_effect_score(self) -> float:
        """计算会话效果分数 0-10"""
        if not self._current_session:
            return 0.0
        s = self._current_session

        # 基础分
        score = 5.0

        # 完成关闭仪式
        if s.outcome in ("completed_closure", "sleep_reported"):
            score += 2.0

        # 睡眠质量加分
        if s.sleep_quality and s.sleep_quality >= 4:
            score += 1.0

        # 用户评分
        if s.rating:
            score += (s.rating - 3) * 0.5

        # 焦虑下降
        if s.initial_anxiety and s.final_anxiety:
            reduction = s.initial_anxiety - s.final_anxiety
            score += reduction * 0.3

        # 有CBT技术使用记录
        techniques_used = set(t.technique_used for t in s.turns if t.technique_used)
        if techniques_used:
            score += 0.5

        return round(min(10.0, max(0.0, score)), 2)

    # ---------- 存储 ----------

    def _save_log(self, log_entry: dict):
        """保存到Redis + 文件"""
        key = f"session_log:{log_entry['user_id']}:{log_entry['session_id']}"
        try:
            _log_redis.setex(key, 90 * 86400, json.dumps(log_entry, ensure_ascii=False))
        except Exception as e:
            print(f"[SessionLogger] Redis save error: {e}")

        # 同时写文件（备份）
        log_file = LOG_DIR / f"sess_{log_entry['session_id']}.json"
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_entry, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[SessionLogger] File write error: {e}")

        # 追加到日索引
        index_file = LOG_DIR / "daily_index.json"
        daily_key = date.today().isoformat()
        try:
            if index_file.exists():
                with open(index_file, "r", encoding="utf-8") as f:
                    index = json.load(f)
            else:
                index = {}
            index.setdefault(daily_key, []).append(log_entry["session_id"])
            with open(index_file, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False)
        except Exception as e:
            print(f"[SessionLogger] Index write error: {e}")

    # ---------- 查询（用于L3数据准备）----------

    def get_high_quality_sessions(self, min_score: float = 7.0, limit: int = 100) -> List[dict]:
        """获取高质量对话（用于L3 Fine-tuning）"""
        logs = []
        index_file = LOG_DIR / "daily_index.json"
        if not index_file.exists():
            return logs

        with open(index_file, "r", encoding="utf-8") as f:
            index = json.load(f)

        # 只查最近30天
        cutoff = (datetime.now().timestamp() - 30 * 86400)
        recent = {d: sess for d, sess in index.items()
                  if datetime.fromisoformat(d).timestamp() > cutoff}

        for sess_id_list in recent.values():
            for sess_id in sess_id_list:
                # 尝试从Redis读取
                key = f"session_log:*:{sess_id}"
                # 简化：直接从文件读
                log_file = LOG_DIR / f"sess_{sess_id}.json"
                if log_file.exists():
                    with open(log_file, "r", encoding="utf-8") as f:
                        log = json.load(f)
                        if log.get("effect_score", 0) >= min_score:
                            logs.append(log)
                            if len(logs) >= limit:
                                return logs
        return logs

    def get_training_data_for_l3(self, min_score: float = 6.0, limit: int = 500) -> List[dict]:
        """导出L3训练格式的数据"""
        sessions = self.get_high_quality_sessions(min_score=min_score, limit=limit)
        training_data = []

        for sess in sessions:
            turns = sess.get("turns", [])
            if len(turns) < 2:
                continue

            # 构建对话消息
            messages = []
            for turn in turns:
                messages.append({
                    "role": turn["role"],
                    "content": turn["content"]
                })

            if len(messages) >= 2:
                training_data.append({
                    "messages": messages,
                    "scenario": sess.get("scenario_id", "unknown"),
                    "anxiety_level": sess.get("initial_anxiety", 5),
                    "insomnia_subtype": sess.get("insomnia_subtype", "mixed"),
                    "effectiveness_score": sess.get("effect_score", 5.0),
                    "outcome": sess.get("outcome", "unknown"),
                    "rating": sess.get("rating"),
                    "sleep_quality": sess.get("sleep_quality"),
                    "session_id": sess["session_id"],
                })

        return training_data

    def export_training_dataset(self, output_path: Path, min_score: float = 6.0):
        """导出完整训练数据集到JSONL文件"""
        data = self.get_training_data_for_l3(min_score=min_score)
        with open(output_path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"[SessionLogger] 导出 {len(data)} 条训练数据到 {output_path}")


# 单例
session_logger = SessionLogger()
