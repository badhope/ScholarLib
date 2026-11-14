"""Transactional email templates (plain text + HTML).

Every template returns ``(subject, text, html)``. The HTML shell is an
inline-styled editorial card (no external assets — email clients block
them), matching the site's paper/ink palette.

Placeholders are passed as keyword arguments; missing keys raise KeyError
at build time (fail fast in tests rather than sending "{{link}}").
"""

from __future__ import annotations

from html import escape

from app.core.config import settings

INK = "#1b2430"
MUTED = "#5b6b7c"
ACCENT = "#2c5aa0"
PAPER = "#f7f6f3"
LINE = "#e3e0d8"


def _shell(title: str, body_html: str, footer_note: str = "") -> str:
    site = escape(settings.site_name)
    base = settings.frontend_base_url.rstrip("/")
    return f"""\
<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 12px;background:{PAPER};font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#fff;border:1px solid {LINE};border-radius:10px;">
    <tr><td style="padding:22px 26px 6px;">
      <div style="font-size:20px;font-weight:700;color:{INK};letter-spacing:.5px;">{site}</div>
      <div style="margin-top:4px;font-size:12px;color:{MUTED};">开放获取学术期刊 · Open Access Journal</div>
    </td></tr>
    <tr><td style="padding:14px 26px 4px;">
      <h1 style="margin:0 0 12px;font-size:17px;line-height:1.5;color:{INK};">{escape(title)}</h1>
      <div style="font-size:14px;line-height:1.9;color:{INK};">{body_html}</div>
    </td></tr>
    <tr><td style="padding:18px 26px 22px;">
      <div style="border-top:1px solid {LINE};padding-top:14px;font-size:12px;color:{MUTED};line-height:1.7;">
        {footer_note or "本邮件由 Rubbish 编辑部系统自动发送，请勿直接回复。"}<br>
        <a href="{escape(base)}" style="color:{ACCENT};text-decoration:none;">{escape(base or site)}</a>
        · 官方读者一群：1084870548<br>
        <span style="color:{MUTED};">防钓鱼提示：本刊官方域名只有一个（rubbish.argjiemi.cn），
        其他域名发来的"Rubbish"邮件均非官方；官方邮件不会索要你的密码。</span>
      </div>
    </td></tr>
  </table>
</body></html>"""


def _button(label: str, href: str) -> str:
    return (
        f'<p style="margin:18px 0;"><a href="{escape(href)}" '
        f'style="display:inline-block;background:{ACCENT};color:#fff;text-decoration:none;'
        f'padding:10px 20px;border-radius:6px;font-size:14px;">{escape(label)}</a></p>'
        f'<p style="margin:0;font-size:12px;color:{MUTED};word-break:break-all;">'
        f"若按钮无法点击，请复制此链接到浏览器：<br>{escape(href)}</p>"
    )


def verify_email(username: str, link: str, expire_hours: int) -> tuple[str, str, str]:
    subject = f"验证你的 {settings.site_name} 邮箱"
    text = (
        f"你好，{username}：\n\n"
        f"感谢注册 {settings.site_name}。请打开以下链接完成邮箱验证：\n{link}\n\n"
        f"链接 {expire_hours} 小时内有效。若你不是本人操作，请忽略本邮件。\n"
    )
    html = _shell(
        "验证你的邮箱地址",
        f"<p>你好，{escape(username)}：</p>"
        f"<p>感谢注册 {escape(settings.site_name)}。点击下方按钮完成邮箱验证：</p>"
        + _button("验证邮箱", link)
        + f'<p style="margin-top:16px;font-size:12px;color:{MUTED};">'
        f"链接 {expire_hours} 小时内有效。若你不是本人操作，请忽略本邮件。</p>",
    )
    return subject, text, html


def reset_password(username: str, link: str, expire_minutes: int) -> tuple[str, str, str]:
    subject = f"重置你的 {settings.site_name} 密码"
    text = (
        f"你好，{username}：\n\n"
        f"我们收到了重置密码的请求。请打开以下链接设置新密码：\n{link}\n\n"
        f"链接 {expire_minutes} 分钟内有效。若你不是本人操作，请忽略本邮件，"
        f"你的密码不会改变。\n"
    )
    html = _shell(
        "重置密码",
        f"<p>你好，{escape(username)}：</p>"
        "<p>我们收到了重置密码的请求。点击下方按钮设置新密码：</p>"
        + _button("设置新密码", link)
        + f'<p style="margin-top:16px;font-size:12px;color:{MUTED};">'
        f"链接 {expire_minutes} 分钟内有效。若你不是本人操作，请忽略本邮件——"
        "你的密码不会改变。</p>",
    )
    return subject, text, html


