"""
知眠数据归档脚本
自动压缩 >90 天的日志文件到 archive/ 目录
建议通过 crontab 每天凌晨运行：0 3 * * * /home/ubuntu/venv/bin/python3 /home/ubuntu/anmian/backend/archive_logs.py
"""
import os
import json
import gzip
import shutil
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
LOG_DIR = BASE_DIR / "conversation_logs"
TRACK_DIR = BASE_DIR / "evaluation_tracking"
ARCHIVE_DIR = BASE_DIR / "archive"
ARCHIVE_DIR.mkdir(exist_ok=True)

RETENTION_DAYS = 90


def archive_directory(source_dir: Path, prefix: str):
    """归档某个目录下过期文件"""
    if not source_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    archived = 0

    for fpath in source_dir.iterdir():
        if not fpath.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
            if mtime < cutoff:
                # 按月归档到 gzip
                month_key = mtime.strftime("%Y%m")
                archive_name = f"{prefix}_{month_key}.jsonl.gz"
                archive_path = ARCHIVE_DIR / archive_name

                # 追加到 gzip 文件
                with gzip.open(archive_path, "at", encoding="utf-8") as af:
                    with open(fpath, "r", encoding="utf-8") as sf:
                        af.write(sf.read().strip() + "\n")

                # 删除原文件
                fpath.unlink()
                archived += 1
                print(f"[Archive] {fpath.name} -> {archive_name}")
        except Exception as e:
            print(f"[Archive] 跳过 {fpath.name}: {e}")

    return archived


def cleanup_old_archives(years: int = 2):
    """删除超过 N 年的归档文件"""
    if not ARCHIVE_DIR.exists():
        return
    cutoff = datetime.now() - timedelta(days=365 * years)
    removed = 0
    for fpath in ARCHIVE_DIR.iterdir():
        if not fpath.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
            if mtime < cutoff:
                fpath.unlink()
                removed += 1
                print(f"[Archive] 删除旧归档: {fpath.name}")
        except Exception as e:
            print(f"[Archive] 跳过删除 {fpath.name}: {e}")
    return removed


if __name__ == "__main__":
    print(f"[Archive] 开始归档，截止时间: {(datetime.now() - timedelta(days=RETENTION_DAYS)).date()}")
    c1 = archive_directory(LOG_DIR, "conversation_logs")
    c2 = archive_directory(TRACK_DIR, "evaluation_tracking")
    c3 = cleanup_old_archives(years=2)
    print(f"[Archive] 完成。归档会话日志: {c1}, 评估追踪: {c2}, 清理旧归档: {c3}")
