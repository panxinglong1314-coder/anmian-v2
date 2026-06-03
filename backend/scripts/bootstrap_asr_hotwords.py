#!/usr/bin/env python3
"""
一键创建腾讯云 ASR 热词表(中英混读优化)。

用法:
  # 服务器上跑(从 backend/.env 读凭证):
  cd /home/ubuntu/anmian/backend && python3 scripts/bootstrap_asr_hotwords.py

  # 本地跑(显式传凭证):
  python3 backend/scripts/bootstrap_asr_hotwords.py \
    --secret-id $TENCENT_SECRET_ID \
    --secret-key $TENCENT_SECRET_KEY \
    --name "zhimian-mixed-zh-en"

成功后会打印 HotwordId, 把它填到 backend/.env:
  TENCENT_ASR_HOTWORD_ID=<打印出来的 ID>
然后 systemctl restart anmian-backend 即生效。
"""
import argparse
import sys
import os
from pathlib import Path

# 让脚本能从 backend/ 启动也能从仓库根启动
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_hotwords(path: Path) -> str:
    """读 asr_hotwords_zhimian.txt → 腾讯云要的格式 (word|weight 一行一个)。"""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "|" not in s:
            continue
        lines.append(s)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret-id", default=os.getenv("TENCENTCLOUD_SECRET_ID", ""))
    ap.add_argument("--secret-key", default=os.getenv("TENCENTCLOUD_SECRET_KEY", ""))
    ap.add_argument("--name", default="zhimian-mixed-zh-en")
    ap.add_argument("--file", default=str(ROOT / "scripts" / "asr_hotwords_zhimian.txt"))
    args = ap.parse_args()

    # 服务器场景:从 .env 兜底
    if not args.secret_id:
        try:
            from infra.settings import settings
            args.secret_id = settings.tencentcloud_secret_id
            args.secret_key = settings.tencentcloud_secret_key
        except Exception:
            pass

    if not args.secret_id or not args.secret_key:
        print("ERROR: 缺少腾讯云凭证。--secret-id / --secret-key 或 .env", file=sys.stderr)
        sys.exit(2)

    word_text = load_hotwords(Path(args.file))
    if not word_text:
        print(f"ERROR: {args.file} 没有可用热词", file=sys.stderr)
        sys.exit(2)
    print(f"读取热词文件: {len(word_text.splitlines())} 词")

    try:
        from tencentcloud.common import credential
        from tencentcloud.asr.v20190614 import asr_client, models
    except ImportError:
        print("ERROR: pip install tencentcloud-sdk-python", file=sys.stderr)
        sys.exit(2)

    cred = credential.Credential(args.secret_id, args.secret_key)
    client = asr_client.AsrClient(cred, "")

    # 腾讯云 ASR 热词表创建 API: CreateAsrVocab
    req = models.CreateAsrVocabRequest()
    req.Name = args.name
    req.Description = "知眠中英混读优化(自动生成)"
    # WordWeights 是结构化列表:[{Word, Weight}, ...]
    word_weights = []
    for line in word_text.splitlines():
        parts = line.split("|")
        if len(parts) != 2: continue
        try:
            ww = models.HotWord()
            ww.Word = parts[0].strip()
            ww.Weight = int(parts[1].strip())
            word_weights.append(ww)
        except (ValueError, AttributeError):
            continue
    req.WordWeights = word_weights

    print(f"调用 CreateAsrVocab: name={args.name}, words={len(word_weights)}")
    try:
        resp = client.CreateAsrVocab(req)
    except Exception as e:
        print(f"\n❌ 创建失败: {e}")
        print("\n常见原因:")
        print(" - 子账号无 ASR 权限 → 控制台 → 访问管理 → 给 QcloudAAIAsrFullAccess 策略")
        print(" - 热词数超额 (单表上限 128) → 拆成多张表")
        print(" - 已存在同名热词表 → 改 --name 或先去控制台删")
        sys.exit(1)

    print("\n✅ 成功!")
    print(f"   VocabId: {resp.VocabId}")
    print(f"\n下一步:")
    print(f"   1. 编辑 backend/.env, 加一行:")
    print(f"      TENCENT_ASR_HOTWORD_ID={resp.VocabId}")
    print(f"   2. sudo systemctl restart anmian-backend")
    print(f"   3. 验证: 跑一段含 'deadline' 的语音, 看 transcript 是否准确")


if __name__ == "__main__":
    main()
