"""
企业 / 团队 / 邀请码服务 — B2B 数据层

数据模型(Redis)：
  org:{org_id}                hash    企业元数据
                                      fields: name, industry, seat_quota,
                                              contact_hr_email, status,
                                              created_at(ISO), period_end(ISO,可选)
  org:invite:{code}           hash    邀请码 → org_id+team_id+expire_at+max_uses+used
  org:teams:{org_id}          set     该企业的所有 team_id
  team:{team_id}              hash    team_name, org_id, manager_email, created_at
  org:users:{org_id}          set     该企业的所有 user_id (用于人数/k-anonymity)
  team:users:{team_id}        set     该 team 的所有 user_id
  user:org:{user_id}          str     反向索引: user_id → org_id (JWT 签发时注入)
  user:team:{user_id}         str     反向索引: user_id → team_id (无 team 则空)

设计原则：
- 所有键以 org: / team: / user:org: / user:team: 前缀,与现有
  user:profile:* / user:memory:* / session_state:* 物理隔离,不会污染 B2C 数据
- seat_quota 软限制:bind 时检查 |org:users:{org_id}| < seat_quota,
  超额则拒绝绑定(返 error,客户端引导 HR 升级套餐)
- invite_code 一次性 vs 可重复使用:由 max_uses 控制(默认 1 = 一次性)
- 邀请码不区分大小写,生成时全部大写
"""
from __future__ import annotations

import json
import secrets
import string
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from infra.redis_client import redis_client


# ===== Redis Keys =====
def k_org(org_id: str) -> str: return f"org:{org_id}"
def k_org_invite(code: str) -> str: return f"org:invite:{code}"
def k_org_teams(org_id: str) -> str: return f"org:teams:{org_id}"
def k_team(team_id: str) -> str: return f"team:{team_id}"
def k_org_users(org_id: str) -> str: return f"org:users:{org_id}"
def k_team_users(team_id: str) -> str: return f"team:users:{team_id}"
def k_user_org(user_id: str) -> str: return f"user:org:{user_id}"
def k_user_team(user_id: str) -> str: return f"user:team:{user_id}"


# ===== ID / Code Generation =====
_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 去掉易混淆的 I/O/0/1


def _gen_org_id() -> str:
    return "org_" + secrets.token_urlsafe(6)[:8].replace("-", "x").replace("_", "y")


def _gen_team_id() -> str:
    return "tm_" + secrets.token_urlsafe(4)[:6].replace("-", "x").replace("_", "y")


def _gen_invite_code(length: int = 6) -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(length))


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _redis_or_raise():
    if not redis_client:
        raise RuntimeError("Redis client not initialized")
    return redis_client


# ===== Org CRUD =====
def create_org(
    name: str,
    industry: str = "",
    seat_quota: int = 50,
    contact_hr_email: str = "",
    period_end: Optional[str] = None,
) -> str:
    """创建企业,返回 org_id。"""
    if not name:
        raise ValueError("name is required")
    r = _redis_or_raise()
    org_id = _gen_org_id()
    while r.exists(k_org(org_id)):     # 极小概率冲突,重试
        org_id = _gen_org_id()
    r.hset(k_org(org_id), mapping={
        "org_id": org_id,
        "name": name,
        "industry": industry,
        "seat_quota": int(seat_quota),
        "contact_hr_email": contact_hr_email,
        "status": "active",
        "created_at": _now_iso(),
        "period_end": period_end or "",
    })
    return org_id


def get_org(org_id: str) -> Optional[Dict[str, Any]]:
    r = _redis_or_raise()
    data = r.hgetall(k_org(org_id))
    if not data:
        return None
    if isinstance(next(iter(data.keys()), ""), bytes):  # 兼容 decode_responses=False
        data = {k.decode(): v.decode() for k, v in data.items()}
    if "seat_quota" in data:
        try: data["seat_quota"] = int(data["seat_quota"])
        except Exception: pass
    return data


def update_org_seat_quota(org_id: str, seat_quota: int) -> bool:
    r = _redis_or_raise()
    if not r.exists(k_org(org_id)):
        return False
    r.hset(k_org(org_id), "seat_quota", int(seat_quota))
    return True


# ===== Team CRUD =====
def create_team(org_id: str, team_name: str, manager_email: str = "") -> str:
    r = _redis_or_raise()
    if not r.exists(k_org(org_id)):
        raise ValueError(f"org {org_id} does not exist")
    team_id = _gen_team_id()
    while r.exists(k_team(team_id)):
        team_id = _gen_team_id()
    r.hset(k_team(team_id), mapping={
        "team_id": team_id,
        "org_id": org_id,
        "team_name": team_name,
        "manager_email": manager_email,
        "created_at": _now_iso(),
    })
    r.sadd(k_org_teams(org_id), team_id)
    return team_id


def get_team(team_id: str) -> Optional[Dict[str, Any]]:
    r = _redis_or_raise()
    data = r.hgetall(k_team(team_id))
    if not data:
        return None
    if isinstance(next(iter(data.keys()), ""), bytes):
        data = {k.decode(): v.decode() for k, v in data.items()}
    return data


