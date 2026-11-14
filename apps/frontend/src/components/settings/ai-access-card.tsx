import { useEffect, useState } from 'react'
import { Bot, Copy, KeyRound, Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { extractError } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

type TokenRow = {
  id: number
  name: string
  prefix: string
  scopes: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  request_count: number
}

function fmt(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('zh-CN')
}

export function AiAccessCard() {
  const [rows, setRows] = useState<TokenRow[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('我的 AI 助手')
  const [days, setDays] = useState(90)
  const [plain, setPlain] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const res = await api.get<TokenRow[]>('/ai/tokens')
      setRows(res.data)
    } catch (err) {
      toast.error(extractError(err, 'Token 列表加载失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function create() {
    setCreating(true)
    try {
      const res = await api.post<{ token: string }>('/ai/tokens', {
        name: name.trim() || 'AI 助手',
        expires_in_days: days,
      })
      setPlain(res.data.token)
      toast.success('Token 已创建，明文只显示这一次')
      void load()
    } catch (err) {
      toast.error(extractError(err, '创建失败'))
    } finally {
      setCreating(false)
    }
  }

  async function revoke(id: number) {
    try {
      await api.delete(`/ai/tokens/${id}`)
      toast.success('已撤销')
      void load()
    } catch (err) {
      toast.error(extractError(err, '撤销失败'))
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success('已复制')
    } catch {
      toast.error('复制失败，请手动选中')
    }
  }

  const origin = typeof window !== 'undefined' ? window.location.origin : 'https://rubbish.argjiemi.cn'
  const mcpConfig = `{
  "mcpServers": {
    "rubbish": {
      "command": "python3",
      "args": ["/abs/path/tools/rubbish-mcp/server.py"],
      "env": {
        "RUBBISH_API_TOKEN": "rbk_你的Token",
        "RUBBISH_BASE_URL": "${origin}"
      }
    }
  }
}`

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-4 w-4" /> AI 投稿接入
          </CardTitle>
          <CardDescription>
            给 MCP / 脚本一个只做投稿的个人 Token。不接受账号密码；Token 可撤销、默认 90 天过期，
            权限只有投稿和读取自己的资料。投稿仍会跑敏感词、站内相似度与每小时 10 篇限流；账号还需先确认当版《投稿与编辑规范》，否则返回 403。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_120px_auto]">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
              placeholder="Token 名称，例如 Cursor / Claude"
            />
            <Input
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value) || 90)}
              aria-label="有效期（天）"
            />
            <Button onClick={create} disabled={creating}>
              {creating ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
              创建 Token
            </Button>
          </div>

          {plain ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:bg-amber-950/20">
              <p className="font-medium">只显示这一次，请现在复制：</p>
              <div className="mt-2 flex items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded bg-background px-2 py-1 font-mono text-xs">
                  {plain}
                </code>
                <Button size="sm" variant="outline" onClick={() => copy(plain)}>
                  <Copy className="mr-1 h-3.5 w-3.5" /> 复制
                </Button>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                关闭页面后无法再次查看；丢了就撤销重建。
              </p>
            </div>
          ) : null}

          {loading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">还没有 Token。</p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {rows.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 p-3 text-sm">
                  <KeyRound className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{r.name}</span>
                  <code className="text-xs text-muted-foreground">{r.prefix}…</code>
                  <Badge variant={r.revoked_at ? 'outline' : 'secondary'}>
                    {r.revoked_at ? '已撤销' : '有效'}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    创建 {fmt(r.created_at)} · 到期 {fmt(r.expires_at)} · 调用 {r.request_count}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto text-destructive"
                    onClick={() => revoke(r.id)}
                    disabled={Boolean(r.revoked_at)}
                  >
                    <Trash2 className="mr-1 h-3.5 w-3.5" /> 撤销
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" /> 接入方式
          </CardTitle>
          <CardDescription>
            把下面配置放到支持 MCP 的客户端；Token 只放环境变量，不要写进提示词或公开仓库。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            工具：<code>submit_paper</code>（投稿，支持幂等键）、
            <code>list_my_submissions</code>（查状态与站内相似度）。
          </p>
          <div className="relative">
            <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
              {mcpConfig}
            </pre>
            <Button
              size="sm"
              variant="outline"
              className="absolute right-2 top-2"
              onClick={() => copy(mcpConfig)}
            >
              <Copy className="mr-1 h-3.5 w-3.5" /> 复制
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            也支持直接调 REST：<code>POST /api/ai/submissions</code>，请求头
            <code>X-API-Key: rbk_...</code>；能力说明见 <code>/api/ai/capabilities</code>。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
