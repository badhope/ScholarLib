// 娱乐轨文体（v1.16）。与后端 catalog/genre.py 的 code 一一对应。
// 论文轨没有“文体”字段；这里只服务娱乐区的分栏与筛选。

export type EssayGenre =
  | 'joke'
  | 'fiction'
  | 'review'
  | 'guide'
  | 'essay'
  | 'poetry'
  | 'rant'

export interface EssayGenreMeta {
  value: EssayGenre
  label: string
  /** 卡片/导航上的一句人话，不写成“分类说明”。 */
  hint: string
  emoji: string
}

export const ESSAY_GENRES: EssayGenreMeta[] = [
  { value: 'joke', label: '学术整活', hint: '把论文格式用在最不该用的地方', emoji: '🧪' },
  { value: 'fiction', label: '小说故事', hint: '有情节，有角色，可能还有猫', emoji: '📖' },
  { value: 'review', label: '评论杂谈', hint: '认真评，认真跑题', emoji: '💬' },
  { value: 'guide', label: '指南攻略', hint: '不一定有用，但一定很具体', emoji: '🧭' },
  { value: 'essay', label: '随笔', hint: '想到哪写到哪，拒绝提纲', emoji: '✍️' },
  { value: 'rant', label: '吐槽', hint: '情绪先到，论证后补', emoji: '🔥' },
]

const GENRE_BY_VALUE = new Map(ESSAY_GENRES.map((g) => [g.value, g]))

export function essayGenreMeta(value?: string | null): EssayGenreMeta {
  return GENRE_BY_VALUE.get((value ?? '') as EssayGenre) ?? ESSAY_GENRES[0]
}

export function essayGenreLabel(value?: string | null): string {
  return essayGenreMeta(value).label
}