def email_login_code(code: str, expire_minutes: int) -> tuple[str, str, str]:
    """邮箱验证码登录邮件。

    正文只放码不放链接：码登录的用户场景往往是"手边没有密码管理器"，
    直接可读可输入比"点链接回调 App"更符合预期。文案刻意说明"不是你
    请求的可以忽略"，与防钓鱼页脚呼应。
    """
    subject = f"【{settings.site_name}】登录验证码 {code}（{expire_minutes} 分钟内有效）"
    text = (
        f"你的登录验证码是：{code}\n"
        "\n"
        f"{expire_minutes} 分钟内有效，仅可使用一次。\n"
        "如果不是你在请求登录，请忽略本邮件——验证码作废不会影响你的账号。\n"
        "本邮件由 Rubbish 编辑部系统发送（rubbish.argjiemi.cn）。"
    )
    body_html = (
        f'<p style="margin:0 0 14px;">你正在登录 <strong>{escape(settings.site_name)}</strong>。'
        f"本次登录验证码为：</p>"
        f'<div style="margin:0 0 16px;padding:14px 20px;background:{PAPER};border:1px dashed {ACCENT};'
        f"border-radius:8px;font-size:28px;font-weight:700;letter-spacing:8px;color:{INK};"
        f'text-align:center;">{escape(code)}</div>'
        f'<p style="margin:0 0 8px;font-size:13px;color:{MUTED};">'
        f"{expire_minutes} 分钟内有效，仅可使用一次。请勿把验证码告诉任何人——"
        f"编辑部工作人员不会向你索要验证码。</p>"
    )
    return subject, text, _shell(title="登录验证码", body_html=body_html)


def duplicate_registration(username: str) -> tuple[str, str, str]:
    subject = f"{settings.site_name}：有人尝试用你的邮箱注册"
    text = (
        f"你好，{username}：\n\n"
        "我们注意到有人使用你的邮箱地址尝试注册新账号。\n\n"
        "如果这是你本人操作，可以忽略本邮件，你的现有账号不受影响。\n"
        "如果不是你本人操作，请考虑修改密码并联系编辑部。\n"
    )
    html = _shell(
        "有人尝试用你的邮箱注册",
        f"<p>你好，{escape(username)}：</p>"
        "<p>我们注意到有人使用你的邮箱地址尝试注册新账号。</p>"
        "<p>如果这是你本人操作，可以忽略本邮件，你的现有账号不受影响。<br>"
        "如果不是你本人操作，请考虑修改密码并联系编辑部。</p>",
    )
    return subject, text, html


def account_created(
    username: str, role_label: str, link: str, note: str = ""
) -> tuple[str, str, str]:
    """Invitation for an account created by an editor (no self-registration)."""
    subject = f"{settings.site_name}：你的编辑部账号已创建"
    note_text = f"\n编辑留言：{note}\n" if note else ""
    note_html = (
        f'<div style="margin:14px 0;padding:10px 14px;background:{PAPER};'
        f"border-left:3px solid {ACCENT};font-size:13px;color:{INK};"
        f'white-space:pre-wrap;">{escape(note)}</div>'
        if note
        else ""
    )
    text = (
        f"你好，{username}：\n\n"
        f"编辑部已为你创建 {settings.site_name} 账号，角色：{role_label}。\n"
        f"{note_text}"
        f"请打开以下页面，使用邮箱验证码登录并设置个人资料：\n{link}\n\n"
        "登录时选择「邮箱验证码登录」，验证码会发送到本邮箱。\n"
        "如果这不是你本人预期的安排，请直接回复编辑部或忽略本邮件。\n"
    )
    html = _shell(
        "你的编辑部账号已创建",
        f"<p>你好，{escape(username)}：</p>"
        f"<p>编辑部已为你创建 <strong>{escape(settings.site_name)}</strong> 账号，"
        f"角色：<strong>{escape(role_label)}</strong>。</p>"
        + (f"<p>编辑留言：</p>{note_html}" if note else "")
        + "<p>请使用邮箱验证码登录并设置个人资料：</p>"
        + _button("登录并设置", link)
        + '<p style="margin-top:16px;font-size:12px;color:'
        + MUTED
        + ';">登录时选择「邮箱验证码登录」，验证码会发送到本邮箱。'
        "如果这不是你本人预期的安排，请直接回复编辑部或忽略本邮件。</p>",
    )
    return subject, text, html


