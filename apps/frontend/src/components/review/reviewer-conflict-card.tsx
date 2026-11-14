import { useEffect, useState } from 'react'
import { ShieldAlert, ShieldCheck } from 'lucide-react'
import { useMyCoiDeclaration, useSaveMyCoiDeclaration } from '@/hooks/api/use-modules'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

/**
 * P1-8：审稿人年度利益冲突声明。
 *
 * 声明是“可解释”的：分派时只用作者姓名/通讯邮箱做匹配。机构、项目等
 * 投稿表里没有的字段只在声明中留档，不假装能自动识别。未声明不会挡住
 * 分派，但编辑侧会看到“未声明”；有声明且命中则后端直接 409。
 */
export function ReviewerConflictCard() {
  const { data, isLoading } = useMyCoiDeclaration()
  const save = useSaveMyCoiDeclaration()
  const [open, setOpen] = useState(false)
  const [conflictsText, setConflictsText] = useState('')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    if (!open) return
    setConflictsText((data?.conflicts ?? []).join('\n'))
    setNotes(data?.notes ?? '')
  }, [open, data])

  const count = data?.conflicts.length ?? 0
  const year = data?.year ?? new Date().getFullYear()

  function submit() {
    save.mutate(
      {
        conflicts: conflictsText
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean),
        notes: notes.trim() || null,
      },
      { onSuccess: () => setOpen(false) },
    )
  }

  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
        <div className="flex min-w-0 items-start gap-2">
          {data?.declared ? (
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
          ) : (
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{year} 年度利益冲突声明</span>
              <Badge variant={data?.declared ? 'default' : 'outline'}>
                {isLoading ? '读取中' : data?.declared ? `已声明 · ${count} 条` : '未声明'}
              </Badge>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              只按作者姓名/通讯邮箱自动匹配；机构等字段不在投稿表里，不做猜测式拦截。
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          {data?.declared ? '更新声明' : '现在声明'}
        </Button>
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{year} 年度利益冲突声明</DialogTitle>
            <DialogDescription>
              每行一个冲突对象：作者姓名、通讯邮箱、机构或项目。分派时会用作者姓名和通讯邮箱匹配；
              命中即拦截，机构信息仅留档。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="coi-conflicts">冲突对象</Label>
              <Textarea
                id="coi-conflicts"
                value={conflictsText}
                onChange={(event) => setConflictsText(event.target.value)}
                placeholder={'张三\nzhangsan@example.com\n某大学（仅留档）'}
                rows={7}
              />
              <p className="text-xs text-muted-foreground">
                已去重；单个对象最多 120 字。声明只对当前年份生效，跨年需重新确认。
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="coi-notes">补充说明（可选）</Label>
              <Textarea
                id="coi-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="例如：本人与该团队存在项目合作，具体范围如下……"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button onClick={submit} disabled={save.isPending}>
              {save.isPending ? '保存中…' : '保存声明'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
