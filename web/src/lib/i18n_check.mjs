/* Проверка i18n: ищет русские строки в web/src, которые НЕ обёрнуты в t(...) и не помечены
 * как сырые данные. Цель — ноль «висящих» видимых строк: всё, что видит пользователь, идёт
 * через словарь (см. lib/i18n.js).
 *
 * Запуск:  node web/src/lib/i18n_check.mjs            (код 1, если нашлись строки)
 *          node web/src/lib/i18n_check.mjs --quiet    (только итог)
 *
 * Что считается «сырыми данными»:
 *   - ключи объектов: { 'Еда': '#ff9f0a' }  — ключ не видно пользователю;
 *   - строки с пометкой i18n-raw в этой строке или в трёх предыдущих непустых
 *     (данные/фразы для ядра, генерируемые файлы, ключи из лога ядра);
 *   - регулярные выражения и комментарии (вырезаются сканером).
 *
 * Проверяются три вида строк: строковые литералы, ТЕЛА шаблонных литералов
 * (без ${…}) и текстовые узлы JSX. Раньше сканер молча пропускал половину
 * разметки: закрывающий тег `</div>` принимался за регекс, а слэш в тексте
 * («404/405», «5 000 ₽/мес») — тоже. Из-за этого проверка отвечала «OK»
 * при живых русских строках на экране.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, dirname, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..')
const EXT = /\.(jsx?|mjs)$/
const CYR = /[Ѐ-ӿ]/
const RAW_MARK = 'i18n-raw'

/* Где может начинаться регекс. Старый вариант («всё, кроме ) ] }») путал регекс
   с закрывающим тегом JSX `</div>` и со слэшем прямо в тексте («404/405»,
   «5 000 ₽/мес») — из-за этого сканер замаскировывал половину разметки
   и молча пропускал русские тексты внутри неё. */
const REGEX_PREV_CHARS = new Set(['=', '(', ',', '[', '{', ';', ':', '?', '!', '&', '|', '+', '-', '*', '%', '^', '~'])
const REGEX_PREV_WORDS = ['return', 'of', 'in', 'typeof', 'new', 'case', 'await', 'yield', 'delete', 'void', 'instanceof', 'do']

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (EXT.test(name)) out.push(p)
  }
  return out
}

/* Сканер: вырезает комментарии, находит строковые литералы и запоминает,
   входит ли литерал в объектный литерал (тогда это ключ, а не видимая строка).
   Шаблонные литералы разбираются с учётом ${…}: тело — строка, подстановка — код. */
function* scan(src, mask, lineOf) {
  const stack = []            // 'obj' | 'arr' | 'paren' | 'block'
  const frames = []           // стек шаблонных литералов: { from, mode: 'body'|'code', depth, val, line }
  let i = 0
  const line = () => lineOf[i]
  const skip = (from, to) => { for (let k = from; k < to && k < mask.length; k++) mask[k] = 0 }
  const prevMeaningful = () => {
    for (let j = i - 1; j >= 0; j--) if (!/\s/.test(src[j])) return src[j]
    return ''
  }
  const lastMeaningfulWord = () => {
    for (let j = i - 1; j >= 0; j--) {
      const c = src[j]
      if (!/\s/.test(c)) {
        if (/[A-Za-z_$]/.test(c)) { let k = j; while (k >= 0 && /[A-Za-z0-9_$]/.test(src[k])) k--; return src.slice(k + 1, j + 1) }
        return c
      }
    }
    return ''
  }
  const startsObject = () => {
    const c = prevMeaningful()
    if (c === '' ) return true
    if ('=(,:[?&|!+{;'.includes(c)) return true
    if (c === '>') return lastMeaningfulWord() === '=>'
    const w = lastMeaningfulWord()
    return ['return', 'of', 'in', 'typeof', 'new', 'case', 'await', 'yield'].includes(w)
  }

  while (i < src.length) {
    const c = src[i]

    // --- внутри шаблонного литерала: тело копится в f.val, подстановка — обычный код.
    //     Рамка остаётся в стеке всё время: вложенный шаблон ложится поверх неё. ---
    if (frames.length) {
      const f = frames[frames.length - 1]
      if (f.mode === 'code') {
        if (c === '}') { f.depth--; if (!f.depth) f.mode = 'body'; i++; continue }
        if (c === '{') { f.depth++; i++; continue }
        // иначе — символ обычного кода: обрабатываем ниже, стек шаблонов не трогаем
      } else {
        if (c === '\\') { f.val += src[i + 1]; i += 2; continue }
        if (c === '`') {
          skip(f.from, i + 1); frames.pop()
          // тело шаблонного литерала — тоже строка: её тоже надо проверять
          if (f.val.trim()) yield { val: f.val, line: f.line, quote: '`', tpl: true }
          i++; continue
        }
        if (c === '$' && src[i + 1] === '{') { f.mode = 'code'; f.depth = 1; i += 2; continue }
        f.val += c; i++; continue
      }
    }

    // «//» — комментарий; но не «https://…» и не «file:///» внутри текста
    if (c === '/' && src[i + 1] === '/' && src[i - 1] !== ':') { skip(i, src.indexOf('\n', i) < 0 ? src.length : src.indexOf('\n', i)); while (i < src.length && src[i] !== '\n') i++; continue }
    if (c === '/' && src[i + 1] === '*') {
      const from = i; i += 2
      while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++
      i += 2; skip(from, i); continue
    }
    if (c === '/' && isRegexStart()) {
      const from = i
      i++
      let inCls = false
      while (i < src.length) {
        if (src[i] === '\n') break
        if (src[i] === '\\') { i += 2; continue }
        if (src[i] === '[') inCls = true
        else if (src[i] === ']') inCls = false
        else if (src[i] === '/' && !inCls) { i++; break }
        i++
      }
      while (i < src.length && /[a-z]/.test(src[i])) i++
      skip(from, i)
      continue
    }
    if (c === '`') { frames.push({ from: i, mode: 'body', depth: 0, val: '', line: lineOf[i + 1] }); i++; continue }
    if (c === '"' || c === "'") {
      const quote = c
      const startLine = line()
      const from = i
      i++
      let val = ''
      while (i < src.length && src[i] !== quote) {
        if (src[i] === '\\') { val += src[i + 1]; i += 2; continue }
        val += src[i]; i++
      }
      i++
      skip(from, i)
      let k = i
      while (k < src.length && /[ \t]/.test(src[k])) k++
      const isKey = src[k] === ':' && stack[stack.length - 1] === 'obj'
      yield { val, line: startLine, isKey, quote }
      continue
    }
    if ('([{'.includes(c)) {
      const kind = c === '{' ? (startsObject() ? 'obj' : 'block') : c === '[' ? 'arr' : 'paren'
      stack.push(kind); i++; continue
    }
    if (')]}'.includes(c)) { stack.pop(); i++; continue }
    i++
  }

  function isRegexStart() {
    const c = prevMeaningful()
    if (c === '') return true
    if (c === '>') return lastMeaningfulWord() === '=>'
    if (REGEX_PREV_CHARS.has(c)) return true
    return REGEX_PREV_WORDS.includes(lastMeaningfulWord())
  }
}