def review_assigned(
    reviewer: str, paper_title: str, link: str, due_days: int
) -> tuple[str, str, str]:
    """Assign notification to a reviewer."""
    subject = f"{settings.site_name}：有一篇稿件等待你评审"
    text = (
        f"你好，{reviewer}：\n\n"
        f"你被指派评审稿件《{paper_title}》。\n"
        f"请打开以下链接查看稿件（双盲，作者身份对你匿名）：\n{link}\n\n"
        f"请在 {due_days} 天内完成评审；如无法评审，请在页面中选择拒绝，"
        "编辑会改派其他审稿人。\n"
    )
    html = _shell(
        "有一篇稿件等待你评审",
        f"<p>你好，{escape(reviewer)}：</p>"
        f"<p>你被指派评审稿件《{escape(paper_title)}》。</p>"
        "<p>请查看稿件（双盲评审，作者身份对你匿名）：</p>"
        + _button("进入审稿工作台", link)
        + f'<p style="margin-top:16px;font-size:12px;color:{MUTED};">'
        f"请在 {due_days} 天内完成评审；如无法评审，请在页面中选择拒绝，编辑会改派其他审稿人。</p>",
    )
    return subject, text, html


def review_reminder(
    reviewer: str, paper_title: str, link: str, days_pending: int
) -> tuple[str, str, str]:
    """Reminder for an assignment that has been waiting too long."""
    subject = f"{settings.site_name}：审稿提醒（已等待 {days_pending} 天）"
    text = (
        f"你好，{reviewer}：\n\n"
        f"你指派的稿件《{paper_title}》已等待 {days_pending} 天，尚未收到评审结果。\n"
        f"请打开以下链接继续：\n{link}\n\n"
        "如果时间不便，请在页面中选择拒绝，编辑会改派其他审稿人。\n"
    )
    html = _shell(
        f"审稿提醒（已等待 {days_pending} 天）",
        f"<p>你好，{escape(reviewer)}：</p>"
        f"<p>稿件《{escape(paper_title)}》已等待 <strong>{days_pending} 天</strong>，"
        "尚未收到你的评审结果。</p>"
        + _button("继续评审", link)
        + '<p style="margin-top:16px;font-size:12px;color:'
        + MUTED
        + ';">如果时间不便，请在页面中选择拒绝，编辑会改派其他审稿人。</p>',
    )
    return subject, text, html


def review_reminder_digest(
    reviewer: str, items: list[tuple[str, int]], link: str
) -> tuple[str, str, str]:
    """One digest email per reviewer, instead of one email per assignment.

    同一审稿人同时被指派多篇稿件时，逐篇发信会在几秒内塞满收件箱；
    合并成一封，既保留全部待办，也避免被判成骚扰邮件。
    """
    count = len(items)
    max_days = max((days for _, days in items), default=0)
    subject = f"{settings.site_name}：审稿提醒（{count} 篇待办，最久 {max_days} 天）"
    lines = "\n".join(f"- 《{title}》（已等待 {days} 天）" for title, days in items)
    text = (
        f"你好，{reviewer}：\n\n"
        f"你有 {count} 篇稿件等待评审：\n{lines}\n\n"
        f"请打开以下链接继续：\n{link}\n\n"
        "如果时间不便，请在页面中选择拒绝，编辑会改派其他审稿人。\n"
    )
    lis = "".join(
        f"<li>《{escape(title)}》已等待 <strong>{days} 天</strong></li>" for title, days in items
    )
    html = _shell(
        f"审稿提醒（{count} 篇待办）",
        f"<p>你好，{escape(reviewer)}：</p>"
        f"<p>你有 <strong>{count} 篇</strong>稿件等待评审：</p>"
        f"<ul>{lis}</ul>"
        + _button("进入审稿工作台", link)
        + '<p style="margin-top:16px;font-size:12px;color:'
        + MUTED
        + ';">如果时间不便，请在页面中选择拒绝，编辑会改派其他审稿人。</p>',
    )
    return subject, text, html


def decision_notice(
    author: str, paper_title: str, decision_label: str, note: str | None, link: str
) -> tuple[str, str, str]:
    """Decision notification to the author."""
    subject = f"{settings.site_name}：你的稿件有了处理结果（{decision_label}）"
    note_html = (
        f'<div style="margin:14px 0;padding:10px 14px;background:{PAPER};border-left:3px solid {ACCENT};'
        f'font-size:13px;color:{INK};white-space:pre-wrap;">{escape(note)}</div>'
        if note
        else ""
    )
    text = (
        f"你好，{author}：\n\n"
        f"你的稿件《{paper_title}》已完成评审，结果为：{decision_label}。\n"
        + (f"\n编辑意见：\n{note}\n" if note else "")
        + f"\n查看详情与后续操作：\n{link}\n"
    )
    html = _shell(
        f"稿件处理结果：{decision_label}",
        f"<p>你好，{escape(author)}：</p>"
        f"<p>你的稿件《{escape(paper_title)}》已完成评审，结果为 "
        f"<strong>{escape(decision_label)}</strong>。</p>"
        + (f"<p>编辑意见：</p>{note_html}" if note else "")
        + _button("查看稿件详情", link),
    )
    return subject, text, html
