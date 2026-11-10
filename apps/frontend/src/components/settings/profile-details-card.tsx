import { useState } from 'react'
import { toast } from 'sonner'
import { extractError } from '@/lib/utils'
import type { UserProfileUpdate, UserResponse } from '@/lib/types'
import { useUpdateProfile } from '@/hooks/api/use-auth'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

const MAX_TEXT = 200

type ProfileForm = {
  display_name: string
  real_name: string
  affiliation: string
  department: string
  academic_title: string
  location: string
  research_interests: string
  website: string
  google_scholar: string
  bio: string
}

function toForm(user?: UserResponse | null): ProfileForm {
  return {
    display_name: user?.display_name ?? '',
    real_name: user?.real_name ?? '',
    affiliation: user?.affiliation ?? '',
    department: user?.department ?? '',
    academic_title: user?.academic_title ?? '',
    location: user?.location ?? '',
    research_interests: user?.research_interests ?? '',
    website: user?.website ?? '',
    google_scholar: user?.google_scholar ?? '',
    bio: user?.bio ?? '',
  }
}

const FIELDS: Array<{
  key: keyof ProfileForm
  label: string
  placeholder: string
  maxLength: number
  type?: 'text' | 'url'
  full?: boolean
}> = [
  { key: 'display_name', label: '展示名', placeholder: '如：牛马程序员', maxLength: 100 },
  { key: 'real_name', label: '真实姓名', placeholder: '选填，仅用于署名参考', maxLength: 100 },
  { key: 'affiliation', label: '单位 / 学校', placeholder: '如：清华大学 / 北京大学', maxLength: 300 },
  { key: 'department', label: '院系 / 部门', placeholder: '如：计算机系 / 信息学院', maxLength: 200 },
  { key: 'academic_title', label: '职称 / 身份', placeholder: '如：本科生、讲师、独立研究者', maxLength: 100 },
  { key: 'location', label: '所在地', placeholder: '如：北京', maxLength: 100 },
  { key: 'website', label: '个人主页', placeholder: 'https://example.com', maxLength: 300, type: 'url' },
  { key: 'google_scholar', label: 'Google Scholar', placeholder: 'https://scholar.google.com/…', maxLength: 300, type: 'url' },
]

/** 个人资料表单：一次性编辑展示名、机构、研究兴趣、主页与简介。 */
export function ProfileDetailsCard({ initial }: { initial?: UserResponse | null }) {
  const [form, setForm] = useState<ProfileForm>(() => toForm(initial))
  const updateProfile = useUpdateProfile()
  const saved = toForm(initial)

  const set = (key: keyof ProfileForm, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const dirty = (Object.keys(form) as Array<keyof ProfileForm>).some(
    (key) => form[key].trim() !== saved[key].trim(),
  )

  const save = async () => {
    const body: UserProfileUpdate = {}
    for (const key of Object.keys(form) as Array<keyof ProfileForm>) {
      const next = form[key].trim()
      const prev = saved[key].trim()
      if (next === prev) continue
      // 空串提交 = 清除该字段；后端会把空串归一为 None。
      body[key] = next || null
    }
    try {
      await updateProfile.mutateAsync(body)
      toast.success('个人资料已保存')
    } catch (err) {
      toast.error(extractError(err, '保存失败，请检查主页链接是否为 http(s)'))
    }
  }

  const bioLeft = MAX_TEXT - form.bio.length

  return (
    <Card>
      <CardHeader>
        <CardTitle>个人资料</CardTitle>
        <CardDescription>
          这些信息保存在你的账号中，用于个人中心展示。所有字段都可以留空；空值不会覆盖已有内容。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          {FIELDS.filter((f) => !f.full).map((field) => (
            <div key={field.key} className="space-y-1.5">
              <Label htmlFor={`profile-${field.key}`}>{field.label}</Label>
              <Input
                id={`profile-${field.key}`}
                type={field.type === 'url' ? 'url' : 'text'}
                inputMode={field.type === 'url' ? 'url' : undefined}
                value={form[field.key]}
                maxLength={field.maxLength}
                placeholder={field.placeholder}
                onChange={(e) => set(field.key, e.target.value)}
              />
            </div>
          ))}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="profile-research_interests">研究兴趣</Label>
          <Textarea
            id="profile-research_interests"
            value={form.research_interests}
            maxLength={500}
            rows={2}
            placeholder="如：多智能体系统、学术出版、内容治理、前端工程"
            onChange={(e) => set('research_interests', e.target.value)}
          />
          <p className="text-xs text-muted-foreground">用顿号或逗号分隔均可，最多 500 字。</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="profile-bio">个人简介</Label>
          <Textarea
            id="profile-bio"
            value={form.bio}
            maxLength={MAX_TEXT}
            rows={3}
            placeholder="一句话介绍自己，例：严肃格式下的自由选题爱好者，正经研究在读研究生。"
            onChange={(e) => set('bio', e.target.value.slice(0, MAX_TEXT))}
          />
          <div className="flex items-center justify-between gap-3">
            <span
              className={`text-xs ${bioLeft < 20 ? 'text-destructive' : 'text-muted-foreground'}`}
            >
              {bioLeft} 字可用
            </span>
            <Button size="sm" onClick={save} disabled={!dirty || updateProfile.isPending}>
              {updateProfile.isPending ? '保存中…' : '保存资料'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
