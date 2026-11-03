// 外链协议白名单：作者可控的 external_url / download_url 渲染进 href 前
// 必须经过这里。只放行 http / https（http 放行是为了同源部署场景，如本地
// /uploads 托管的稿件文件），阻止 javascript: / data: 等存储型 XSS。
// 纯 SPA，无 SSR 顾虑；相对路径按当前 origin 解析后判断。

/**
 * 判断一个 URL 是否可安全用于 <a href> / iframe。
 *
 * 解析失败（无法 new URL）一律视为不安全。
 */
export function isSafeExternalUrl(url: string | null | undefined): boolean {
  if (!url) return false
  try {
    const u = new URL(url, window.location.origin)
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}

/**
 * 返回可安全渲染的 href：不安全时降级为 '#'（配合 title/aria-disabled 提示）。
 */
export function safeHref(url: string | null | undefined): string {
  return isSafeExternalUrl(url) ? (url as string) : '#'
}
