import { uploadMediaImage } from '@/lib/media'

/**
 * 论坛图片走通用媒体端点，和投稿正文共用同一套 MIME/大小/魔数校验。
 * 旧帖里的 `/api/forum/images/...` 仍由后端兼容路由继续可读。
 */
export async function uploadForumImage(file: File): Promise<string> {
  return uploadMediaImage(file, 'forum')
}
