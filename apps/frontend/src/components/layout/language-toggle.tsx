import { Languages } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getLang, setLang, useLang } from '@/lib/i18n'

export function LanguageToggle() {
  const lang = useLang()
  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-8 gap-1.5 px-2 text-xs"
      onClick={() => setLang(getLang() === 'en' ? 'zh' : 'en')}
      aria-label={lang === 'en' ? '切换到中文' : 'Switch to English'}
      title={lang === 'en' ? '切换到中文' : 'Switch to English'}
    >
      <Languages className="h-3.5 w-3.5" />
      {lang === 'en' ? '中文' : 'EN'}
    </Button>
  )
}
