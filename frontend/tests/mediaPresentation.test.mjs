import test from 'node:test'
import assert from 'node:assert/strict'
import { mediaPreviewFor, mediaPreviewsFor, safeMediaUrl } from '../src/agent/loop/mediaPresentation.ts'

/** 夹具模拟浏览器已收到的 tool.result 投影，不接触真实临时地址。 */
function tool(name, result) {
  return { name, status: 'succeeded', event: 'tool.result', display: { result_preview: JSON.stringify(result) } }
}

test('图片卡只预览受控 HTTPS 地址并保留模型状态', () => {
  const preview = mediaPreviewFor(tool('image.generate', {
    status: 'succeeded', model: 'qwen-image-3.0-pro',
    image_urls: ['https://cdn.example/image.png?Signature=temporary', 'javascript:alert(1)', 'data:image/png;base64,private'],
  }))
  assert.equal(preview?.kind, 'image')
  assert.deepEqual(preview?.imageUrls, ['https://cdn.example/image.png?Signature=temporary'])
  assert.equal(preview?.model, 'qwen-image-3.0-pro')
})

test('视频在完成前显示任务状态，完成后才提供播放器地址', () => {
  const pending = mediaPreviewFor(tool('video.create', { status: 'PENDING', upstream_task_id: 'task-1' }))
  assert.equal(pending?.videoUrl, null)
  assert.equal(pending?.upstreamTaskId, 'task-1')
  const ready = mediaPreviewFor(tool('video.status', {
    status: 'SUCCEEDED', upstream_task_id: 'task-1', video_url: 'https://cdn.example/video.mp4',
  }))
  assert.equal(ready?.videoUrl, 'https://cdn.example/video.mp4')
  assert.equal(safeMediaUrl('http://cdn.example/video.mp4'), null)
})

test('媒体总结区只汇总登记工具的成功结果', () => {
  const previews = mediaPreviewsFor([
    tool('image.generate', { status: 'succeeded', image_urls: ['https://cdn.example/image.png'] }),
    tool('read', { status: 'succeeded', image_urls: ['https://cdn.example/not-media.png'] }),
  ])
  assert.equal(previews.length, 1)
  assert.equal(previews[0]?.imageUrls[0], 'https://cdn.example/image.png')
})
