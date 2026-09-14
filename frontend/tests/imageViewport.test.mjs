import assert from 'node:assert/strict'
import test from 'node:test'
import { clampImageScale, fitImageScale, clampImageOffset } from '../src/utils/imageViewport.ts'

test('适应窗口使用真实图片与容器尺寸，小图不放大', () => {
  assert.equal(fitImageScale(2000, 1000, 1000, 800), 0.5)
  assert.equal(fitImageScale(1000, 2000, 1000, 800), 0.4)
  assert.equal(fitImageScale(200, 100, 1000, 800), 1)
  assert.equal(fitImageScale(0, 0, 0, 0), 1)
})
test('旋转 90/270 度后按交换宽高适配', () => {
  assert.equal(fitImageScale(2000, 1000, 1000, 800, 90), 0.4)
  assert.equal(fitImageScale(2000, 1000, 1000, 800, 270), 0.4)
  assert.equal(fitImageScale(2000, 1000, 1000, 800, 180), 0.5)
})
test('缩放限制在 1% 到 500%，非法比例不传播', () => {
  assert.equal(clampImageScale(0), 0.01)
  assert.equal(clampImageScale(10), 5)
  assert.equal(clampImageScale(NaN), 1)
  assert.equal(clampImageScale(0.8), 0.8)
})
test('拖动不能越出图片边界，缩小后自动归中', () => {
  assert.equal(clampImageOffset(900, 2000, 1000), 500)
  assert.equal(clampImageOffset(-900, 2000, 1000), -500)
  assert.equal(clampImageOffset(100, 200, 1000), 0)
  assert.equal(clampImageOffset(100, 2000, 1000), 100)
})
