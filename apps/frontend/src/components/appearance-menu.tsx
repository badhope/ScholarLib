import { Check, Moon, Palette, Sun, MonitorSmartphone } from 'lucide-react'
import { useTheme, type Theme } from '@/components/theme-provider'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const THEME_LABEL: Record<Theme, string> = {
  light: '亮色',
  dark: '暗色',
  system: '跟随系统',
}

const THEME_ICON: Record<Theme, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: MonitorSmartphone,
}

/**
 * 外观菜单：一个入口同时管「配色方案」和「明暗」。
 * 拆成两个按钮会让顶栏在移动端更挤，也让用户以为两者互不相干。
 */
export function AppearanceMenu() {
  const { theme, setTheme, themes, palette, setPalette, palettes, resolvedTheme } = useTheme()
  const currentPalette = palettes.find((item) => item.key === palette)
  const ariaLabel = '外观设置：' + (currentPalette?.label ?? '苔绿') + ' · ' + THEME_LABEL[resolvedTheme]

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={ariaLabel}
        >
          <Palette className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="text-xs font-medium tracking-wide text-muted-foreground">
          配色
        </DropdownMenuLabel>
        {palettes.map((item) => (
          <DropdownMenuItem
            key={item.key}
            onSelect={() => setPalette(item.key)}
            className="gap-3"
          >
            <span
              className="h-3.5 w-3.5 shrink-0 rounded-full ring-1 ring-border"
              style={{ backgroundColor: item.swatch }}
              aria-hidden
            />
            <span className="flex flex-1 flex-col leading-tight">
              <span className="text-sm">{item.label}</span>
              <span className="text-[11px] text-muted-foreground">{item.hint}</span>
            </span>
            {palette === item.key && <Check className="h-3.5 w-3.5 text-primary" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs font-medium tracking-wide text-muted-foreground">
          明暗
        </DropdownMenuLabel>
        {themes.map((item) => {
          const Icon = THEME_ICON[item]
          return (
            <DropdownMenuItem key={item} onSelect={() => setTheme(item)}>
              <Icon className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="flex-1 text-sm">{THEME_LABEL[item]}</span>
              {theme === item && <Check className="h-3.5 w-3.5 text-primary" />}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
