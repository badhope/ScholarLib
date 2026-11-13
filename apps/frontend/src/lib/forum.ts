import { api } from '@/lib/api'

/** 上传一张论坛图片，返回可直接插进 Markdown 的站内短链。 */
export async function uploadForumImage(file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<{ url: string }>('/forum/images', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data.url
}
