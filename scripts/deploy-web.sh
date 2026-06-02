#!/bin/bash
# 完整部署 web/ (sleepai.chat 个人版 SPA) 到 prod
# 永远完整 tar 部署,绝不单文件 scp(避免 index.html 和 assets hash 不一致)
#
# 用法: bash scripts/deploy-web.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/web"

echo "▼ 1. Build web/"
npm run build 2>&1 | tail -3

echo
echo "▼ 2. Tar dist/"
TAR=/tmp/web-dist-$(date +%s).tar.gz
tar czf "$TAR" -C dist . 2>&1 | tail -1
echo "  $(ls -lh $TAR | awk '{print $5}') tar"

echo
echo "▼ 3. scp to server"
scp -i ~/.ssh/id_ed25519 "$TAR" ubuntu@124.222.43.248:/tmp/web-dist-new.tar.gz >/dev/null

echo
echo "▼ 4. 部署(原子替换,带备份)"
ssh -i ~/.ssh/id_ed25519 ubuntu@124.222.43.248 'bash -s' << 'REMOTE'
set -e
echo "  备份当前版本..."
sudo cp -r /home/ubuntu/anmian/web_dist /home/ubuntu/anmian/web_dist.bak_$(date +%s) 2>&1 | tail -1
echo "  保留媒体文件(*.mp4 / *.webm) 避免覆盖手动上传的大文件..."
sudo mkdir -p /tmp/web-media-preserve
sudo find /home/ubuntu/anmian/web_dist -maxdepth 1 -type f \( -name "*.mp4" -o -name "*.webm" \) -exec mv {} /tmp/web-media-preserve/ \; 2>/dev/null || true
echo "  清空旧 + 解压新..."
sudo rm -rf /home/ubuntu/anmian/web_dist/*
sudo tar xzf /tmp/web-dist-new.tar.gz -C /home/ubuntu/anmian/web_dist/
echo "  恢复媒体文件..."
sudo find /tmp/web-media-preserve -type f -exec mv {} /home/ubuntu/anmian/web_dist/ \; 2>/dev/null || true
sudo rmdir /tmp/web-media-preserve 2>/dev/null || true
sudo chown -R ubuntu:ubuntu /home/ubuntu/anmian/web_dist
echo "  清理临时文件..."
rm /tmp/web-dist-new.tar.gz
echo "  当前 index.html refs:"
grep -oE 'index-[A-Za-z0-9_-]+\.(js|css)' /home/ubuntu/anmian/web_dist/index.html
echo "  assets 存在:"
ls /home/ubuntu/anmian/web_dist/assets/ | grep -E '^index' | head -3
REMOTE

echo
echo "▼ 5. 外网验证"
HTML=$(/usr/bin/curl -s -m 5 https://www.sleepai.chat/)
JS=$(echo "$HTML" | /usr/bin/grep -oE "/assets/index-[A-Za-z0-9_-]+\.js" | head -1)
CSS=$(echo "$HTML" | /usr/bin/grep -oE "/assets/index-[A-Za-z0-9_-]+\.css" | head -1)
js_meta=$(/usr/bin/curl -s -m 5 "https://www.sleepai.chat$JS" -o /dev/null -w "%{http_code}")
css_meta=$(/usr/bin/curl -s -m 5 "https://www.sleepai.chat$CSS" -o /dev/null -w "%{http_code}")
if [[ "$js_meta" == "200" && "$css_meta" == "200" ]]; then
  echo "  ✓ Deploy OK"
  echo "    JS  $JS -> $js_meta"
  echo "    CSS $CSS -> $css_meta"
  rm -f "$TAR"
else
  echo "  ✗ Deploy 异常 (JS=$js_meta CSS=$css_meta),tar 保留于 $TAR"
  exit 1
fi
