# 知眠 HR 后台 (zhimian-hr-admin)

B2B 团队心理体检的客户端 — 给企业 HR 用的独立 Web 应用。

部署在 `https://sleepai.chat/hr-admin/`(Nginx 静态托管 `dist/`)。
跟 `web/`(个人版 sleepai.chat 主站)是**两个独立应用**,共用同一后端 API。

## 页面

| 路由 | 内容 |
|---|---|
| `/hr-admin/login` | 邮箱 + 验证码登录,验证后端 JWT 必须含 `role=hr_admin` |
| `/hr-admin/` | 总览:参与度 / 睡眠 / 焦虑 / worry / 危机一屏卡片 |
| `/hr-admin/teams` | 团队列表与成员数 |
| `/hr-admin/employees` | CSV 批量导入 + 邀请码生成 |
| `/hr-admin/reports` | 5 维度详细聚合报告 |
| `/hr-admin/settings` | 企业基本信息、席位使用、k-anonymity 守护说明 |

## 后端 API 依赖

- `POST /api/v1/auth/email/request` / `verify` — 邮箱验证码登录
- `GET /api/v1/auth/me` — 当前身份 + 企业归属
- `GET /api/v1/org/admin/teams` — 团队列表
- `GET /api/v1/org/admin/org_info` — 企业基本信息
- `POST /api/v1/org/admin/employees/import` — 批量导入员工
- `GET /api/v1/org/insights/{overview,sleep,anxiety,worry_domains,crisis,engagement}` —
  6 个聚合洞察,全部 k≥5 守护

所有 `/org/admin/*` 和 `/org/insights/*` 端点都需要 JWT 中 `role=hr_admin`。

## 本地开发

```bash
cd hr-admin
npm install
npm run dev    # http://localhost:3001/hr-admin/
```

开发时 `vite.config.ts` 把 `/api` 反代到 `https://sleepai.chat`,
所以本地直接拿生产数据(配合测试企业账号使用)。

## 构建 & 部署

```bash
npm run build
# 产物在 dist/。Nginx 配置:
# location /hr-admin/ {
#     alias /home/ubuntu/anmian/hr-admin-dist/;
#     try_files $uri $uri/ /hr-admin/index.html;
# }
```

## 关键设计约束

- **永远不传 user_id / openid 给前端**:所有 `/org/insights/*` 返回的字段都是聚合
  数字。`InsufficientNotice` 组件在 n < k_min 时拦截展示。
- **客户端不能指定 org_id**:后端从 JWT 取 `org_id`,query 参数被忽略。客户端只能
  传 `team_id` 钻取子集。
- **危机事件只数字**:`/org/insights/crisis` 返回 `{high, medium, low, total}`,
  绝不含 event_id / user_id / message。

## 给 HR 第一次开通的 SOP

1. 运营操作员 (`/api/v1/admin/org/create`) 创建企业 → org_id
2. 运营生成邀请码 (`/api/v1/admin/org/invite`) → 给到 HR
3. HR 用 `/auth/org/register`(直接在 web/ 上 register 或先 verify 再 join)→
   拿到带 org_id 的 JWT
4. 运营 `/api/v1/admin/org/grant_hr_admin` 把 HR 升级为 hr_admin
5. HR **重登一次**(/auth/email/verify 会带 role=hr_admin 重签 JWT)
6. HR 进 `/hr-admin/`,完成

## i18n

中英双语,所有 key 在 `src/locales/{zh,en}.json` 完全对齐。
LocalStorage key:`zhimian_hr_locale`,与 web/ (`zhimian_locale`) 完全独立。
