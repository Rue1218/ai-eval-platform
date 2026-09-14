/** 图片缩放范围；比例以原始像素为基准，避免 CSS 限宽造成虚假的 100%。 */
export const MIN_IMAGE_SCALE = 0.01
export const MAX_IMAGE_SCALE = 5

/** 限制缩放范围并隔离非法输入。 */
export function clampImageScale(scale: number): number {
  return Number.isFinite(scale) ? Math.min(MAX_IMAGE_SCALE, Math.max(MIN_IMAGE_SCALE, scale)) : 1
}

/** 按旋转后的真实尺寸适配容器，小图默认不放大。 */
export function fitImageScale(width: number, height: number, viewportWidth: number, viewportHeight: number, rotation = 0): number {
  if (width <= 0 || height <= 0 || viewportWidth <= 0 || viewportHeight <= 0) return 1
  const swapped = Math.abs(rotation % 180) === 90
  return clampImageScale(Math.min(1, viewportWidth / (swapped ? height : width), viewportHeight / (swapped ? width : height)))
}

/** 限制拖动范围，缩小后自动归中，避免图片被拖出视野。 */
export function clampImageOffset(offset: number, imageSize: number, viewportSize: number): number {
  const limit = Math.max(0, (imageSize - viewportSize) / 2)
  return Math.min(limit, Math.max(-limit, offset))
}
