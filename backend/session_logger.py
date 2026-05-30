"""
会话日志记录器
知眠 L2: 记录有效对话 → 用于 L3 Fine-tuning 数据积累
"""

import json
import time
import uuid
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
import redis
import os
from dialogue_evaluator import dialogue_evaluator
from alert_manager import send_alert, send_daily_report

from evaluation_tracker import record_session_evaluation, _get_morning_data
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
    """会话日志：内存缓冲 + Redis持久化 + 文件备份。

    v2.4 多用户安全:用 dict 按 (user_id, session_id) 键存放 active sessions,
    多个用户同时聊天时各自的 session 不再互相覆盖。

    线程安全:外层是单进程 asyncio 单线程 + run_in_threadpool,read/write 之间
    有锁保护(_lock)。
    """

    def __init__(self):
        # 多会话状态:(user_id, session_id) -> SessionLog
        self._active_sessions: Dict[Tuple[str, str], SessionLog] = {}
        import threading
        self._lock = threading.RLock()
        self._buffer: List[Dict] = []
        self._buffer_size = 10

    # ---------- 内部:键查找 ----------

    def _find_by_session_id(self, session_id: str) -> Optional[SessionLog]:
        """跨用户按 session_id 查(用于 update_rating)。"""
        for sess in self._active_sessions.values():
            if sess.session_id == session_id:
                return sess
        return None

    def _most_recent_for_user(self, user_id: str) -> Optional[SessionLog]:
        """找该用户最近活动的 session(用于 morning 打卡 finalize)。"""
        candidates = [s for (u, _), s in self._active_sessions.items() if u == user_id]
        if not candidates:
            return None
        def last_ts(s):
            iso = getattr(s, "_last_activity", None) or s.start_time
            try: return datetime.fromisoformat(iso).timestamp()
            except Exception: return 0
        return max(candidates, key=last_ts)

    # ---------- 会话生命周期 ----------

    def start_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        insomnia_subtype: Optional[str] = None,
        stage: Optional[str] = None
    ) -> str:
        """开始一个新会话(若同 key 已存在,返回现有 session_id 不覆盖)。"""
        session_id = session_id or f"sess_{int(time.time())}"
        with self._lock:
            key = (user_id, session_id)
            if key in self._active_sessions:
                return session_id
            self._active_sessions[key] = SessionLog(
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
        """记录一轮对话。需要 user_id+session_id 才能路由(向后兼容:都缺则丢)。"""
        if not user_id or not session_id:
            return
        with self._lock:
            key = (user_id, session_id)
            sess = self._active_sessions.get(key)
            if not sess:
                self.start_session(user_id=user_id, session_id=session_id)
                sess = self._active_sessions.get(key)
                if not sess:
                    return

            turn = ConversationTurn(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                technique_used=technique_used,
                anxiety_level=anxiety_level,
            )
            sess.turns.append(turn)
            try:
                sess._last_activity = turn.timestamp
            except Exception:
                pass

            if len(sess.turns) == 1 and anxiety_level:
                sess.initial_anxiety = anxiety_level
            if scenario_id:
                sess.scenario_id = scenario_id

    def update_anxiety(self, level: int, user_id: Optional[str] = None,
                       session_id: Optional[str] = None):
        """更新焦虑等级。需要 user_id+session_id 定位会话。"""
        if not user_id or not session_id:
            return
        with self._lock:
            sess = self._active_sessions.get((user_id, session_id))
            if sess and sess.turns:
                sess.turns[-1].anxiety_level = level
                sess.final_anxiety = level

    def update_rating(self, session_id: str, rating: int, notes: Optional[str] = None) -> bool:
        """会话结束后补录用户评分（用于延迟收集方案）"""
        # 如果存在活跃会话匹配，直接更新并保存
        sess = self._find_by_session_id(session_id)
        if sess:
            sess.rating = rating
            if notes:
                sess.notes = notes
            self._save_log(sess.to_dict())
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

    def finalize_if_idle(self, max_idle_minutes: int = 15) -> int:
        """扫描所有活跃会话,空转 ≥ max_idle_minutes 的统一 end_session(idle_timeout)。
        每个 add_turn 会刷新 _last_activity;周期 janitor 调用本方法。
        Returns: 本次 finalize 掉的会话数。"""
        now_ts = time.time()
        cutoff_sec = max_idle_minutes * 60
        with self._lock:
            stale_keys: List[Tuple[str, str]] = []
            for key, sess in list(self._active_sessions.items()):
                last_iso = getattr(sess, "_last_activity", None) or sess.start_time
                try:
                    last_ts = datetime.fromisoformat(last_iso).timestamp()
                except Exception:
                    continue
                if (now_ts - last_ts) < cutoff_sec:
                    continue
                # 空会话(无用户轮)直接丢
                n_user_turns = sum(1 for t in sess.turns if t.role == "user")
                if n_user_turns < 1:
                    del self._active_sessions[key]
                    continue
                stale_keys.append(key)
        # 锁外执行 end_session(end_session 自己会再上锁)
        n = 0
        for (uid, sid) in stale_keys:
            self.end_session(outcome="idle_timeout", user_id=uid, session_id=sid)
            n += 1
        return n

    def end_session(
        self,
        outcome: str = "completed",
        sleep_quality: Optional[int] = None,
        rating: Optional[int] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """结束指定会话(需 user_id+session_id 路由)。"""
        if not user_id or not session_id:
            # 兼容:若调用者没传,但当前仅有一个活跃会话,则关那个
            with self._lock:
                if len(self._active_sessions) == 1:
                    (user_id, session_id) = next(iter(self._active_sessions.keys()))
                else:
                    return
        with self._lock:
            sess = self._active_sessions.get((user_id, session_id))
            if not sess:
                return
            sess.end_time = datetime.now().isoformat()
            sess.outcome = outcome
            if sleep_quality:
                sess.sleep_quality = sleep_quality
            if rating:
                sess.rating = rating
            if notes:
                sess.notes = notes

        # 锁外执行重计算 + 评估 + IO(都比较慢,避免阻塞其它会话)
        effect_score = self._compute_effect_score(sess)
        eval_result = dialogue_evaluator.evaluate_session(sess.to_dict())
        quality_eval = dialogue_evaluator.to_dict(eval_result)
        session_dict = sess.to_dict()

        # 关联晨间睡眠数据
        user_id = session_dict.get("user_id", "")
        session_id = session_dict.get("session_id", "")
        session_date = None
        if session_id:
            import re
            m = re.match(r"session_(\d{4}-\d{2}-\d{2})_", session_id)
            if m:
                session_date = m.group(1)

        morning_data = None
        if user_id and session_date:
            try:
                morning_data = _get_morning_data(user_id, session_date)
            except Exception:
                pass

        # 构造带晨间数据的增强评估报告
        enhanced_report = dict(quality_eval)
        if morning_data:
            enhanced_report["_morning"] = {
                "sleep_quality": morning_data.get("sleep_quality"),
                "se": morning_data.get("se"),
                "tst_minutes": morning_data.get("tst_minutes"),
                "fatigue_level": morning_data.get("fatigue_level"),
                "waso_minutes": morning_data.get("waso_minutes", 0),
            }

        log_entry = {
            **session_dict,
            "effect_score": effect_score,
            "effect_breakdown": {
                "outcome_score": 1.0 if outcome in ("completed_closure", "sleep_reported") else 0.0,
                "rating_score": (rating or 3) / 5.0,
                "anxiety_reduction": max(0, (int(sess.initial_anxiety or 5)) - (int(sess.final_anxiety or 5))) / 10.0,
            },
            "quality_evaluation": quality_eval,
        }
        if morning_data:
            log_entry["morning_data"] = morning_data

        self._save_log(log_entry)

        # 触发告警（不合格/需改进）
        try:
            report = quality_eval.get("report", {})
            if report:
                send_alert(report, session_dict)
        except Exception as e:
            print(f"[SessionLogger] 告警发送失败: {e}")

        # 记录会话粒度评估（关联晨间睡眠数据）
        try:
            record_session_evaluation(session_id, enhanced_report, user_id=user_id)
        except Exception as e:
            print(f"[SessionLogger] 评估记录失败: {e}")

        # v2.4: 关系深化兜底 — 任何 ≥3 用户轮的 finalize 都累加 session_count
        # + 刷新 last_session_time。原本只有 closure 路径会做这件事,导致流失会话
        # 不被记得;现在 idle_timeout / interrupted / completed_closure / sleep_reported
        # 都会触发,真摘要(last_session_summary)仍由 closure 路径独占写入。
        try:
            n_user_turns = sum(1 for t in sess.turns if t.role == "user")
            if n_user_turns >= 3 and outcome in (
                "completed_closure", "sleep_reported", "idle_timeout", "interrupted"
            ):
                from infra.redis_client import redis_client as _rc
                mem_key = f"user:memory:{user_id}"
                raw = _rc.get(mem_key)
                memory = json.loads(raw) if raw else {}
                memory["session_count"] = int(memory.get("session_count", 0)) + 1
                memory["last_session_time"] = datetime.now().isoformat(timespec="seconds")
                # 若上次主题域可推断,记录(不覆盖 closure 路径写的真摘要)
                last_dom = None
                for t in reversed(sess.turns):
                    if t.role == "user" and getattr(t, "scenario_id", None):
                        last_dom = t.scenario_id
                        break
                if last_dom and not memory.get("last_topic_domain"):
                    memory["last_topic_domain"] = last_dom
                _rc.setex(mem_key, 90 * 86400, json.dumps(memory, ensure_ascii=False))
        except Exception as e:
            print(f"[SessionLogger] session_count bump 失败(非关键): {e}")

        # 从活跃表移除
        with self._lock:
            self._active_sessions.pop((user_id, session_id), None)

    # ---------- 效果评分（用于L3训练数据筛选）----------

    def _compute_effect_score(self, sess: Optional[SessionLog] = None) -> float:
        """计算会话效果分数 0-10。可传入特定 session,缺省则不合法返回 0。"""
        if sess is None:
            return 0.0
        s = sess

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
