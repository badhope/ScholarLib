import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { AxiosError } from 'axios'
import { Info } from 'lucide-react'
import { toast } from 'sonner'
import { requireAdminGuard } from '@/lib/route-guards'
import {
  useReviewMode,
  useSetReviewMode,
  useSiteSettings,
  useUpdateSiteSettings,
} from '@/hooks/api/use-modules'
import type { ReviewMode, SiteSettingsResponse } from '@/lib/types'
import { PageHeader } from '@/components/common/page-header'
import { ErrorState, Loading } from '@/components/common/state'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

export const Route = createFileRoute('/admin/settings')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminSettingsPage,
})

const REVIEW_MODE_OPTIONS: {
  value: ReviewMode
  label: string
  description: string
}[] = [
  {
    value: 'single_blind',
    label: '单盲评审',
    description:
      '审稿人可以看到作者姓名与单位；作者始终看不到审稿人身份。多数学科的默认做法。',
  },
  {
    value: 'double_blind',
    label: '双盲评审',
    description:
      '在单盲基础上，进一步对审稿人隐藏作者姓名、通讯邮箱、投稿人与发表信息，仅保留标题、摘要、关键词与正文。',
  },
]

function AdminSettingsPage() {
  const { data, isLoading, isError, refetch } = useReviewMode()
  const setMode = useSetReviewMode()
  const site = useSiteSettings()
  const updateSite = useUpdateSiteSettings()
  const [siteDraft, setSiteDraft] = useState<SiteSettingsResponse | null>(null)
  if (siteDraft === null && site.data) {
    setSiteDraft(site.data)
  }
  const siteDirty =
    siteDraft !== null &&
    site.data !== undefined &&
    (siteDraft.captcha_required_for_registration !==
      site.data.captcha_required_for_registration ||
      siteDraft.doi_author_entry_enabled !== site.data.doi_author_entry_enabled)
  // 本地暂存选择，点"保存"才提交，避免误点即生效
  const [draft, setDraft] = useState<ReviewMode | null>(null)
  // 当 draft 为 null 且 data 到达时初始化（仅首次）
  if (draft === null && data) {
    setDraft(data.review_mode)
  }
  const current = data?.review_mode
  const dirty = draft !== null && draft !== current

  const handleSave = () => {
    if (!draft || !dirty) return
    setMode.mutate(draft, {
      onSuccess: (res) => {
        setDraft(res.review_mode)
        toast.success(
          res.review_mode === 'double_blind'
            ? '已切换为双盲评审'
            : '已切换为单盲评审',
        )
      },
      onError: (err) => {
        const msg =
          err instanceof AxiosError
            ? (err.response?.data?.detail ?? err.message)
            : '保存失败'
        toast.error(typeof msg === 'string' ? msg : '保存失败')
      },
    })
  }

  return (
    <div>
      <PageHeader
        title="期刊设置"
        description="配置本刊的评审流程策略，设置对全站生效。"
      />

      {isLoading ? (
        <Loading />
      ) : isError ? (
        <ErrorState message="加载期刊设置失败" onRetry={() => refetch()} />
      ) : (
        <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">评审模式</CardTitle>
            <CardDescription>
              决定审稿人在审稿工作台能看到多少作者信息。
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-3">
            <fieldset className="space-y-3">
              <legend className="sr-only">评审模式</legend>
              {REVIEW_MODE_OPTIONS.map((opt) => {
                const checked = draft === opt.value
                return (
                  <label
                    key={opt.value}
                    data-testid={`review-mode-${opt.value}`}
                    className={
                      'flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors ' +
                      (checked
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:bg-muted/50')
                    }
                  >
                    <input
                      type="radio"
                      name="review-mode"
                      value={opt.value}
                      checked={checked}
                      onChange={() => setDraft(opt.value)}
                      className="mt-1 size-4 accent-primary"
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">
                        {opt.label}
                        {current === opt.value && (
                          <span className="ml-2 text-xs font-normal text-muted-foreground">
                            当前生效
                          </span>
                        )}
                      </span>
                      <span className="mt-1 block text-sm text-muted-foreground">
                        {opt.description}
                      </span>
                    </span>
                  </label>
                )
              })}
            </fieldset>

            <p className="flex items-start gap-2 rounded-md bg-muted p-3 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                切换只影响此后打开的稿件视图。已经分派并被审稿人看过的稿件，
                作者身份无法「收回」；正文中若含有可识别信息（致谢、基金号、
                自引），仍需作者自行匿名化。管理员账号不受双盲限制。
              </span>
            </p>
          </CardContent>

          <CardFooter className="gap-2">
            <Button
              onClick={handleSave}
              disabled={!dirty || setMode.isPending}
              data-testid="save-review-mode"
            >
              {setMode.isPending ? '保存中…' : '保存'}
            </Button>
            {dirty && (
              <Button
                variant="ghost"
                onClick={() => setDraft(current ?? null)}
                disabled={setMode.isPending}
              >
                取消
              </Button>
            )}
          </CardFooter>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">注册与题录开关</CardTitle>
            <CardDescription>
              这些开关写入本租户设置，重启后仍然生效；不会改动环境变量默认值。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {site.isLoading ? (
              <Loading />
            ) : site.isError || siteDraft === null ? (
              <ErrorState message="加载运营开关失败" onRetry={() => site.refetch()} />
            ) : (
              <>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-4">
                  <input
                    type="checkbox"
                    checked={siteDraft.captcha_required_for_registration}
                    onChange={(e) =>
                      setSiteDraft({
                        ...siteDraft,
                        captcha_required_for_registration: e.target.checked,
                      })
                    }
                    className="mt-1 size-4 accent-primary"
                  />
                  <span>
                    <span className="block text-sm font-medium">注册必须回答验证码</span>
                    <span className="mt-1 block text-sm text-muted-foreground">
                      关闭后注册页不再请求验证码；已签发但未使用的验证码自然失效。
                    </span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-4">
                  <input
                    type="checkbox"
                    checked={siteDraft.doi_author_entry_enabled}
                    onChange={(e) =>
                      setSiteDraft({
                        ...siteDraft,
                        doi_author_entry_enabled: e.target.checked,
                      })
                    }
                    className="mt-1 size-4 accent-primary"
                  />
                  <span>
                    <span className="block text-sm font-medium">允许作者填写官方 DOI</span>
                    <span className="mt-1 block text-sm text-muted-foreground">
                      关闭后投稿表单隐藏 DOI 输入；已保存的 DOI 不会被删除，只是不再新增。
                    </span>
                  </span>
                </label>
              </>
            )}
          </CardContent>
          <CardFooter className="gap-2">
            <Button
              onClick={() => {
                if (!siteDraft || !siteDirty) return
                updateSite.mutate(siteDraft, {
                  onSuccess: (res) => {
                    setSiteDraft(res)
                    toast.success('运营开关已保存')
                  },
                  onError: (err) => {
                    const msg =
                      err instanceof AxiosError
                        ? (err.response?.data?.detail ?? err.message)
                        : '保存失败'
                    toast.error(typeof msg === 'string' ? msg : '保存失败')
                  },
                })
              }}
              disabled={!siteDirty || updateSite.isPending}
            >
              {updateSite.isPending ? '保存中…' : '保存开关'}
            </Button>
          </CardFooter>
        </Card>
        </div>
      )}
    </div>
  )
}
