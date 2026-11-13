import { useRef, useState } from 'react'
import { Camera, Check, ImagePlus, LockKeyhole, Loader2, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { uploadForumImage } from '@/lib/forum'
import { extractError, cn } from '@/lib/utils'
import type { UserProfileUpdate, UserResponse } from '@/lib/types'
import { useUpdateProfile } from '@/hooks/api/use-auth'
import { useUnlockAccent, useWallet } from '@/hooks/api/use-currency'
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
const MAX_IMAGE = 5 * 1024 * 1024

const ACCENTS = [
  { value: '#2f5d46', label: '松绿' },
  { value: '#24334d', label: '墨蓝' },
  { value: '#8a5a2b', label: '赭石' },
  { value: '#7a3350', label: '绛紫' },
  { value: '#3f6f73', label: '雾青' },
  { value: '#8b6b2e', label: '麦金' },
]

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
  avatar_url: string
  banner_url: string
  accent_color: string
  contact_email: string
  profile_visibility: 'public' | 'private'
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
    avatar_url: user?.avatar_url ?? '',
    banner_url: user?.banner_url ?? '',
    accent_color: user?.accent_color || '#2f5d46',
    contact_email: user?.contact_email ?? '',
    profile_visibility: user?.profile_visibility === 'private' ? 'private' : 'public',
  }
}