def list_teams(org_id: str) -> List[str]:
    r = _redis_or_raise()
    return sorted(_smembers_str(r, k_org_teams(org_id)))


# ===== Invite Code =====
def create_invite_code(
    org_id: str,
    team_id: Optional[str] = None,
    expire_days: int = 30,
    max_uses: int = 1,
    role: str = "user",   # v2.6: 邀请码可以是 HR 入职码
) -> str:
    """创建邀请码。

    Args:
        role: "user" (员工,默认) | "hr_admin" (HR — 用码加入即自动拉成 HR)
    """
    if role not in ("user", "hr_admin"):
        raise ValueError(f"invalid role: {role!r}")
    r = _redis_or_raise()
    if not r.exists(k_org(org_id)):
        raise ValueError(f"org {org_id} does not exist")
    if team_id and not r.exists(k_team(team_id)):
        raise ValueError(f"team {team_id} does not exist")
    code = _gen_invite_code()
    while r.exists(k_org_invite(code)):
        code = _gen_invite_code()
    expire_at = (datetime.utcnow() + timedelta(days=int(expire_days))).isoformat(timespec="seconds") + "Z"
    r.hset(k_org_invite(code), mapping={
        "code": code,
        "org_id": org_id,
        "team_id": team_id or "",
        "expire_at": expire_at,
        "max_uses": int(max_uses),
        "used": 0,
        "role": role,
        "created_at": _now_iso(),
    })
    # 邀请码 hash 设 TTL,过期自动消失(给 expire_days + 7 天兜底)
    r.expire(k_org_invite(code), (int(expire_days) + 7) * 86400)
    return code


def get_invite_code(code: str) -> Optional[Dict[str, Any]]:
    r = _redis_or_raise()
    data = r.hgetall(k_org_invite(code.upper()))
    if not data:
        return None
    if isinstance(next(iter(data.keys()), ""), bytes):
        data = {k.decode(): v.decode() for k, v in data.items()}
    if "max_uses" in data:
        try: data["max_uses"] = int(data["max_uses"])
        except Exception: pass
    if "used" in data:
        try: data["used"] = int(data["used"])
        except Exception: pass
    return data


