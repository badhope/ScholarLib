/**
 * 轻量双语壳层：仅覆盖导航、分组、页头与通用操作。
 *
 * 不假装“全站已英文化”——正文、栏目、稿件与后台表单仍是中文。
 * 这里的目标是让英文用户在首屏能看懂去哪里，不制造 70 个页面的
 * 半翻译状态。语言选择持久化到 localStorage。
 */
import { useEffect, useState } from 'react'

export type Lang = 'zh' | 'en'

const KEY = 'rubbish.lang'
const EVENT = 'rubbish:lang'

const NAV_EN: Record<string, string> = {
  '/': 'Home',
  '/papers': 'Papers',
  '/fun': 'Supplement',
  '/forum': 'Forum',
  '/me': 'Me',
  '/dashboard': 'Overview',
  '/submissions': 'My submissions',
  '/appeals': 'Appeals',
  '/library': 'Reading list',
  '/follows': 'Following',
  '/recommendations': 'For you',
  '/review/assignments': 'Review desk',
  '/ingest': 'Import',
  '/notifications': 'Notifications',
  '/sections': 'Sections',
  '/archive': 'Archive',
  '/about': 'About & metrics',
  '/guide': 'Submission guide',
  '/admin': 'Admin overview',
  '/admin/users': 'Users',
  '/admin/shop': 'R-coin shop',
  '/admin/claims': 'Claims',
  '/admin/role-applications': 'Role requests',
  '/admin/announcements': 'Announcements',
  '/admin/forum-boards': 'Forum boards',
  '/admin/reports': 'Reports',
  '/admin/volumes': 'Volumes',
  '/admin/issues': 'Issues',
  '/admin/releases': 'Release gate',
  '/admin/journal': 'Journal info',
  '/admin/settings': 'Journal settings',
  '/admin/audit-logs': 'Audit logs',
  '/admin/system-health': 'System health',
}

const GROUP_EN: Record<string, string> = {
  一级入口: 'Primary',
  我的工作: 'Workspace',
  期刊: 'Journal',
  站点管理: 'Site admin',
  总览: 'Overview',
  用户与权限: 'Users & access',
  内容与社区: 'Content & community',
  期刊与发布: 'Journal & release',
  系统与安全: 'System & security',
}

const TEXT_EN: Record<string, string> = {
  搜索: 'Search',
  登录: 'Sign in',
  注册: 'Join',
  个人中心: 'Profile',
  账号设置: 'Settings',
  审稿工作台: 'Review desk',
  主编工作台: 'Editor desk',
  退出登录: 'Sign out',
  展开侧边栏: 'Expand sidebar',
  收起侧边栏: 'Collapse sidebar',
  打开菜单: 'Open menu',
  关闭菜单: 'Close menu',
  账号菜单: 'Account menu',
  跳到主要内容: 'Skip to content',
}

export function getLang(): Lang {
  if (typeof window === 'undefined') return 'zh'
  return window.localStorage.getItem(KEY) === 'en' ? 'en' : 'zh'
}

export function setLang(lang: Lang): void {
  window.localStorage.setItem(KEY, lang)
  document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN'
  window.dispatchEvent(new CustomEvent(EVENT, { detail: lang }))
}

export function useLang(): Lang {
  const [lang, set] = useState<Lang>(getLang)
  useEffect(() => {
    const onChange = () => set(getLang())
    window.addEventListener(EVENT, onChange)
    return () => window.removeEventListener(EVENT, onChange)
  }, [])
  return lang
}

export function navLabel(to: string, zh: string, lang: Lang = getLang()): string {
  return lang === 'en' ? (NAV_EN[to] ?? zh) : zh
}

export function groupLabel(zh: string, lang: Lang = getLang()): string {
  return lang === 'en' ? (GROUP_EN[zh] ?? zh) : zh
}

export function text(key: string, lang: Lang = getLang()): string {
  return lang === 'en' ? (TEXT_EN[key] ?? key) : key
}
