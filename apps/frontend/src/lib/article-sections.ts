// Nature 式栏目 / 分部：与后端 catalog.SECTIONS 的 part slug 对齐。
// 投稿向导与后台新建资源共用同一份选项，避免两个入口的栏目名漂移。
export const ARTICLE_SECTION_OPTIONS = [
  { value: 'editorial', label: 'This Week · Editorial' },
  { value: 'world-view', label: 'This Week · World View' },
  { value: 'research-highlights', label: 'This Week · Research Highlights' },
  { value: 'news', label: 'News in Focus · News' },
  { value: 'features', label: 'News in Focus · Features' },
  { value: 'book-review', label: 'Books & Arts · Book Review' },
  { value: 'arts-review', label: 'Books & Arts · Arts Review' },
  { value: 'comment', label: 'Opinion · Comment' },
  { value: 'correspondence', label: 'Opinion · Correspondence' },
  { value: 'work-feature', label: 'Work · Feature' },
  { value: 'technology-feature', label: 'Work · Technology Feature' },
  { value: 'news-views', label: 'Research · News & Views' },
  { value: 'reviews', label: 'Research · Reviews' },
  { value: 'articles', label: 'Research · Articles' },
  { value: 'amendments-corrections', label: 'Amendments & Corrections' },
  { value: 'collections', label: 'Collections' },
] as const
