import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type Prefs = {
  in_app_comment: boolean
  in_app_forum: boolean
  in_app_review: boolean
  in_app_submission: boolean
  email_comment: boolean
  email_forum: boolean
  email_review: boolean
  email_submission: boolean
}

const ROWS: Array<{ key: keyof Prefs; label: string; hint: string }> = [
  { key: 'in_app_comment', label: '文章评论', hint: '有人评论你发表的文章时，在站内通知你' },
  { key: 'in_app_forum', label: '论坛回复', hint: '有人回复你的帖子时，在站内通知你' },
  { key: 'in_app_review', label: '审稿邀请与催审', hint: '指派、催审、裁决等审稿工作通知' },
  { key: 'in_app_submission', label: '投稿进度', hint: '稿件录用、拒稿、返修等决定' },
  { key: 'email_comment', label: '文章评论邮件', hint: '额外发一封邮件；需要站点配置 SMTP 才会真正送达' },
  { key: 'email_forum', label: '论坛回复邮件', hint: '额外发一封邮件；需要站点配置 SMTP 才会真正送达' },
  { key: 'email_review', label: '审稿邮件', hint: '审稿指派与催审邮件' },
  { key: 'email_submission', label: '投稿决定邮件', hint: '录用/拒稿等决定邮件' },
]

export function NotificationPrefsCard() {
  const [prefs, setPrefs] = useState<Prefs | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .get<Prefs>('/users/me/notification-preferences')
      .then((res) => {
        if (alive) setPrefs(res.data)
      })
      .catch(() => {
        if (alive) toast.error('通知偏好加载失败，请稍后再试')
      })
    return () => {
      alive = false
    }
  }, [])

  async function save() {
    if (!prefs) return
    setSaving(true)
    try {
      const res = await api.patch<Prefs>('/users/me/notification-preferences', prefs)
      setPrefs(res.data)
      toast.success('通知偏好已保存')
    } catch {
      toast.error('保存失败，请稍后再试')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>通知偏好</CardTitle>
        <CardDescription>
          站内通知即时到达；邮件是额外通道，未配置 SMTP 时只会记录为“未发送”，不会假装送达。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!prefs ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {ROWS.map((row) => (
                <label
                  key={row.key}
                  className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/40"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 accent-[#2f5d46]"
                    checked={prefs[row.key]}
                    onChange={(e) =>
                      setPrefs((prev) => (prev ? { ...prev, [row.key]: e.target.checked } : prev))
                    }
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{row.label}</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                      {row.hint}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                自己评论/回复自己的内容不会触发通知。
              </p>
              <Button onClick={save} disabled={saving} size="sm">
                {saving ? '保存中…' : '保存偏好'}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
