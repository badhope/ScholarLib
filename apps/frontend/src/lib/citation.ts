import type { ResourceResponse } from '@/lib/types'

export type CitationStyle = 'gb-t-7714' | 'apa' | 'mla'

export type CitationResource = Pick<
  ResourceResponse,
  'title' | 'authors' | 'year' | 'type' | 'venue' | 'publisher' | 'doi' | 'volume' | 'issue' | 'pages' | 'external_url' | 'site_id'
>

const TYPE_MARK: Record<string, string> = {
  paper: 'J',
  book: 'M',
  dataset: 'DS',
  tutorial: 'EB/OL',
}

function clean(value?: string | null): string {
  return (value ?? '').trim()
}

function authorList(authors: string[]): string[] {
  return authors.map((a) => a.trim()).filter(Boolean)
}

function gbtAuthors(authors: string[]): string {
  const names = authorList(authors)
  if (!names.length) return '佚名'
  return names.slice(0, 3).join('，') + (names.length > 3 ? '，等' : '')
}

function gbtType(type: string): string {
  return TYPE_MARK[type] ?? 'Z'
}

function gbtSource(resource: CitationResource): string {
  const venue = clean(resource.venue) || clean(resource.publisher)
  if (!venue) return ''
  const year = resource.year ? String(resource.year) : ''
  const vol = clean(resource.volume)
  const issue = clean(resource.issue)
  const pages = clean(resource.pages)
  const volIssue = [vol, issue ? `(${issue})` : ''].filter(Boolean).join('')
  return `${venue}${year ? `，${year}` : ''}${volIssue ? `，${volIssue}` : ''}${pages ? `：${pages}` : ''}．`
}

function apaAuthors(authors: string[]): string {
  const names = authorList(authors)
  if (!names.length) return ''
  if (names.length === 1) return names[0]
  if (names.length === 2) return `${names[0]}, & ${names[1]}`
  return `${names.slice(0, -1).join(', ')}, & ${names[names.length - 1]}`
}

function apaSource(resource: CitationResource): string {
  const venue = clean(resource.venue) || clean(resource.publisher)
  if (!venue) return ''
  const year = resource.year ? String(resource.year) : ''
  const vol = clean(resource.volume)
  const issue = clean(resource.issue)
  const pages = clean(resource.pages)
  const volIssue = [vol, issue ? `(${issue})` : ''].filter(Boolean).join('')
  return `${venue}${year ? `, ${year}` : ''}${volIssue ? `, ${volIssue}` : ''}${pages ? `, ${pages}` : ''}.`
}

function mlaAuthors(authors: string[]): string {
  const names = authorList(authors)
  if (!names.length) return ''
  if (names.length === 1) return names[0]
  if (names.length === 2) return `${names[0]}, and ${names[1]}`
  return `${names[0]}, et al`
}

function tail(resource: CitationResource): string {
  const doi = clean(resource.doi)
  if (doi) return `https://doi.org/${doi.replace(/^https?:\/\/doi\.org\//i, '')}`
  return clean(resource.external_url) || clean(resource.site_id) || ''
}

/**
 * 轻量引用生成：不引入 CSL 引擎，先覆盖站内最常用的三种。
 * 作者名保持用户录入的原始顺序，不擅自把中文姓名拆成姓/名。
 */
export function formatCitation(resource: CitationResource, style: CitationStyle): string {
  const title = clean(resource.title) || '无题'
  const year = resource.year ? String(resource.year) : ''
  const typeMark = gbtType(resource.type)
  const source = gbtSource(resource)
  const suffix = tail(resource)

  if (style === 'apa') {
    const authors = apaAuthors(resource.authors)
    const apa = [
      authors ? `${authors}` : '',
      year ? `(${year}).` : '',
      `${title}.`,
      apaSource(resource),
      suffix,
    ].filter(Boolean).join(' ')
    return apa.replace(/\s+/g, ' ').trim()
  }

  if (style === 'mla') {
    const authors = mlaAuthors(resource.authors)
    const venue = clean(resource.venue) || clean(resource.publisher)
    const pages = clean(resource.pages) ? `pp. ${clean(resource.pages)}.` : ''
    return [
      authors ? `${authors}.` : '',
      `"${title}."`,
      venue ? `${venue},` : '',
      year ? `${year},` : '',
      pages,
      suffix,
    ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim()
  }

  return `${gbtAuthors(resource.authors)}：${title}[${typeMark}]．${source}${suffix ? ` ${suffix}` : ''}`.trim()
}
