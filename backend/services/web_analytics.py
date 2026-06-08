"""
官网 (sleepai.chat) 流量监控 - 极简自研版

设计:
- 前端 /track.js 发送 pv (PV) 和 end (session 结束) 两类事件
- 后端写 Redis,admin 拉聚合
- 无第三方依赖,无 GA/友盟

Redis schema (所有 TTL = 90 天):
- web:events:{YYYY-MM-DD}        list  当日事件 JSON, 头插, cap 5000
- web:visitors:{YYYY-MM-DD}      set   当日独立访客 ID (UV)
- web:sessions:{YYYY-MM-DD}      set   当日 session ID
- web:session_meta:{session_id}  hash  {visitor_id,first_page,start_ts,last_ts,end_ts,duration_s,page_count,ip,ua}  TTL 24h
- web:page:{YYYY-MM-DD}:{page}   str   每页 PV 计数
"""
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List

EVENTS_TTL_DAYS = 90
SESSION_TTL_HOURS = 24
EVENTS_CAP_PER_DAY = 5000


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _decode(v):
    return v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v


def _decode_hash(h: Dict) -> Dict[str, str]:
    return {_decode(k): _decode(v) for k, v in (h or {}).items()}


def record_pageview(
    redis_client,
    visitor_id: str,
    session_id: str,
    page: str,
    ref: str = "",
    ua: str = "",
    ip: str = "",
) -> Dict[str, Any]:
    """记录单次 PV;同时更新 UV/sessions/session_meta/page 计数"""
    now = int(time.time() * 1000)
    today = _today()
    event = {
        "event": "pv",
        "visitor_id": visitor_id,
        "session_id": session_id,
        "page": (page or "/")[:200],
        "ref": (ref or "")[:200],
        "ua": (ua or "")[:200],
        "ip": ip or "",
        "ts": now,
    }
    try:
        # 1. 事件列表 (用于 recent + top-page 聚合)
        k_events = f"web:events:{today}"
        pipe = redis_client.pipeline()
        pipe.lpush(k_events, json.dumps(event, ensure_ascii=False))
        pipe.ltrim(k_events, 0, EVENTS_CAP_PER_DAY - 1)
        pipe.expire(k_events, EVENTS_TTL_DAYS * 86400)

        # 2. UV
        k_uv = f"web:visitors:{today}"
        pipe.sadd(k_uv, visitor_id)
        pipe.expire(k_uv, EVENTS_TTL_DAYS * 86400)

        # 3. Sessions
        k_sess = f"web:sessions:{today}"
        pipe.sadd(k_sess, session_id)
        pipe.expire(k_sess, EVENTS_TTL_DAYS * 86400)

        # 4. Page-level PV 计数
        page_short = event["page"][:100]
        k_page = f"web:page:{today}:{page_short}"
        pipe.incr(k_page)
        pipe.expire(k_page, EVENTS_TTL_DAYS * 86400)
        pipe.execute()

        # 5. Session meta (单独写,避免 pipeline 内 hgetall)
        k_meta = f"web:session_meta:{session_id}"
        existing = redis_client.hgetall(k_meta)
        if not existing:
            redis_client.hset(
                k_meta,
                mapping={
                    "visitor_id": visitor_id,
                    "first_page": event["page"],
                    "start_ts": str(now),
                    "last_ts": str(now),
                    "page_count": "1",
                    "ip": ip or "",
                    "ua": event["ua"],
                },
            )
        else:
            redis_client.hincrby(k_meta, "page_count", 1)
            redis_client.hset(k_meta, "last_ts", str(now))
        redis_client.expire(k_meta, SESSION_TTL_HOURS * 3600)

        return {"ok": True, "ts": now}
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


