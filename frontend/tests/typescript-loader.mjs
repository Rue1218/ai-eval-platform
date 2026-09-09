import { readFile } from 'node:fs/promises'
import ts from 'typescript'

/** 单测复用项目锁定的 TS 编译器，兼容 CI Node 20，不依赖 Node 实验性 TS 转换。 */
export async function load(url, context, nextLoad) {
  if (!url.endsWith('.ts')) return nextLoad(url, context)
  const source = await readFile(new URL(url), 'utf8')
  return { format: 'module', shortCircuit: true, source: ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText }
}
