import { useState } from 'react'
import { toast } from 'sonner'
import { extractError } from '@/lib/utils'
import { useUpdateBio } from '@/hooks/api/use-auth'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'

const MAX_BIO = 200

/** 一句话简介：PATCH /users/me 的 bio 字段；空串提交 = 清除。 */
export function BioCard({ initialBio }: { initialBio?: string | null }) {
  // 用 key 重置替代 effect 回写 state（react-hooks/set-state-in-effect）：
  // 外层在 initialBio 变化时给组件换 key，本地草稿自动丢弃。
  const [value, setValue] = useState(initialBio ?? '')
  const savedBio = initialBio ?? ''
  // 走 useUpdateBio 而不是裸 api.patch：保存成功后统一失效 ['auth','me']，
  // 个人中心与设置页读的是同一份缓存，避免两处显示不同步。
  const updateBio = useUpdateBio()

  const dirty = value !== savedBio
  const remaining = MAX_BIO - value.length

  const save = async () => {
    try {
      const data = await updateBio.mutateAsync({ bio: value.trim() })
      setValue(data.bio ?? '')
      toast.success(data.bio ? '简介已更新' : '简介已清除')
    } catch (err) {
      toast.error(extractError(err, '保存失败'))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>个人简介</CardTitle>
        <CardDescription>
          一句话介绍自己（≤{MAX_BIO} 字），展示在个人中心。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value.slice(0, MAX_BIO))}
          placeholder="例：荒诞现象业余观测者，正经研究在读研究生。"
          rows={3}
          maxLength={MAX_BIO}
        />
        <div className="flex items-center justify-between">
          <span
            className={`text-xs ${remaining < 20 ? 'text-destructive' : 'text-muted-foreground'}`}
          >
            {remaining} 字可用
          </span>
          <Button size="sm" onClick={save} disabled={!dirty || updateBio.isPending}>
            {updateBio.isPending ? '保存中…' : '保存简介'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
