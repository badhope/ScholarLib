"""Public-facing privacy policy page.

GDPR Article 13 / 14 requires that data subjects be informed of the
controller's identity, the categories of data processed, the purposes
of processing, and the retention period before any personal data is
collected. We serve the policy as a small standalone HTML page so a
visitor without JavaScript still gets a readable document (the SPA
shell would render nothing).

Retention constants live in ``app.core.retention`` so this text and the
code cannot drift apart silently.
"""

from __future__ import annotations

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.retention import AUDIT_LOG_RETENTION_DAYS, USER_DELETION_GRACE_DAYS

router = APIRouter(tags=["public"])

CONTACT_EMAIL = "admin@argjiemi.cn"

PRIVACY_POLICY_MD = f"""\
# Rubbish 隐私政策

_最后更新：2026-10-22_

## 我们是谁

Rubbish（rubbish.argjiemi.cn）是一份开放获取学术期刊，由本站编辑部运营。
隐私相关事宜请联系 `{CONTACT_EMAIL}`。

## 我们收集哪些数据

注册账号时收集：

- 邮箱地址（用于登录与密码找回）。
- 用户名（公开显示的作者名）。
- 密码（以 bcrypt 哈希存储，我们无法看到明文）。
- 账号创建时间。

使用服务时还会收集：

- 你提交、评审或收藏的稿件与文献记录。
- 你填写的审稿意见与评分。
- 安全审计所需的 IP 地址与请求时间。
- 匿名页面访问记录：仅路径与来源页，不含 IP、User-Agent 或账号身份，用于统计内容阅读量，保留 90 天。
- Cookie：一个 HttpOnly 的登录刷新令牌，以及（如启用）CSRF 双提交 Cookie。

我们**不**收集：广告标识符、第三方追踪像素、生物识别数据、特殊类别个人数据。

## 用途

- 提供登录、投稿、评审、阅读等核心服务。
- 防止滥用（限流、暴力破解防护）。
- 记录账号操作审计日志，保留 {AUDIT_LOG_RETENTION_DAYS} 天。

## 保留期限

- 账号资料：直至你申请删除。
- 删除账号后：邮箱、用户名、密码、TOTP 密钥立即匿名化，数据行在
  **{USER_DELETION_GRACE_DAYS} 天宽限期**后彻底删除。
- 审计日志：**{AUDIT_LOG_RETENTION_DAYS} 天**。
- 备份：90 天内轮换删除。

## 你的权利

- 导出全部个人数据：`GET /api/users/me/export`。
- 注销账号：`DELETE /api/users/me`，{USER_DELETION_GRACE_DAYS} 天内可恢复。
- 关闭双因素认证：`POST /api/auth/2fa/disable`。
- 其他数据主体请求：发送邮件至 `{CONTACT_EMAIL}`，我们将在 30 天内答复。

## 我们如何保护数据

- 生产环境全站 HTTPS。
- 密码使用 bcrypt 加盐哈希。
- 访问令牌 15 分钟过期，可通过 token 版本号即时吊销。
- 刷新令牌每次使用都轮换，已消费的令牌重放会被拒绝。
- 支持 TOTP 双因素认证，建议所有账号开启。
- 代理层限流拦截暴力破解。
- 审计日志记录操作者、对象、动作与时间。

## 政策变更

重大变更会提前 14 天在站内公告。以上「最后更新」日期为准。
"""


def _inline(text: str) -> str:
    """Escape, then turn ``code`` spans and paired ``**`` into markup."""
    escaped = html.escape(text)
    parts = escaped.split("`")
    for i in range(1, len(parts), 2):
        parts[i] = f"<code>{parts[i]}</code>"
    escaped = "".join(parts)
    chunks = escaped.split("**")
    return "".join(
        f"<strong>{chunk}</strong>" if i % 2 else chunk for i, chunk in enumerate(chunks)
    )


def _render_html(markdown_text: str) -> str:
    """Render the policy as a minimal, dependency-free HTML page.

    The document is a fixed constant (no user input), so a hand-rolled
    heading/paragraph renderer is sufficient and keeps this route free of
    a markdown dependency.
    """
    body: list[str] = []
    in_list = False
    for raw in markdown_text.splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        if not line:
            continue
        if line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("_") and line.endswith("_"):
            body.append(f'<p class="muted">{_inline(line.strip("_"))}</p>')
        else:
            body.append(f"<p>{_inline(line)}</p>")
    if in_list:
        body.append("</ul>")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="index" />
<title>隐私政策 · Rubbish</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; background: #fbfaf6; color: #1b2233;
         font: 16px/1.75 -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 48px 20px 72px; }}
  h1 {{ font-size: 30px; margin: 0 0 4px; }}
  h2 {{ font-size: 19px; margin: 32px 0 8px; }}
  p, li {{ color: #333c4f; }}
  .muted {{ color: #6b7488; font-size: 14px; }}
  ul {{ padding-left: 22px; }}
  code {{ background: #efece3; border-radius: 4px; padding: 1px 5px; font-size: 13px; }}
  a {{ color: #33409b; }}
  footer {{ margin-top: 40px; border-top: 1px solid #dcd7c9; padding-top: 16px;
            font-size: 14px; color: #6b7488; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #12151c; color: #e8ecf5; }}
    p, li {{ color: #c4cbdb; }}
    code {{ background: #232a37; }}
    a {{ color: #9fb0ff; }}
    footer {{ border-color: #2a3140; color: #8b93a7; }}
  }}
</style>
</head>
<body>
<main>
{chr(10).join(body)}
<footer>© 2026 Rubbish · 开放获取期刊 · <a href="/">返回首页</a></footer>
</main>
</body>
</html>"""


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def get_privacy_policy() -> HTMLResponse:
    """Return the privacy policy as a standalone HTML page."""
    return HTMLResponse(_render_html(PRIVACY_POLICY_MD))
