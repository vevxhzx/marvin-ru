import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'

const TAG_ATTRS = '((?:\\{[^}]*\\}|[^>])*)'
const tagRe = (n) => new RegExp(`<${n}\\b${TAG_ATTRS}>`, 'gs')

const files = []
const walk = (d) => {
  for (const e of readdirSync(d, { withFileTypes: true })) {
    const p = join(d, e.name)
    if (e.isDirectory()) walk(p)
    else if (/\.jsx?$/.test(e.name)) files.push(p)
  }
}
walk('web/src/mapp')

let n = 0
for (const f of files) {
  const t = readFileSync(f, 'utf8')
  for (const m of t.matchAll(tagRe('button'))) {
    if (!/\btype=/.test(m[0])) {
      n++
      console.log(relative('.', f), t.slice(0, m.index).split('\n').length, m[0].replace(/\s+/g, ' ').slice(0, 100))
    }
  }
}
console.log('buttons without type:', n, 'of', files.length, 'files')
