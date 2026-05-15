"""
RAG 知识库版本管理

功能：
- 记录每次索引构建的版本信息
- 计算 corpus 文件哈希，追踪变更
- 支持查看历史版本和回滚
- 版本元数据存储在 Redis

索引目录结构：
  vector_index/
    current/          -> 当前活跃索引（软链接或复制）
    v_{timestamp}/    -> 版本化索引目录
    versions.json     -> 版本清单
"""

import json
import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from infra.redis_client import redis_client
from services.admin_audit import log_admin_action

KB_VERSION_KEY = "admin:kb:versions"
KB_CURRENT_VERSION_KEY = "admin:kb:current_version"

# 默认索引目录（与 rag_engine.py 保持一致）
DEFAULT_INDEX_DIR = Path("/home/ubuntu/anmian/backend/vector_index")
DEFAULT_CORPUS_DIR = Path("/home/ubuntu/anmian/corpus")


def _hash_file(path: Path) -> str:
    """计算文件 SHA256 哈希"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


def _get_corpus_hashes(corpus_dir: Path = None) -> Dict[str, str]:
    """获取所有 corpus 文件的哈希值"""
    corpus_dir = corpus_dir or DEFAULT_CORPUS_DIR
    hashes = {}
    if not corpus_dir.exists():
        return hashes
    for f in sorted(corpus_dir.iterdir()):
        if f.is_file():
            hashes[f.name] = _hash_file(f)
    return hashes


def _get_index_metrics(index_dir: Path) -> Dict[str, Any]:
    """获取索引目录的指标信息"""
    metrics = {"exists": False, "files": [], "total_size_mb": 0}
    if not index_dir.exists():
        return metrics
    metrics["exists"] = True
    total_size = 0
    for root, _, files in os.walk(index_dir):
        for f in files:
            fp = Path(root) / f
            total_size += fp.stat().st_size
            metrics["files"].append(f)
    metrics["total_size_mb"] = round(total_size / (1024 * 1024), 2)
    return metrics


def get_kb_versions(limit: int = 20) -> List[Dict[str, Any]]:
    """获取知识库版本历史"""
    try:
        raw = redis_client.get(KB_VERSION_KEY)
        if raw:
            versions = json.loads(raw)
            return versions[:limit]
    except Exception:
        pass
    return []


def get_current_kb_version() -> Optional[str]:
    """获取当前活跃的版本 ID"""
    try:
        return redis_client.get(KB_CURRENT_VERSION_KEY) or ""
    except Exception:
        return ""


def get_kb_status() -> Dict[str, Any]:
    """获取知识库当前状态"""
    current_version = get_current_kb_version()
    versions = get_kb_versions(limit=1)
    latest = versions[0] if versions else None

    corpus_hashes = _get_corpus_hashes()
    index_metrics = _get_index_metrics(DEFAULT_INDEX_DIR)

    # 检查 corpus 是否有变更（与最新版本对比）
    has_changes = False
    if latest and latest.get("corpus_hashes"):
        old_hashes = latest["corpus_hashes"]
        for fname, h in corpus_hashes.items():
            if old_hashes.get(fname) != h:
                has_changes = True
                break

    return {
        "current_version": current_version,
        "latest_version": latest["version_id"] if latest else "",
        "total_versions": len(get_kb_versions(limit=100)),
        "corpus_files": len(corpus_hashes),
        "corpus_hashes": corpus_hashes,
        "index_metrics": index_metrics,
        "has_unsaved_changes": has_changes,
        "index_dir": str(DEFAULT_INDEX_DIR),
        "corpus_dir": str(DEFAULT_CORPUS_DIR),
    }


def create_kb_version(
    operator: str = "admin",
    notes: str = "",
    index_dir: Path = None,
    corpus_dir: Path = None,
) -> Dict[str, Any]:
    """
    创建新的知识库版本：
    1. 备份当前索引到版本化目录
    2. 记录版本元数据
    3. 更新当前版本指针
    """
    index_dir = index_dir or DEFAULT_INDEX_DIR
    corpus_dir = corpus_dir or DEFAULT_CORPUS_DIR

    version_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_dir = index_dir.parent / f"v_{version_id}"

    # 备份当前索引（如果存在）
    if index_dir.exists():
        try:
            if version_dir.exists():
                shutil.rmtree(version_dir)
            shutil.copytree(index_dir, version_dir)
        except Exception as e:
            return {"success": False, "error": f"备份索引失败: {e}"}

    # 收集元数据
    corpus_hashes = _get_corpus_hashes(corpus_dir)
    index_metrics = _get_index_metrics(version_dir)

    version_entry = {
        "version_id": version_id,
        "created_at": datetime.now().isoformat(),
        "operator": operator,
        "notes": notes,
        "corpus_hashes": corpus_hashes,
        "index_metrics": index_metrics,
        "index_path": str(version_dir),
    }

    # 保存到版本列表（头部插入）
    versions = get_kb_versions(limit=100)
    versions.insert(0, version_entry)
    # 保留最近 50 个版本
    versions = versions[:50]
    redis_client.set(KB_VERSION_KEY, json.dumps(versions, ensure_ascii=False))

    # 更新当前版本指针
    redis_client.set(KB_CURRENT_VERSION_KEY, version_id)

    # 审计日志
    log_admin_action("kb_version_create", operator, {
        "version_id": version_id,
        "notes": notes,
        "corpus_files": len(corpus_hashes),
    })

    return {"success": True, "version": version_entry}


def rollback_kb_version(version_id: str, operator: str = "admin") -> Dict[str, Any]:
    """
    回滚到指定版本：
    1. 找到版本对应的索引目录
    2. 复制回当前索引目录
    3. 更新当前版本指针
    """
    versions = get_kb_versions(limit=100)
    target = None
    for v in versions:
        if v.get("version_id") == version_id:
            target = v
            break

    if not target:
        return {"success": False, "error": f"版本 {version_id} 不存在"}

    version_dir = Path(target.get("index_path", ""))
    if not version_dir.exists():
        return {"success": False, "error": f"版本索引目录不存在: {version_dir}"}

    # 复制回当前目录
    try:
        if DEFAULT_INDEX_DIR.exists():
            shutil.rmtree(DEFAULT_INDEX_DIR)
        shutil.copytree(version_dir, DEFAULT_INDEX_DIR)
    except Exception as e:
        return {"success": False, "error": f"回滚索引失败: {e}"}

    # 更新当前版本指针
    redis_client.set(KB_CURRENT_VERSION_KEY, version_id)

    # 审计日志
    log_admin_action("kb_version_rollback", operator, {
        "version_id": version_id,
        "from_version": get_current_kb_version(),
    })

    return {"success": True, "version_id": version_id}


def delete_kb_version(version_id: str, operator: str = "admin") -> Dict[str, Any]:
    """删除指定版本（保留索引文件，仅从清单移除）"""
    versions = get_kb_versions(limit=100)
    new_versions = [v for v in versions if v.get("version_id") != version_id]

    if len(new_versions) == len(versions):
        return {"success": False, "error": f"版本 {version_id} 不存在"}

    redis_client.set(KB_VERSION_KEY, json.dumps(new_versions, ensure_ascii=False))

    log_admin_action("kb_version_delete", operator, {"version_id": version_id})

    return {"success": True}