/* Текстовые узлы JSX: `>текст<` или `>текст {`. Строка считается только если это
   действительно код (а не содержимое строкового литерала или комментария). */
function jsxTexts(src, mask, lineOf) {
  const out = []
  const re = />([^<>{}]*[А-Яа-яЁё][^<>{}]*)(?=[<{])/g
  let m
  while ((m = re.exec(src))) {
    const from = m.index + 1, to = from + m[1].length
    let clean = true
    for (let k = from; k < to; k++) if (!mask[k]) { clean = false; break }
    if (!clean) continue
    out.push({ val: m[1].replace(/\s+/g, ' ').trim(), line: lineOf[from], jsx: true })
  }
  return out
}

/* Пометка i18n-raw в этой строке или в трёх предыдущих непустых.
   Раньше проверялась только первая непустая строка: разметка «комментарий над строкой»
   не работала, и пометка молча терялась. */
function rawMarked(lines, ln) {
  let seen = 0
  for (let j = ln - 1; j >= 0 && seen < 3; j--) {
    if (lines[j] === '') continue
    seen++
    if (lines[j].includes(RAW_MARK)) return true
  }
  return false
}

const only = process.argv.find((a) => a.startsWith('--file='))
const onlyPath = only ? only.slice(7).replace(/\\/g, '/') : null
const quiet = process.argv.includes('--quiet')
const files = walk(SRC).filter((f) => !f.endsWith('i18n_check.mjs') && !f.endsWith('i18n.test.mjs') && !f.endsWith(`${sep}i18n.js`))
  .filter((f) => !onlyPath || f.replace(/\\/g, '/').endsWith(onlyPath))

let total = 0
const perFile = []
for (const f of files) {
  const src = readFileSync(f, 'utf8')
  const lines = src.split('\n')
  const mask = new Uint8Array(src.length).fill(1)   // 1 — код, 0 — строка/комментарий/регекс
  // карта «индекс → номер строки» (1-based), чтобы обратное сканирование не путало строки
  const lineOf = new Uint32Array(src.length + 1)
  for (let k = 0, ln = 1; k < src.length; k++) lineOf[k] = ln, ln += src[k] === '\n' ? 1 : 0
  lineOf[src.length] = lineOf[src.length - 1] + 1
  const it = scan(src, mask, lineOf)
  const found = [...it]
  const hits = [...found, ...jsxTexts(src, mask, lineOf)]
    .filter((h) => !h.isKey && CYR.test(h.val) && !rawMarked(lines, h.line))
    .sort((a, b) => a.line - b.line)
  if (hits.length) {
    perFile.push([relative(SRC, f).replace(/\\/g, '/'), hits])
    total += hits.length
  }
}

if (!quiet) {
  for (const [f, hits] of perFile) {
    console.log(`\n${f} — ${hits.length}`)
    for (const h of hits) console.log(`  ${h.line}: ${JSON.stringify(h.val)}`)
  }
}
console.log(`\n${'='.repeat(52)}`)
console.log(total === 0 ? 'OK: висящих русских строк нет' : `НАЙДЕНО висящих русских строк: ${total} (в ${perFile.length} файл(ах))`)
process.exit(total === 0 ? 0 : 1)