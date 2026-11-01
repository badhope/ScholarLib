import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (name: string) => readFileSync(`src/routes/${name}.tsx`, 'utf8')

describe('onboarding guidance', () => {
 it('directs L1 readers to the rules without claiming comments require L2', () => {
 const profile = source('profile')
 expect(profile).toContain('L1 即可阅读和评论')
 expect(profile).toContain('to="/policies"')
 expect(profile).not.toContain('解锁 L2：评论')
 expect(profile).not.toContain('L1–L4由积分自动解锁')
 })

 it('allows authors who accepted the current rules to access submissions at L1', () => {
 const authors = source('authors')
 expect(authors).not.toContain('currentLevel >=3')
 expect(authors).not.toContain('先确认社区规范（L2）')
 expect(authors).not.toContain('账号会升到 L3')
 expect(authors).toContain('to="/submissions"')
 })

 it('describes the XP thresholds and acceptance requirement accurately', () => {
 expect(source('levels')).not.toContain('L1–L3 随确认动作解锁')
 })
})
