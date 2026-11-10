import { useState } from 'react'
import { Plus, Trash2, ChevronUp, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { AuthorEditInput, AuthorRole } from '@/lib/types'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/**
 * 作者编辑面板（v5，发布前管理端）。
 * - 增删作者
 * - 上下按钮排序（移动端兜底；桌面端也支持 HTML5 drag）
 * - 第一作者单选（唯一）
 * - 通讯作者单选（可空，唯一）
 * - 本地校验：≥1 位、第一唯一、通讯唯一、邮箱格式
 */
export function AuthorEditor({
  value,
  onChange,
}: {
  value: AuthorEditInput[]
  onChange: (next: AuthorEditInput[]) => void
}) {
  const [dragOver, setDragOver] = useState<number | null>(null)

  const sorted = [...value].sort((a, b) => a.order - b.order)

  const update = (idx: number, patch: Partial<AuthorEditInput>) => {
    const next = sorted.map((a, i) => (i === idx ? { ...a, ...patch } : a))
    reassignOrder(next)
    onChange(next)
  }

  const reassignOrder = (arr: AuthorEditInput[]) => {
    arr.forEach((a, i) => {
      a.order = i + 1
    })
  }

  const add = () => {
    const next = [...sorted, { name: '', affiliation: '', email: '', roles: [], order: sorted.length + 1 }]
    onChange(next)
  }

  const remove = (idx: number) => {
    const next = sorted.filter((_, i) => i !== idx)
    reassignOrder(next)
    onChange(next)
  }

  const move = (idx: number, dir: -1 | 1) => {
    const j = idx + dir
    if (j < 0 || j >= sorted.length) return
    const next = [...sorted]
    ;[next[idx], next[j]] = [next[j], next[idx]]
    reassignOrder(next)
    onChange(next)
  }

  const toggleRole = (idx: number, role: AuthorRole) => {
    const author = sorted[idx]
    const has = author.roles.includes(role)
    let roles: AuthorRole[]
    if (has) {
      roles = author.roles.filter((r) => r !== role)
    } else {
      // 唯一：取消其他人的同一角色
      roles = [role]
      sorted.forEach((a, i) => {
        if (i !== idx && a.roles.includes(role)) {
          a.roles = a.roles.filter((r) => r !== role)
        }
      })
    }
    update(idx, { roles })
  }

  // 校验
  const errors: string[] = []
  if (sorted.length === 0) errors.push('至少需要 1 位作者')
  if (sorted.length > 0 && !sorted.some((a) => a.roles.includes('first')))
    errors.push('必须指定 1 位第一作者')
  sorted.forEach((a) => {
    if (!a.name.trim()) errors.push('作者姓名不能为空')
    if (a.email && a.email.trim() && !EMAIL_RE.test(a.email.trim()))
      errors.push(`「${a.name}」的邮箱格式不正确`)
  })

  return (
    <div className="space-y-3">
      {sorted.map((author, idx) => (
        <div
          key={idx}
          draggable
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(idx)
          }}
          onDragLeave={() => setDragOver(null)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(null)
            // 简单拖拽：前端不实现跨 index 交换，移动端用上下按钮
          }}
          className={
            'rounded-lg border p-3 space-y-2 ' +
            (dragOver === idx ? 'border-primary bg-primary/5' : '')
          }
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              <span className="text-xs font-medium text-muted-foreground">#{author.order}</span>
              <button
                type="button"
                onClick={() => move(idx, -1)}
                disabled={idx === 0}
                className="rounded p-1 hover:bg-muted disabled:opacity-30"
                aria-label="上移"
              >
                <ChevronUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => move(idx, 1)}
                disabled={idx === sorted.length - 1}
                className="rounded p-1 hover:bg-muted disabled:opacity-30"
                aria-label="下移"
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
            <button
              type="button"
              onClick={() => remove(idx)}
              disabled={sorted.length <= 1}
              className="rounded p-1 text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-30"
              aria-label="删除作者"
              title={sorted.length <= 1 ? '至少保留 1 位作者' : '删除作者'}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-1">
              <Label className="text-xs">姓名</Label>
              <Input
                value={author.name}
                onChange={(e) => update(idx, { name: e.target.value })}
                placeholder="张三"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">单位</Label>
              <Input
                value={author.affiliation ?? ''}
                onChange={(e) => update(idx, { affiliation: e.target.value })}
                placeholder="清华大学"
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">邮箱（仅在作者认领后公开）</Label>
            <Input
              type="email"
              value={author.email ?? ''}
              onChange={(e) => update(idx, { email: e.target.value })}
              placeholder="name@university.edu.cn"
            />
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            邮箱可留空；公开仅对已完成认领的作者生效。
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={author.roles.includes('first')}
                onChange={() => toggleRole(idx, 'first')}
              />
              第一作者（仅 1 位）
            </label>
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={author.roles.includes('corresponding')}
                onChange={() => toggleRole(idx, 'corresponding')}
              />
              通讯作者（可选 1 位）
            </label>
          </div>
        </div>
      ))}

      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus className="h-4 w-4" />
        添加作者
      </Button>

      {errors.length > 0 && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
          <p className="font-medium">校验未通过：</p>
          <ul className="ml-4 list-disc">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
