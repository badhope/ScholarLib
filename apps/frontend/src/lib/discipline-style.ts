/**
 * 学科 → 图标/配色映射（首页分类入口与 /browse 共用）。
 *
 * 每个学科一个专属图标：此前「信息科学」与「数学与统计」共用
 * LineChart，是复制粘贴遗漏——图标是导航线索，撞图标会让两个
 * 入口看起来像同一个东西。
 */
import {
  Atom,
  BookOpen,
  Brain,
  Cpu,
  Database,
  FlaskConical,
  Globe2,
  Landmark,
  Leaf,
  LineChart,
  Users,
  type LucideIcon,
} from 'lucide-react'

export const DISCIPLINE_STYLE: Record<string, { icon: LucideIcon; tint: string }> = {
  计算机科学: { icon: Cpu, tint: 'from-sky-500/15 to-sky-500/5' },
  信息科学: { icon: Database, tint: 'from-indigo-500/15 to-indigo-500/5' },
  生命科学: { icon: FlaskConical, tint: 'from-emerald-500/15 to-emerald-500/5' },
  物理与宇宙学: { icon: Atom, tint: 'from-violet-500/15 to-violet-500/5' },
  地球科学: { icon: Globe2, tint: 'from-teal-500/15 to-teal-500/5' },
  生态与环境科学: { icon: Leaf, tint: 'from-green-500/15 to-green-500/5' },
  数学与统计: { icon: LineChart, tint: 'from-cyan-500/15 to-cyan-500/5' },
  心理学: { icon: Brain, tint: 'from-rose-500/15 to-rose-500/5' },
  社会科学: { icon: Users, tint: 'from-amber-500/15 to-amber-500/5' },
  人文与文化研究: { icon: Landmark, tint: 'from-orange-500/15 to-orange-500/5' },
  管理学: { icon: BookOpen, tint: 'from-blue-500/15 to-blue-500/5' },
}

export const DEFAULT_DISCIPLINE_STYLE = { icon: BookOpen, tint: 'from-primary/15 to-primary/5' }