# ===== Membership =====
def bind_user_to_org(
    user_id: str,
    invite_code: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """绑定用户到企业。

    Returns: (success, message, info_dict)
      info_dict on success: {"org_id":..., "team_id":..., "code":..., "org_name":...}
    """
    r = _redis_or_raise()
    code = (invite_code or "").upper().strip()
    if not code:
        return False, "invite_code is required", None
    inv = get_invite_code(code)
    if not inv:
        return False, "邀请码无效或已过期", None
    # 过期
    try:
        if datetime.fromisoformat(inv["expire_at"].replace("Z", "")) < datetime.utcnow():
            return False, "邀请码已过期", None
    except Exception:
        pass
    # 用量
    used = int(inv.get("used", 0))
    max_uses = int(inv.get("max_uses", 1))
    if used >= max_uses:
        return False, "邀请码已用完", None

    org_id = inv["org_id"]
    team_id = inv.get("team_id") or None

    # seat_quota 配额
    org = get_org(org_id)
    if not org:
        return False, "企业不存在", None
    seat_quota = int(org.get("seat_quota", 0))
    current_seats = r.scard(k_org_users(org_id))
    # 同一用户重复绑相同 org 不算占额
    already_in_this_org = r.sismember(k_org_users(org_id), user_id)
    if not already_in_this_org and seat_quota > 0 and current_seats >= seat_quota:
        return False, f"企业席位已满({current_seats}/{seat_quota})", None

    # 已经在其它 org → 拒绝(避免数据混淆;切换 org 需先 unbind)
    existing_org = r.get(k_user_org(user_id))
    if isinstance(existing_org, bytes): existing_org = existing_org.decode()
    if existing_org and existing_org != org_id:
        return False, f"用户已属于另一企业({existing_org}),请先退出", None

    # 写正向 + 反向索引
    r.sadd(k_org_users(org_id), user_id)
    r.set(k_user_org(user_id), org_id)
    if team_id:
        r.sadd(k_team_users(team_id), user_id)
        r.set(k_user_team(user_id), team_id)
    # 邀请码用量 +1
    r.hincrby(k_org_invite(code), "used", 1)

    # v2.6: HR 入职码 (role=hr_admin) 自动拉升为 HR;
    # 普通员工码 (role=user) 不降级既有 HR (避免误操作)
    invite_role = (inv.get("role") or "user").strip()
    if invite_role == "hr_admin" and get_user_role(user_id) != "hr_admin":
        set_user_role(user_id, "hr_admin")

    return True, "ok", {
        "org_id": org_id,
        "team_id": team_id or "",
        "code": code,
        "org_name": org.get("name", ""),
        "role": get_user_role(user_id),
    }


def unbind_user(user_id: str) -> bool:
    """员工退订/离职 — 从企业 + team 清除索引。
    注意:不删 user:profile:{user_id} 等 B2C 数据(保留个人记录)。"""
    r = _redis_or_raise()
    org_id = r.get(k_user_org(user_id))
    if isinstance(org_id, bytes): org_id = org_id.decode()
    team_id = r.get(k_user_team(user_id))
    if isinstance(team_id, bytes): team_id = team_id.decode()
    pipe = r.pipeline()
    if org_id:
        pipe.srem(k_org_users(org_id), user_id)
    if team_id:
        pipe.srem(k_team_users(team_id), user_id)
    pipe.delete(k_user_org(user_id))
    pipe.delete(k_user_team(user_id))
    pipe.execute()
    return bool(org_id)


def get_user_org(user_id: str) -> Optional[str]:
    r = _redis_or_raise()
    v = r.get(k_user_org(user_id))
    if isinstance(v, bytes): v = v.decode()
    return v or None


def get_user_team(user_id: str) -> Optional[str]:
    r = _redis_or_raise()
    v = r.get(k_user_team(user_id))
    if isinstance(v, bytes): v = v.decode()
    return v or None


def list_org_users(org_id: str) -> List[str]:
    r = _redis_or_raise()
    return sorted(_smembers_str(r, k_org_users(org_id)))


def list_team_users(team_id: str) -> List[str]:
    r = _redis_or_raise()
    return sorted(_smembers_str(r, k_team_users(team_id)))


def delete_org(org_id: str) -> Dict[str, int]:
    """级联删除一家企业 + 所有相关索引 / 邀请码 / 报告缓存。

    **不删用户的个人数据** (user_profile / sleep_diary / worry 等保留 B2C 历史),
    只清理"该用户属于这个 org"的反向索引;HR 角色降级为 user。

    Returns:
        {"org_meta": 1/0, "teams": N, "invites": N, "users_unbound": N, "reports": N}
    """
    r = _redis_or_raise()
    stats = {"org_meta": 0, "teams": 0, "invites": 0,
             "users_unbound": 0, "reports": 0, "members": 0}

    # 1) 列出该 org 下的 user_ids → 清反向索引 + 角色降级
    user_ids = list_org_users(org_id)
    for uid in user_ids:
        r.delete(k_user_org(uid))
        r.delete(k_user_team(uid))
        # 角色降为普通用户 (避免遗留 hr_admin 在没企业的用户上)
        if get_user_role(uid) == "hr_admin":
            set_user_role(uid, "user")
        stats["users_unbound"] += 1

    # 2) 列出 org 下的 teams → 删 team meta + team_users set
    team_ids = list(_smembers_str(r, k_org_teams(org_id)))
    for tid in team_ids:
        r.delete(k_team(tid))
        r.delete(k_team_users(tid))
        stats["teams"] += 1
    r.delete(k_org_teams(org_id))

    # 3) 扫所有 org:invite:* → 把属于该 org 的码删掉
    for key in r.scan_iter(match="org:invite:*", count=500):
        k = key.decode() if isinstance(key, bytes) else key
        inv_org = r.hget(k, "org_id")
        if isinstance(inv_org, bytes): inv_org = inv_org.decode()
        if inv_org == org_id:
            r.delete(k)
            stats["invites"] += 1

    # 4) 清月报缓存 org:report:{org_id}:*
    for key in r.scan_iter(match=f"org:report:{org_id}:*", count=200):
        r.delete(key)
        stats["reports"] += 1

    # 5) 计费 + members 集合 + org 元数据
    r.delete(f"org:billing:{org_id}")
    stats["members"] = r.scard(k_org_users(org_id)) or 0
    r.delete(k_org_users(org_id))

    deleted = r.delete(k_org(org_id))
    stats["org_meta"] = int(deleted or 0)

    # 6) 全局 org 索引 set (列表用)
    r.srem("org_index", org_id)

    return stats


def org_seat_usage(org_id: str) -> Tuple[int, int]:
    """Returns (current_used, seat_quota)。"""
    r = _redis_or_raise()
    current = r.scard(k_org_users(org_id))
    org = get_org(org_id)
    quota = int(org.get("seat_quota", 0)) if org else 0
    return int(current), quota


# ===== User Role =====
def k_user_role(user_id: str) -> str:
    return f"user:role:{user_id}"


def get_user_role(user_id: str) -> str:
    """Returns 'user' (default) | 'hr_admin'。"""
    r = _redis_or_raise()
    v = r.get(k_user_role(user_id))
    if isinstance(v, bytes): v = v.decode()
    return v or "user"


def set_user_role(user_id: str, role: str) -> bool:
    """设置用户角色。仅由 admin 端点调用。"""
    if role not in ("user", "hr_admin"):
        raise ValueError(f"invalid role: {role}")
    r = _redis_or_raise()
    if role == "user":
        r.delete(k_user_role(user_id))
    else:
        r.set(k_user_role(user_id), role)
    return True


# ===== utils =====
def _smembers_str(r, key) -> List[str]:
    members = r.smembers(key) or set()
    out = []
    for m in members:
        if isinstance(m, bytes): m = m.decode()
        out.append(m)
    return out
