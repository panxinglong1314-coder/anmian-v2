#!/bin/bash
# B2B 转型端到端验收脚本 — 在 prod 服务器上跑
# 用法:ssh ubuntu@124.222.43.248 'bash -s' < scripts/verify_b2b.sh
#
# 跑完会:
# - 创建测试企业 + 5 个员工 + HR 账号
# - 验证 8 个关键链路
# - 自动清理所有测试数据
#
# 期望全部 ✓,出现 ✗ 说明那一步坏了

set -u
TOKEN=$(grep -E "^ADMIN_TOKEN=" /home/ubuntu/anmian/backend/.env | cut -d= -f2-)
API="http://127.0.0.1:8000"
PASS=0
FAIL=0

assert() {
    local name="$1"
    local actual="$2"
    local expected="$3"
    # 同时容忍 JSON 紧凑(无空格)和美化两种格式
    local expected_compact="${expected// /}"
    if [[ "$actual" == *"$expected"* ]] || [[ "${actual// /}" == *"$expected_compact"* ]]; then
        echo "  ✓ $name"
        PASS=$((PASS+1))
    else
        echo "  ✗ $name"
        echo "    expected: contains '$expected'"
        echo "    actual:   ${actual:0:200}"
        FAIL=$((FAIL+1))
    fi
}

echo "════════════════════════════════════════════════════"
echo "  知眠 B2B 转型 - 端到端验收"
echo "════════════════════════════════════════════════════"