def record_session_end(redis_client, session_id: str, duration_s: int = 0) -> Dict[str, Any]:
    """用户关闭页面 / 切走时记录最终停留时长"""
    try:
        k_meta = f"web:session_meta:{session_id}"
        if not redis_client.exists(k_meta):
            return {"ok": False, "error": "session not found"}
        now = int(time.time() * 1000)
        redis_client.hset(k_meta, mapping={
            "end_ts": str(now),
            "duration_s": str(max(0, min(int(duration_s or 0), 7200))),  # cap 2h
        })
        redis_client.expire(k_meta, SESSION_TTL_HOURS * 3600)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


def get_overview(redis_client, days: int = 7) -> Dict[str, Any]:
    """N 天聚合: PV/UV/sessions/avg_duration/top_pages/daily_trend"""
    now = datetime.now()
    daily = []
    total_pv = 0
    total_uv_set = set()
    total_sessions = 0
    durations: List[int] = []
    page_counts: Dict[str, int] = {}

    for i in range(days):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        events = redis_client.lrange(f"web:events:{d}", 0, -1) or []
        pv = 0
        for raw in events:
            try:
                ev = json.loads(_decode(raw))
                if ev.get("event") == "pv":
                    pv += 1
                    p = (ev.get("page") or "/")[:100]
                    page_counts[p] = page_counts.get(p, 0) + 1
            except Exception:
                continue

        uvs = redis_client.smembers(f"web:visitors:{d}") or set()
        uv_list = [_decode(v) for v in uvs]
        sess = redis_client.smembers(f"web:sessions:{d}") or set()
        sess_list = [_decode(s) for s in sess]

        # 取该日 session 的实际时长 (只取前 200 个避免热查询慢)
        for sid in list(sess_list)[:200]:
            m = redis_client.hgetall(f"web:session_meta:{sid}")
            if not m:
                continue
            m = _decode_hash(m)
            try:
                # 优先用 duration_s (前端 end 上报); 否则 last_ts - start_ts
                d_s = int(m.get("duration_s", "0") or 0)
                if d_s <= 0:
                    start = int(m.get("start_ts", "0") or 0)
                    last = int(m.get("last_ts", "0") or 0)
                    if last > start:
                        d_s = (last - start) // 1000
                if 0 < d_s < 7200:
                    durations.append(d_s)
            except Exception:
                continue

        daily.append({"date": d, "pv": pv, "uv": len(uv_list), "sessions": len(sess_list)})
        total_pv += pv
        total_uv_set.update(uv_list)
        total_sessions += len(sess_list)

    avg_duration = int(sum(durations) / len(durations)) if durations else 0
    top_pages = sorted(page_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "days": days,
        "total_pv": total_pv,
        "total_uv": len(total_uv_set),
        "total_sessions": total_sessions,
        "avg_duration_s": avg_duration,
        "top_pages": [{"page": p, "pv": c} for p, c in top_pages],
        "daily_trend": list(reversed(daily)),  # 早→晚
    }


def get_recent_visits(redis_client, limit: int = 50) -> List[Dict[str, Any]]:
    """今日最近 N 条 PV 事件,实时面板用"""
    today = _today()
    raws = redis_client.lrange(f"web:events:{today}", 0, limit - 1) or []
    out: List[Dict[str, Any]] = []
    for raw in raws:
        try:
            ev = json.loads(_decode(raw))
            # 附上 session 时长 (snap shot)
            sid = ev.get("session_id", "")
            if sid:
                m = _decode_hash(redis_client.hgetall(f"web:session_meta:{sid}"))
                if m:
                    try:
                        d_s = int(m.get("duration_s", "0") or 0)
                        if d_s <= 0:
                            start = int(m.get("start_ts", "0") or 0)
                            last = int(m.get("last_ts", "0") or 0)
                            d_s = (last - start) // 1000 if last > start else 0
                        ev["duration_s"] = d_s
                        ev["page_count"] = int(m.get("page_count", "0") or 0)
                    except Exception:
                        pass
            out.append(ev)
        except Exception:
            continue
    return out
