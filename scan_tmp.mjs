import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const TAG_ATTRS = '((?:\\{[^}]*\\}|[^>])*)'
const tagRe = (n) => new RegExp(`<${n}\\b${TAG_ATTRS}>`, 'gs')

const walk = (dir, out = []) => {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'site') continue
    const p = join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (/\.(jsx|js|tsx|ts)$/.test(e.name)) out.push(p)
  }
  return out
}

const targets = process.argv.slice(2)
const files = targets.length ? walk(join(process.cwd(), targets[0])) : walk(join(process.cwd(), 'web/src'))

for (const f of files) {
  const t = readFileSync(f, 'utf8')
  for (const tag of ['span', 'div', 'a', 'li', 'td', 'p', 'section', 'i']) {
    for (const m of t.matchAll(tagRe(tag))) {
      const s = m[0]
      if (!/\sonClick\s*=|\sonKeyDown\s*=|\sonPointerDown\s*=/.test(s)) continue
      const line = t.slice(0, m.index).split('\n').length
      const role = /\brole=/.test(s)
      const ti = /\btabIndex/i.test(s)
      const kbd = /onKeyDown|onKeyUp|onKeyPress/.test(s)
      const bad = tag !== 'button' && (!role || !ti || !kbd)
      if (bad) console.log(`${f}:${line} <${tag}> role=${role} tabIndex=${ti} kbd=${kbd} :: ${s.replace(/\s+/g, ' ').slice(0, 120)}`)
    }
  }
}
console.log('done')
