"""
B2B 销售线索 (sales lead) 服务。

来源:
- 官网 /enterprise 页 CTA 提交的咨询表单(API: /api/v1/sales/lead)
- 后续可加:HR admin 自助下单时漏过的对话框等

数据模型 (Redis):
  sales_leads:pending    zset, score=ts_ms,  member=lead_id  (未跟进)
  sales_leads:archived   zset, score=ts_ms,  member=lead_id  (已跟进/关闭)
  sales_lead:{lead_id}   hash, full lead record (TTL: pending=∞, archived=180d)

字段:
  lead_id, company_name, contact_name, contact_email, contact_phone,
  team_size, message, locale, source, created_at,
  status (pending|contacted|qualified|closed_won|closed_lost),
  notes, follow_up_operator
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from infra.redis_client import redis_client


KEY_PENDING = "sales_leads:pending"
KEY_ARCHIVED = "sales_leads:archived"
KEY_PREFIX = "sales_lead:"

# 180 天后归档项过期
TTL_ARCHIVED_SECONDS = 180 * 24 * 3600
# pending 不主动过期,但兜底 1 年
TTL_PENDING_FALLBACK = 365 * 24 * 3600

# 截断防止过长字段撑爆 Redis
MAX_NAME_LEN = 100
MAX_EMAIL_LEN = 200
MAX_PHONE_LEN = 30
MAX_MESSAGE_LEN = 2000
MAX_NOTES_LEN = 1000

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _redis_or_raise():
    if not redis_client:
        raise RuntimeError("Redis client not initialized")
    return redis_client


def _key(lead_id: str) -> str:
    return f"{KEY_PREFIX}{lead_id}"


def _decode(d: Dict[Any, Any]) -> Dict[str, str]:
    out = {}
    for k, v in (d or {}).items():
        if isinstance(k, bytes): k = k.decode()
        if isinstance(v, bytes): v = v.decode()
        out[k] = v
    return out


def submit_lead(
    company_name: str,
    contact_email: str,
    contact_name: str = "",
    team_size: str = "",
    contact_phone: str = "",
    message: str = "",
    locale: str = "zh",
    source: str = "/enterprise",
) -> Dict[str, Any]:
    """提交一条销售线索。验证 + 防过长 + 落 Redis。Returns 创建的线索 dict。"""
    company_name = (company_name or "").strip()[:MAX_NAME_LEN]
    contact_name = (contact_name or "").strip()[:MAX_NAME_LEN]
    contact_email = (contact_email or "").strip().lower()[:MAX_EMAIL_LEN]
    contact_phone = (contact_phone or "").strip()[:MAX_PHONE_LEN]
    team_size = (team_size or "").strip()[:30]
    message = (message or "").strip()[:MAX_MESSAGE_LEN]
    locale = (locale or "zh")[:5]
    source = (source or "")[:100]

    if not company_name:
        raise ValueError("company_name is required")
    if not contact_email or not _EMAIL_RE.match(contact_email):
        raise ValueError("contact_email is invalid")

    r = _redis_or_raise()
    lead_id = uuid.uuid4().hex[:16]
    now_ms = int(time.time() * 1000)
    record = {
        "lead_id": lead_id,
        "company_name": company_name,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "team_size": team_size,
        "message": message,
        "locale": locale,
        "source": source,
        "created_at": _now_iso(),
        "status": "pending",
        "notes": "",
        "follow_up_operator": "",
    }
    try:
        r.hset(_key(lead_id), mapping=record)
        r.expire(_key(lead_id), TTL_PENDING_FALLBACK)
        r.zadd(KEY_PENDING, {lead_id: now_ms})
        logging.info(f"[SalesLead] new lead {lead_id} from {company_name} ({contact_email})")
    except Exception as e:
        logging.error(f"[SalesLead] redis write failed: {e}")
        raise
    return record


def get_lead(lead_id: str) -> Optional[Dict[str, Any]]:
    r = _redis_or_raise()
    raw = r.hgetall(_key(lead_id))
    if not raw:
        return None
    return _decode(raw)


def list_leads(status: str = "pending", limit: int = 100) -> List[Dict[str, Any]]:
    """按状态列表。status='pending' 看待跟进的,'archived' 看历史的。"""
    r = _redis_or_raise()
    key = KEY_PENDING if status == "pending" else KEY_ARCHIVED
    # 按时间倒序(最新在前)
    ids = r.zrevrange(key, 0, limit - 1)
    out: List[Dict[str, Any]] = []
    for lid in ids:
        if isinstance(lid, bytes): lid = lid.decode()
        rec = get_lead(lid)
        if rec:
            out.append(rec)
    return out


def update_lead(
    lead_id: str,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    operator: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """更新线索状态/备注/跟进人。

    status ∈ {pending, contacted, qualified, closed_won, closed_lost}
    - 切到 closed_* 时 → 自动从 pending zset 移到 archived
    - 切回 pending → 从 archived 移回 pending
    """
    r = _redis_or_raise()
    if not r.exists(_key(lead_id)):
        return None

    updates: Dict[str, Any] = {}
    if status:
        if status not in ("pending", "contacted", "qualified", "closed_won", "closed_lost"):
            raise ValueError(f"invalid status: {status}")
        updates["status"] = status
    if notes is not None:
        updates["notes"] = (notes or "")[:MAX_NOTES_LEN]
    if operator is not None:
        updates["follow_up_operator"] = (operator or "")[:50]

    if updates:
        r.hset(_key(lead_id), mapping=updates)

    # 移动 zset 队列
    if status:
        if status in ("closed_won", "closed_lost"):
            r.zrem(KEY_PENDING, lead_id)
            r.zadd(KEY_ARCHIVED, {lead_id: int(time.time() * 1000)})
            r.expire(_key(lead_id), TTL_ARCHIVED_SECONDS)
        elif status == "pending":
            r.zrem(KEY_ARCHIVED, lead_id)
            r.zadd(KEY_PENDING, {lead_id: int(time.time() * 1000)})
            r.expire(_key(lead_id), TTL_PENDING_FALLBACK)

    return get_lead(lead_id)


def delete_lead(lead_id: str) -> bool:
    """物理删除一条销售线索 (含 hash + 两个 zset 索引)。

    Returns:
        True 若实际删除了; False 若不存在
    """
    r = _redis_or_raise()
    if not r.exists(_key(lead_id)):
        return False
    pipe = r.pipeline()
    pipe.delete(_key(lead_id))
    pipe.zrem(KEY_PENDING, lead_id)
    pipe.zrem(KEY_ARCHIVED, lead_id)
    pipe.execute()
    return True


def get_stats() -> Dict[str, Any]:
    """运营快速看板:各状态计数。"""
    r = _redis_or_raise()
    pending_n = int(r.zcard(KEY_PENDING) or 0)
    archived_n = int(r.zcard(KEY_ARCHIVED) or 0)
    # 状态细分
    by_status = {"pending": 0, "contacted": 0, "qualified": 0,
                 "closed_won": 0, "closed_lost": 0}
    for lid in r.zrevrange(KEY_PENDING, 0, 500):
        if isinstance(lid, bytes): lid = lid.decode()
        rec = get_lead(lid)
        if rec:
            s = rec.get("status", "pending")
            by_status[s] = by_status.get(s, 0) + 1
    for lid in r.zrevrange(KEY_ARCHIVED, 0, 500):
        if isinstance(lid, bytes): lid = lid.decode()
        rec = get_lead(lid)
        if rec:
            s = rec.get("status", "closed_lost")
            by_status[s] = by_status.get(s, 0) + 1
    return {
        "pending_count": pending_n,
        "archived_count": archived_n,
        "total": pending_n + archived_n,
        "by_status": by_status,
    }


async def send_lead_notification(lead: Dict[str, Any], to_email: str) -> bool:
    """通过 Resend 发邮件通知运营。无 KEY 则跳过。"""
    import httpx
    from infra.settings import settings
    api_key = getattr(settings, "resend_api_key", "") or os.getenv("RESEND_API_KEY", "")
    if not api_key or not to_email:
        return False
    subject = f"[知眠企业版] 新线索:{lead.get('company_name', '?')} · {lead.get('team_size', '?')}"
    body = (
        f"知眠 B2B 销售收到新咨询:\n\n"
        f"  公司:       {lead.get('company_name', '')}\n"
        f"  联系人:     {lead.get('contact_name', '')}\n"
        f"  邮箱:       {lead.get('contact_email', '')}\n"
        f"  电话:       {lead.get('contact_phone') or '(未填)'}\n"
        f"  团队规模:   {lead.get('team_size') or '(未填)'}\n"
        f"  来源:       {lead.get('source', '')}\n"
        f"  时间:       {lead.get('created_at', '')}\n\n"
        f"留言:\n{lead.get('message') or '(无)'}\n\n"
        f"线索 ID:{lead.get('lead_id', '')}\n"
        f"在 admin 后台跟进:https://sleepai.chat/admin/#leads\n"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "from": getattr(settings, "auth_from_email", "ZhiMian Sales <noreply@sleepai.chat>"),
                    "to": [to_email],
                    "subject": subject,
                    "text": body,
                },
            )
            return resp.status_code in (200, 201)
    except Exception as e:
        logging.warning(f"[SalesLead] notify failed: {e}")
        return False
