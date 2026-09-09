import test from 'node:test'
import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { createRequestId } from '../src/utils/requestId.ts'

test('HTTP 随机源生成不重复的 UUID v4，原生实现不可调用也能发送', () => {
  const source = { getRandomValues: bytes => webcrypto.getRandomValues(bytes) }
  const values = Array.from({length: 200}, () => createRequestId(source))
  assert.equal(new Set(values).size, values.length)
  for (const value of values) assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  assert.match(createRequestId({...source, randomUUID() { throw new Error('不可用') }}), /^[0-9a-f-]{36}$/)
  assert.throws(() => createRequestId({}), /安全随机/)
})