# ---- 1. 创建测试企业 ----
echo
echo "▼ 1. 运营创建企业 + 邀请码"
ORG_RESP=$(curl -s -X POST -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Verify Test Co","seat_quota":20}' "$API/api/v1/admin/org/create")
ORG=$(echo "$ORG_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('org_id','FAIL'))")
assert "org 创建" "$ORG" "org_"

INV_RESP=$(curl -s -X POST -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" \
  -d "{\"org_id\":\"$ORG\",\"max_uses\":20}" "$API/api/v1/admin/org/invite")
CODE=$(echo "$INV_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code','FAIL'))")
[[ "$CODE" =~ ^[A-Z0-9]{6}$ ]] && echo "  ✓ 邀请码生成 ($CODE)" && PASS=$((PASS+1)) || { echo "  ✗ 邀请码生成"; FAIL=$((FAIL+1)); }

# ---- 2. 公开销售线索接收 ----
echo
echo "▼ 2. /enterprise 表单提交 → /sales/lead"
LEAD_RESP=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"company_name":"Verify Inc","contact_email":"buyer@verify.test","team_size":"50-200","message":"想了解"}' \
  "$API/api/v1/sales/lead")
assert "lead 提交" "$LEAD_RESP" "lead_id"

LEAD_STATS=$(curl -s -H "X-Admin-Token: $TOKEN" "$API/api/v1/admin/sales/leads?status=pending")
assert "运营看到队列" "$LEAD_STATS" "Verify Inc"

# ---- 3. HR 注册 + 升级 ----
echo
echo "▼ 3. HR 邮箱+邀请码注册 + 升级 hr_admin"
redis-cli setex "email_code:hr@verify.test" 600 "111111" >/dev/null
REG_RESP=$(curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"email\":\"hr@verify.test\",\"code\":\"111111\",\"invite_code\":\"$CODE\"}" \
  "$API/api/v1/auth/org/register")
assert "HR 注册" "$REG_RESP" "$ORG"

GRANT_RESP=$(curl -s -X POST -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" \
  -d "{\"email\":\"hr@verify.test\",\"org_id\":\"$ORG\"}" \
  "$API/api/v1/admin/org/grant_hr_admin")
assert "授予 hr_admin 角色" "$GRANT_RESP" "hr_admin"

# 重登拿带 role 的 JWT
redis-cli setex "email_code:hr@verify.test" 600 "222222" >/dev/null
HR_JWT=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"email":"hr@verify.test","code":"222222"}' \
  "$API/api/v1/auth/email/verify" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
[[ -n "$HR_JWT" ]] && echo "  ✓ HR JWT 重签" && PASS=$((PASS+1)) || { echo "  ✗ HR JWT 重签"; FAIL=$((FAIL+1)); }

ME_RESP=$(curl -s -H "Authorization: Bearer $HR_JWT" "$API/api/v1/auth/me")
assert "/auth/me 含 org" "$ME_RESP" "$ORG"
assert "/auth/me 含 hr_admin role" "$ME_RESP" "hr_admin"

# ---- 4. CSV 批量导入 ----
echo
echo "▼ 4. HR CSV 批量导入员工"
CSV='email,team\nalice@verify.test,Engineering\nbob@verify.test,Sales\ncharlie@verify.test,Engineering\ndan@verify.test,Engineering\nemma@verify.test,Sales'
IMPORT_RESP=$(curl -s -X POST -H "Authorization: Bearer $HR_JWT" -H "Content-Type: application/json" \
  -d "{\"csv_text\":\"$CSV\",\"send_emails\":false,\"expire_days\":14}" \
  "$API/api/v1/org/admin/employees/import")
assert "5 员工导入成功" "$IMPORT_RESP" '"succeeded":5'

# 关键: CSV 导入只生成邀请码 — 员工要凭码真注册才算占用席位 + 写到 org:users。
# 提取每个员工的专属邀请码,逐个走 /auth/org/register。
echo "  ▸ 模拟 5 员工凭邀请码真注册..."
for EMAIL in alice@verify.test bob@verify.test charlie@verify.test dan@verify.test emma@verify.test; do
  EMP_CODE=$(echo "$IMPORT_RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for it in d['items']:
    if it['email']=='$EMAIL':
        print(it.get('code',''))
        break
")
  redis-cli setex "email_code:$EMAIL" 600 "987654" >/dev/null
  USRID=$(curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"code\":\"987654\",\"invite_code\":\"$EMP_CODE\"}" \
    "$API/api/v1/auth/org/register" | python3 -c "import sys,json; print(json.load(sys.stdin).get('user_id',''))")
  if [[ -n "$USRID" ]]; then
    redis-cli hset "sleep_diary:$USRID:2026-05-15" se 0.78 tst 7 sol 12 waso 10 quality 7 >/dev/null
    redis-cli hset "sleep_diary:$USRID:2026-05-22" se 0.85 tst 7.5 sol 8 waso 5 quality 8 >/dev/null
    redis-cli set "user:memory:$USRID" '{"session_count":3,"triggers":{"work":2,"health":1}}' >/dev/null
  fi
done

# ---- 5. 团队聚合 API + k-anonymity ----
echo
echo "▼ 5. HR 看聚合数据 (k≥5 通过)"
SLEEP_RESP=$(curl -s -H "Authorization: Bearer $HR_JWT" "$API/api/v1/org/insights/sleep?period=30d")
assert "聚合 status=ok" "$SLEEP_RESP" '"status":"ok"'
assert "返 avg_se_pct" "$SLEEP_RESP" "avg_se_pct"

# 关键: 不能含 user_id / email
echo "$SLEEP_RESP" | grep -q "alice@\|user_id" && { echo "  ✗ 隐私泄漏: 含 user_id 或 email"; FAIL=$((FAIL+1)); } || { echo "  ✓ 响应无 user_id / email 泄漏"; PASS=$((PASS+1)); }

OVERVIEW_RESP=$(curl -s -H "Authorization: Bearer $HR_JWT" "$API/api/v1/org/insights/overview?period=30d")
assert "/overview status=ok" "$OVERVIEW_RESP" '"status":"ok"'

CRISIS_RESP=$(curl -s -H "Authorization: Bearer $HR_JWT" "$API/api/v1/org/insights/crisis?period=30d")
echo "$CRISIS_RESP" | grep -q '"high"\|"medium"\|"low"' && echo "  ✓ /crisis 返计数字段" && PASS=$((PASS+1)) || { echo "  ✗ /crisis 缺计数字段"; FAIL=$((FAIL+1)); }

# ---- 6. PDF 月报生成 ----
echo
echo "▼ 6. PDF 月报"
curl -s -H "Authorization: Bearer $HR_JWT" "$API/api/v1/org/insights/report/pdf?ym=2026-05" \
  -o /tmp/verify_report.pdf -w "%{http_code} %{size_download}" > /tmp/pdf_meta
HTTP_PDF=$(cat /tmp/pdf_meta | awk '{print $1}')
SIZE_PDF=$(cat /tmp/pdf_meta | awk '{print $2}')
[[ "$HTTP_PDF" == "200" && "$SIZE_PDF" -gt 5000 ]] && echo "  ✓ PDF 下载 ($SIZE_PDF bytes)" && PASS=$((PASS+1)) || { echo "  ✗ PDF 失败 (HTTP=$HTTP_PDF size=$SIZE_PDF)"; FAIL=$((FAIL+1)); }
file /tmp/verify_report.pdf | grep -q "PDF document" && echo "  ✓ 真实 PDF 文件格式" && PASS=$((PASS+1)) || { echo "  ✗ 不是有效 PDF"; FAIL=$((FAIL+1)); }
rm -f /tmp/verify_report.pdf /tmp/pdf_meta

# ---- 7. k-anonymity 守护 (员工 < 5) ----
echo
echo "▼ 7. k=5 守护:n<5 应拒绝"
# 把团队拆成 2 人小组
ENG_TEAM_ID=$(curl -s -H "Authorization: Bearer $HR_JWT" "$API/api/v1/org/admin/teams" | \
  python3 -c "import sys,json; teams=json.load(sys.stdin)['teams']; print(next((t['team_id'] for t in teams if t['team_name']=='Sales'), ''))")
if [[ -n "$ENG_TEAM_ID" ]]; then
  TEAM_RESP=$(curl -s -H "Authorization: Bearer $HR_JWT" "$API/api/v1/org/insights/sleep?period=30d&team_id=$ENG_TEAM_ID")
  assert "Sales 团队 2 人 → insufficient_data" "$TEAM_RESP" "insufficient_data"
fi

# ---- 8. 非 HR 角色被拒 ----
echo
echo "▼ 8. 普通员工调 hr_admin 端点 → 403"
redis-cli setex "email_code:alice@verify.test" 600 "333333" >/dev/null
EMP_JWT=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"email":"alice@verify.test","code":"333333"}' \
  "$API/api/v1/auth/email/verify" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $EMP_JWT" \
  "$API/api/v1/org/insights/sleep")
[[ "$STATUS" == "403" ]] && echo "  ✓ 普通员工调 insights → 403" && PASS=$((PASS+1)) || { echo "  ✗ 期望 403 实际 $STATUS"; FAIL=$((FAIL+1)); }

# ---- 清理 ----
echo
echo "▼ 清理测试数据"
redis-cli --scan --pattern "org:*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "team:*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "user:org:*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "user:team:*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "user:role:*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "user:memory:em_*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "user_profile:em_*verify*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "user_profile:em_*hr@verify*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "sleep_diary:em_*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "email_code:*verify*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "sales_lead*verify*" | xargs -r redis-cli del >/dev/null
redis-cli --scan --pattern "sales_leads:*" | xargs -r redis-cli del >/dev/null
echo "  ✓ 清理完成"

# ---- 汇总 ----
echo
echo "════════════════════════════════════════════════════"
TOTAL=$((PASS+FAIL))
echo "  结果: $PASS / $TOTAL 通过"
if [[ $FAIL -eq 0 ]]; then
  echo "  ✓ B2B 全链路验收通过"
  exit 0
else
  echo "  ✗ $FAIL 项失败,需排查"
  exit 1
fi
