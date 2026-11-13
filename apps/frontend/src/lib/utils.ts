import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { AxiosError } from 'axios'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * 把外部传入的跳转地址收敛成"仅站内相对路径"。
 *
 * 背景：`?redirect=` 完全由 URL 控制，直接喂给 router 会造成开放重定向——
 * 攻击者推送 `/login?redirect=https://evil.example/phish`，受害者输入真实
 * 凭据后"登录成功"被静默送到钓鱼站，可信度极高。
 *
 * 规则：必须以单个 `/` 开头且第二个字符不是 `/` 或 `\`（否则 `//evil.com`
 * 会被浏览器当作协议相对 URL、`/\evil.com` 在部分浏览器同样外跳）。
 * 其余一律回退到 fallback。
 */
export function safeInternalPath(
  redirect: string | null | undefined,
  fallback = '/dashboard',
): string {
  if (!redirect) return fallback
  if (!redirect.startsWith('/')) return fallback
  if (redirect.length > 1 && (redirect[1] === '/' || redirect[1] === '\\')) {
    return fallback
  }
  return redirect
}

/**
 * 后端返回的时间是原始 ISO 字符串（如 `2026-09-14T14:21:51.181237Z`），
 * 直接渲染既难读又会撑破卡片布局，统一格式化后再展示。
 * 空值 / 非法值回退到 fallback，避免页面出现 "Invalid Date"。
 */
export function formatDateTime(iso: string | null | undefined, fallback = '—'): string {
  if (!iso) return fallback
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleString()
}

// 后端 detail 目前是英文（FastAPI/OAuth2 惯例），界面上直接抛出会让中文用户
// 看到 "Invalid credentials" 这类原文。此处集中映射常见认证/权限/校验错误，
// 未命中的 detail 原样返回（新增后端错误时可在下表补充）。
const BACKEND_ERROR_ZH: Record<string, string> = {
  'Invalid credentials': '用户名或密码不正确',
  'User account is disabled': '账号已被停用，请联系编辑部',
  'Invalid or expired two-factor session; log in again': '验证会话已过期，请重新登录',
  'Invalid or expired refresh token': '登录状态已过期，请重新登录',
  'Not authenticated': '请先登录',
  'Insufficient permissions': '没有权限执行此操作',
  'Resource not found': '内容不存在或已被删除',
  'Submission not found': '投稿不存在或已被删除',
  'This resource has no downloadable file': '该内容没有可下载的文件',
  'This resource has no online manuscript': '该内容没有在线全文',
  'Only the submitter can upload files': '只有投稿作者本人可以上传文件',
  'File exceeds maximum size': '文件超过大小限制',
  'Unsupported file type': '不支持该文件类型',
  'Comment not found': '评论不存在',
  'Reading list not found': '阅读列表不存在',
  'Assignment not found': '审稿任务不存在',
  'Email already registered': '该邮箱已注册',
  'Username already taken': '该用户名已被占用',
  'Slug already taken in this tenant': '该短链接已被占用',
  'DOI already exists in this catalog': '该 DOI 已存在',
}

export function translateBackendError(detail: string): string {
  return BACKEND_ERROR_ZH[detail] ?? detail
}

// Single source of truth for converting a thrown value (axios + unknown)
// into a user-facing toast message. Used by every mutation catch block.
export function extractError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return translateBackendError(detail)
    // 等级门禁等结构化错误：{ code, required_level, current_level, message }
    // 直接把 message 抛给用户；没有 message 时退回固定文案。
    if (detail && typeof detail === 'object') {
      const message = (detail as { message?: unknown }).message
      if (typeof message === 'string' && message) return message
    }
  }
  return fallback
}

// Parse a comma-separated list field (authors / tags / keywords / jel_codes)
// into a trimmed, empty-filtered string array. Replaces the repeated inline
// `.split(',').map(s => s.trim()).filter(Boolean)` pattern across the app.
export function parseListField(s: string): string[] {
  return s
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
}

// 作者名展示统一入口：
// 1) 把 "Last, First" 规范成 "First Last"（BibTeX/RIS 导入常带逗号格式，
//    直接 join 会让人误以为拆成多个作者）；
// 2) 超过 2 位作者时截断为 "前两位 et al."。
//
// P0 兜底：数据侧会清掉姓名含 bigbad 的脏数据，但缓存/旧接口可能还带出来，
// 展示层统一过滤，防止脏作者名漏到读者视野。
export function sanitizeAuthors(authors: string[] | null | undefined): string[] {
  if (!authors) return []
  return authors.filter((a) => {
    if (!a) return false
    // 大小写不敏感匹配 "bigbad"，避免 BigBad / BIGBAD 变体漏网
    return !a.toLowerCase().includes('bigbad')
  })
}

export function formatAuthors(authors: string[], limit = 2): string {
  const names = sanitizeAuthors(authors).map((a) => {
    const parts = a
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    return parts.length >= 2 ? `${parts.slice(1).join(' ')} ${parts[0]}` : a
  })
  if (names.length > limit) {
    return `${names.slice(0, limit).join('、')} 等`
  }
  return names.join('、')
}

// Trigger a browser download from a Blob response (export / file download).
// Filename is parsed from Content-Disposition, falling back to fallbackName.
// Deduplicates the blob-download logic previously hand-rolled in
// exportResources() and downloadSubmissionFile().
export function downloadBlob(data: Blob, disposition: string, fallbackName: string): void {
  // RFC 5987 takes precedence: filename*=UTF-8''... carries Chinese titles.
  // Without this, the ASCII fallback (`filename="..."`) wins and the user
  // receives a file named with underscores instead of the article title.
  const encoded = /filename\*=UTF-8''([^;\n]+)/i.exec(disposition)
  let filename: string
  if (encoded?.[1]) {
    try {
      filename = decodeURIComponent(encoded[1].trim())
    } catch {
      filename = fallbackName
    }
  } else {
    const match = /filename="?([^";]+)"?/.exec(disposition)
    filename = match?.[1] ?? fallbackName
  }
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  // 移动端浏览器（尤其 iOS/微信）从点击到真正开始接收 blob 有延迟；
  // 立刻 revoke 会让下载在开始前就被取消。移动端优先新标签打开 PDF，
  // 让系统阅读器接管，用户可以直接“存储到文件”或转发。
  const isMobile = /Android|iPhone|iPad|iPod|HarmonyOS|Mobile/i.test(navigator.userAgent)
  if (isMobile) a.target = '_blank'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 120_000)
}

// Backend list endpoints return a bare array with no meta; the total page
// count is inferred from whether the current page came back full. Extracted
// from the identical logic in admin/users.tsx and admin/audit-logs.tsx.
export function inferTotalPagesFromFullPage(
  items: unknown[],
  pageSize: number,
  page: number,
): number {
  return items.length >= pageSize ? page + 1 : page
}
