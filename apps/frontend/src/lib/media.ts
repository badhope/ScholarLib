import { api } from '@/lib/api'

/** 上传正文图片；返回可直接插进 Markdown 的站内短链。 */
export async function uploadMediaImage(file: File, purpose: 'submission' | 'forum' | 'note' = 'submission'): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<{ url: string }>(`/media/images?purpose=${purpose}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data.url
}
