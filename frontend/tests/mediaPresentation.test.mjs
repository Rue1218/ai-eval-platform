import test from 'node:test'
import assert from 'node:assert/strict'
import { canonicalMediaToolName, mediaPreviewFor, mediaPreviewsFor, safeMediaUrl } from '../src/agent/loop/mediaPresentation.ts'
import { toolAliases } from '../src/agent/loop/toolPresentation.ts'

/** 夹具模拟浏览器已收到的 tool.result 投影，不接触真实临时地址。 */
function tool(name, result, registryName) {
  return {
    name, registry_name: registryName, status: 'succeeded', event: 'tool.result',
    display: { result_preview: JSON.stringify(result) },
  }
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

test('模型侧 platform_ wire 名同样识别为媒体工具并生成预览', () => {
  // 真实链路里事件 name 是 wire 名（platform_image_generate），registry_name 才带点号。
  assert.equal(canonicalMediaToolName('platform_image_generate'), 'image.generate')
  const byWire = mediaPreviewFor(tool('platform_image_generate', {
    status: 'succeeded', image_urls: ['https://cdn.example/image.png'],
  }))
  assert.equal(byWire?.kind, 'image')
  assert.deepEqual(byWire?.imageUrls, ['https://cdn.example/image.png'])

  const video = mediaPreviewFor(tool('platform_video_status', {
    status: 'SUCCEEDED', upstream_task_id: 'task-1', video_url: 'https://cdn.example/video.mp4',
  }))
  assert.equal(video?.videoUrl, 'https://cdn.example/video.mp4')

  // registry_name 优先：即使别名表未覆盖也能还原（防御未来重命名）。
  const byRegistry = mediaPreviewFor(tool('platform_image_generate', {
    status: 'succeeded', image_urls: ['https://cdn.example/image.png'],
  }, 'image.generate'))
  assert.equal(byRegistry?.kind, 'image')
})

test('同一产物的多次查询只汇总一条，拿到成品地址的优先', () => {
  const previews = mediaPreviewsFor([
    tool('platform_video_create', { status: 'PENDING', upstream_task_id: 'task-1' }),
    tool('platform_video_status', { status: 'RUNNING', upstream_task_id: 'task-1' }),
    tool('platform_video_status', {
      status: 'SUCCEEDED', upstream_task_id: 'task-1', video_url: 'https://cdn.example/video.mp4',
    }),
    tool('platform_image_generate', { status: 'succeeded', image_urls: ['https://cdn.example/a.png'] }),
  ])
  assert.equal(previews.length, 2)
  assert.equal(previews[0]?.videoUrl, 'https://cdn.example/video.mp4')
  assert.deepEqual(previews[1]?.imageUrls, ['https://cdn.example/a.png'])
})

test('wire 名在通用工具卡上显示中文标题', () => {
  assert.equal(toolAliases['platform_image_generate'], '生成图片')
  assert.equal(toolAliases['platform_video_status'], '查询视频结果')
})
