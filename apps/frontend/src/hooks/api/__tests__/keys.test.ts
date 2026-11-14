import { describe, expect, it } from 'vitest'
import { keys } from '../use-modules'

describe('query keys', () => {
  it('separates list cache entries by pageSize', () => {
    expect(keys.submission.mine(undefined, 1, 1)).not.toEqual(
      keys.submission.mine(undefined, 1, 20),
    )
    expect(keys.submission.all(undefined, 1, 1)).not.toEqual(
      keys.submission.all(undefined, 1, 20),
    )
    expect(keys.submission.pending(1, 1)).not.toEqual(
      keys.submission.pending(1, 20),
    )
    expect(keys.review.myAssignments('pending', 1, 5)).not.toEqual(
      keys.review.myAssignments('pending', 1, 20),
    )
  })
})
