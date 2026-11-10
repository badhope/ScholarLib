// 存量摘要里有作者手打的硬换行；直接 pre-wrap 会渲染成
// “还涉及 / 生活成本”这种断句。单换行并成空格，空行保留段落。
const STRUCTURED_ABSTRACT_LABEL = '(?:背景|目的|方法学补充|方法|主要拓展|结果|结论|本文的自我限制|局限)'

export function normalizeAbstract(text: string): string {
  return text
    .replace(/\r/g, '')
    .replace(/\*\*/g, '')
    // 结构化摘要的“背景/目的/方法/结果/结论”是语义分段，不能当成硬换行压平
    .replace(new RegExp(`\\n(?=${STRUCTURED_ABSTRACT_LABEL}[。：])`, 'g'), '\u0000')
    .replace(/\n{2,}/g, '\u0000')
    .replace(/(?<=[\u4e00-\u9fff])\n(?=[\u4e00-\u9fff])/g, '')
    .replace(/\n/g, ' ')
    // 有些摘要没有换行，直接以“。目的。”串联，也补回分段
    .replace(new RegExp(`(?<=[。；])\\s*${STRUCTURED_ABSTRACT_LABEL}[。：]`, 'g'), (m) => `\n\n${m.trim()}`)
    // eslint-disable-next-line no-control-regex
    .replace(/\u0000/g, '\n\n')
}
