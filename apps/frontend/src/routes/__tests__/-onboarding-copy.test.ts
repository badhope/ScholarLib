import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (name: string) => readFileSync(`src/routes/${name}.tsx`, 'utf8')

describe('homepage issue information', () => {
 it('does not advertise a fixed issue in the masthead', () => {
 expect(source('index')).not.toMatch(/第\s*1\s*卷\s*·\s*第\s*1\s*期\s*·\s*2026\s*年/)
 })
})

describe('onboarding guidance', () => {
 it('tells readers that reading and commenting need no points', () => {
 const profile = source('profile')
 // 身份体系 3.0：评论不再有积分门槛，文案不得再出现"L1/L2 解锁"。
 expect(profile).toContain('注册即可阅读和评论')
 expect(profile).toContain('to="/policies"')
 expect(profile).not.toContain('解锁 L2：评论')
 expect(profile).not.toContain('L1–L4由积分自动解锁')
 expect(profile).not.toContain('L2、L3 按积分解锁')
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