const FIELDS: Array<{
  key: keyof ProfileForm
  label: string
  placeholder: string
  maxLength: number
  type?: 'text' | 'url'
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

export function ProfileDetailsCard({ initial }: { initial?: UserResponse | null }) {
  const [form, setForm] = useState<ProfileForm>(() => toForm(initial))
  const [uploading, setUploading] = useState<'avatar' | 'banner' | null>(null)
  const avatarInput = useRef<HTMLInputElement>(null)
  const bannerInput = useRef<HTMLInputElement>(null)
  const updateProfile = useUpdateProfile()
  const wallet = useWallet()
  const unlockAccent = useUnlockAccent()
  const saved = toForm(initial)

  const set = (key: keyof ProfileForm, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const dirty = (Object.keys(form) as Array<keyof ProfileForm>).some(
    (key) => form[key] !== saved[key],
  )
  const accentUnlocked = Boolean(saved.accent_color === form.accent_color || wallet.data?.accent_unlocked)

  const pickImage = async (file: File | undefined, key: 'avatar_url' | 'banner_url') => {
    if (!file) return
    if (!/^image\/(png|jpeg|gif|webp)$/.test(file.type)) {
      toast.error('只支持 PNG / JPEG / GIF / WebP')
      return
    }
    if (file.size > MAX_IMAGE) {
      toast.error('图片不能超过 5MB')
      return
    }
    setUploading(key === 'avatar_url' ? 'avatar' : 'banner')
    try {
      const url = await uploadForumImage(file)
      set(key, url)
      toast.success(key === 'avatar_url' ? '头像已上传，保存后生效' : '封面已上传，保存后生效')
    } catch (err) {
      toast.error(extractError(err, '图片上传失败'))
    } finally {
      setUploading(null)
    }
  }

  const unlock = async () => {
    try {
      await unlockAccent.mutateAsync()
      toast.success('已解锁自定义主题色')
    } catch (err) {
      toast.error(extractError(err, 'R 币不足，先签到攒币'))
    }
  }

  const save = async () => {
    const body: UserProfileUpdate = {}
    for (const key of Object.keys(form) as Array<keyof ProfileForm>) {
      const next = form[key].trim()
      const prev = saved[key].trim()
      if (next === prev) continue
      if (key === 'profile_visibility') {
        body.profile_visibility = form.profile_visibility
        continue
      }
      if (key === 'accent_color') {
        body.accent_color = form.accent_color
        continue
      }
      // 空串提交 = 清除该字段；后端会把空串归一为 None。
      ;(body as Record<string, string | null>)[key] = next || null
    }
    if (Object.keys(body).length === 0) return
    try {
      await updateProfile.mutateAsync(body)
      toast.success('主页资料已保存')
    } catch (err) {
      toast.error(extractError(err, '保存失败，请检查主页链接是否为 http(s)'))
    }
  }

  const bioLeft = MAX_TEXT - form.bio.length

  return (
    <Card>
      <CardHeader>
        <CardTitle>个人主页</CardTitle>
        <CardDescription>
          这些信息会出现在你的公开主页。账号邮箱不会公开；只有你填写的公开联系邮箱会展示。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="overflow-hidden rounded-2xl border bg-card">
          <div
            className="relative h-28 sm:h-36"
            style={{
              background: form.banner_url
                ? `center / cover no-repeat url(${form.banner_url})`
                : `linear-gradient(120deg, ${form.accent_color}22, ${form.accent_color}55)`,
            }}
          >
            <button
              type="button"
              onClick={() => bannerInput.current?.click()}
              className="absolute right-3 top-3 inline-flex h-8 items-center gap-1.5 rounded-full border bg-background/90 px-3 text-xs font-medium shadow-sm backdrop-blur hover:bg-background"
            >
              {uploading === 'banner' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}
              {form.banner_url ? '换封面' : '上传封面'}
            </button>
            <input
              ref={bannerInput}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              className="hidden"
              onChange={(e) => void pickImage(e.target.files?.[0], 'banner_url')}
            />
          </div>
          <div className="flex items-end gap-4 px-4 pb-4 sm:px-6">
            <div className="relative -mt-8 shrink-0">
              {form.avatar_url ? (
                <img
                  src={form.avatar_url}
                  alt="头像"
                  className="h-20 w-20 rounded-full border-4 border-card object-cover shadow-sm"
                />
              ) : (
                <span
                  className="flex h-20 w-20 items-center justify-center rounded-full border-4 border-card text-2xl font-semibold text-white shadow-sm"
                  style={{ backgroundColor: form.accent_color }}
                >
                  {(form.display_name || initial?.username || 'R').slice(0, 1)}
                </span>
              )}
              <button
                type="button"
                onClick={() => avatarInput.current?.click()}
                className="absolute -bottom-1 -right-1 flex h-7 w-7 items-center justify-center rounded-full border bg-background shadow-sm hover:bg-muted"
                aria-label="上传头像"
              >
                {uploading === 'avatar' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Camera className="h-3.5 w-3.5" />}
              </button>
              <input
                ref={avatarInput}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                className="hidden"
                onChange={(e) => void pickImage(e.target.files?.[0], 'avatar_url')}
              />
            </div>
            <div className="min-w-0 flex-1 pb-1">
              <p className="truncate text-sm font-medium">
                {form.display_name || initial?.username || '未命名主页'}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {form.bio || '一句话简介会显示在这里'}
              </p>
            </div>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {FIELDS.map((field) => (
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

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="profile-contact_email">公开联系邮箱</Label>
            <Input
              id="profile-contact_email"
              type="email"
              value={form.contact_email}
              maxLength={255}
              placeholder="选填，会展示在公开主页"
              onChange={(e) => set('contact_email', e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>主页可见性</Label>
            <div className="flex gap-2">
              {[
                { value: 'public', label: '公开' },
                { value: 'private', label: '仅自己' },
              ].map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => set('profile_visibility', item.value)}
                  className={cn(
                    'h-9 rounded-md border px-3 text-sm transition-colors',
                    form.profile_visibility === item.value
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'bg-background text-muted-foreground hover:bg-muted',
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <Label>主页主题色</Label>
            {!accentUnlocked && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <LockKeyhole className="h-3 w-3" /> 100 R 币解锁
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {ACCENTS.map((accent) => {
              const active = form.accent_color.toLowerCase() === accent.value
              return (
                <button
                  key={accent.value}
                  type="button"
                  disabled={!accentUnlocked && !active}
                  onClick={() => {
                    if (!accentUnlocked && !active) {
                      toast.info('先花 100 R 币解锁自定义主题色')
                      return
                    }
                    set('accent_color', accent.value)
                  }}
                  className={cn(
                    'flex h-9 items-center gap-2 rounded-full border px-3 text-xs transition-opacity',
                    active ? 'border-foreground/40 bg-muted/40' : 'border-border',
                    !accentUnlocked && !active && 'cursor-not-allowed opacity-50',
                  )}
                >
                  <span className="h-4 w-4 rounded-full" style={{ backgroundColor: accent.value }} />
                  {accent.label}
                  {active && <Check className="h-3.5 w-3.5" />}
                </button>
              )
            })}
            {!accentUnlocked && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void unlock()}
                disabled={unlockAccent.isPending}
              >
                {unlockAccent.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                解锁自定义色
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            主题色会用在主页头像、按钮和封面渐变上；解锁后永久可用。
          </p>
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
            <Button size="sm" onClick={() => void save()} disabled={!dirty || updateProfile.isPending}>
              {updateProfile.isPending ? '保存中…' : '保存主页'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
