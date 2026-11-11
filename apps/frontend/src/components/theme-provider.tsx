import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

// 主题切换的极简自研实现，替代 next-themes。
//
// 背景：next-themes 0.4.6 的 ThemeProvider 内部无条件渲染一个 inline
// <script>（其内部 ThemeScript 组件，用于 SSR 前应用主题）。在纯 client-render
// 的 Vite SPA 里这个 script 永远不会执行（React 19.3 起还会在 dev 下告警
// "Encountered a script tag while rendering React component"），且本仓库
// index.html 的 CSP script-src 'self' 会直接拦截 inline script，线上同样报
// CSP violation。首屏防闪烁已由 public/theme-bootstrap.js（外链脚本）负责，
// 运行时切换由本实现完成：localStorage 持久化 + 系统偏好跟随（matchMedia）+
// 多标签 storage 同步 + class 属性切换（对应 index.css 的 .dark 自定义变体）。

export type Theme = 'light' | 'dark' | 'system'
/** 配色方案：同一套语义 token，换的是品牌色相与纸面底色。 */
export type Palette = 'jade' | 'ink' | 'clay' | 'celadon'

const STORAGE_KEY = 'theme'
const PALETTE_KEY = 'palette'

export const PALETTES: { key: Palette; label: string; hint: string; swatch: string }[] = [
  { key: 'jade', label: '苔绿', hint: '刊物的身份色', swatch: '#2f5d46' },
  { key: 'ink', label: '墨蓝', hint: '学术、克制', swatch: '#2b3f63' },
  { key: 'clay', label: '赭石', hint: '纸感、人文', swatch: '#8a4b32' },
  { key: 'celadon', label: '青瓷', hint: '冷灰、安静', swatch: '#33585a' },
]

interface ThemeContextValue {
  /** 用户选择的主题（含 'system'） */
  theme: Theme
  /** 实际生效的主题（'system' 时由系统偏好解析） */
  resolvedTheme: 'light' | 'dark'
  /** 当前系统偏好 */
  systemTheme: 'light' | 'dark'
  setTheme: (theme: Theme) => void
  themes: Theme[]
  /** 当前配色方案 */
  palette: Palette
  setPalette: (palette: Palette) => void
  palettes: typeof PALETTES
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getSystemTheme(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function readStoredPalette(): Palette {
  try {
    const stored = localStorage.getItem(PALETTE_KEY)
    if (stored === 'jade' || stored === 'ink' || stored === 'clay' || stored === 'celadon') {
      return stored
    }
  } catch {
    // 隐私模式：用默认配色
  }
  return 'jade'
}

function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // 隐私模式下 localStorage 抛错：退回默认值
  }
  // 默认亮色：这是学术期刊站点，读者多在白天/办公室阅读，白底黑字更接近
  // 纸质期刊的阅读预期。用户仍可在右上角切换到暗色或「跟随系统」。
  return 'light'
}

// 与 public/theme-bootstrap.js 保持同一套类切换逻辑（attribute="class"）
function applyTheme(resolved: 'light' | 'dark'): void {
  const root = document.documentElement
  root.classList.remove('light', 'dark')
  root.classList.add(resolved)
  root.style.colorScheme = resolved
}

function applyPalette(palette: Palette): void {
  document.documentElement.setAttribute('data-palette', palette)
}

// disableTransitionOnChange：切换瞬间全局禁用过渡，避免深浅色交叉淡化闪烁
function disableTransitionsOnce(): void {
  const style = document.createElement('style')
  style.appendChild(
    document.createTextNode(
      '*,*::before,*::after{-webkit-transition:none!important;-moz-transition:none!important;-o-transition:none!important;-ms-transition:none!important;transition:none!important}',
    ),
  )
  document.head.appendChild(style)
  const clear = () => {
    window.getComputedStyle(document.body)
    setTimeout(() => style.remove(), 1)
  }
  clear()
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme)
  const [palette, setPaletteState] = useState<Palette>(readStoredPalette)
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(getSystemTheme)
  const resolvedTheme = theme === 'system' ? systemTheme : theme

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // 隐私模式：仅内存生效
    }
    disableTransitionsOnce()
  }, [])

  const setPalette = useCallback((next: Palette) => {
    setPaletteState(next)
    try {
      localStorage.setItem(PALETTE_KEY, next)
    } catch {
      // 隐私模式：仅内存生效
    }
    disableTransitionsOnce()
  }, [])

  // 系统偏好变化（含 theme==='system' 时由 resolvedTheme 派生应用）
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystemTheme(getSystemTheme())
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    applyTheme(resolvedTheme)
  }, [resolvedTheme])

  useEffect(() => {
    applyPalette(palette)
  }, [palette])

  // 多标签同步：其他标签改主题后本标签跟随
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) {
        const next = e.newValue
        setThemeState(next === 'light' || next === 'dark' ? next : 'system')
      } else if (e.key === PALETTE_KEY) {
        const next = e.newValue
        setPaletteState(
          next === 'ink' || next === 'clay' || next === 'celadon' ? next : 'jade',
        )
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      resolvedTheme,
      systemTheme,
      setTheme,
      themes: ['light', 'dark', 'system'],
      palette,
      setPalette,
      palettes: PALETTES,
    }),
    [theme, resolvedTheme, systemTheme, setTheme, palette, setPalette],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within <ThemeProvider>')
  return ctx
}
