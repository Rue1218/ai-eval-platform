import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_ATTACHMENT_BYTES,
  attachmentRejectionReason,
  createPreviewTracker,
  hasAllowedAttachmentSuffix,
} from '../src/agent/attachments.ts'

test('hasAllowedAttachmentSuffix：白名单大小写不敏感，无后缀拒绝', () => {
  assert.equal(hasAllowedAttachmentSuffix('a.md'), true)
  assert.equal(hasAllowedAttachmentSuffix('A.PDF'), true)
  assert.equal(hasAllowedAttachmentSuffix('report.xlsx'), true)
  assert.equal(hasAllowedAttachmentSuffix('voice.WAV'), true)
  assert.equal(hasAllowedAttachmentSuffix('photo.jpeg'), true)
  assert.equal(hasAllowedAttachmentSuffix('script.exe'), false)
  assert.equal(hasAllowedAttachmentSuffix('noext'), false)
  assert.equal(hasAllowedAttachmentSuffix('archive.tar.gz'), false)
})

test('attachmentRejectionReason：空 / 超限 / 格式 三类拒绝，正常为 null', () => {
  assert.equal(attachmentRejectionReason({ name: 'a.md', size: 0 }), '空文件')
  assert.equal(attachmentRejectionReason({ name: 'a.md', size: MAX_ATTACHMENT_BYTES + 1 }), '超过 20MB')
  assert.equal(attachmentRejectionReason({ name: 'a.exe', size: 10 }), '格式不支持')
  assert.equal(attachmentRejectionReason({ name: 'a.md', size: MAX_ATTACHMENT_BYTES }), null)
  assert.equal(attachmentRejectionReason({ name: 'a.md', size: 1 }), null)
})

test('createPreviewTracker：只释放已追踪 URL，重复释放与未知 URL 无副作用', () => {
  const revoked = []
  const tracker = createPreviewTracker(
    file => `blob:${file.name}`,
    url => revoked.push(url),
  )
  const url = tracker.create({ name: 'x' })
  assert.equal(url, 'blob:x')
  assert.equal(tracker.size, 1)
  tracker.release('blob:unknown')
  assert.deepEqual(revoked, [])
  tracker.release(url)
  assert.deepEqual(revoked, ['blob:x'])
  assert.equal(tracker.size, 0)
  tracker.release(url)
  assert.deepEqual(revoked, ['blob:x'])
  tracker.release(undefined)
  assert.deepEqual(revoked, ['blob:x'])
})

test('createPreviewTracker：revokeAll 清空全部且幂等', () => {
  const revoked = []
  const tracker = createPreviewTracker(file => `blob:${file.name}`, url => revoked.push(url))
  tracker.create({ name: 'a' })
  tracker.create({ name: 'b' })
  assert.equal(tracker.size, 2)
  tracker.revokeAll()
  assert.deepEqual(revoked.sort(), ['blob:a', 'blob:b'])
  assert.equal(tracker.size, 0)
  tracker.revokeAll()
  assert.equal(revoked.length, 2)
})
