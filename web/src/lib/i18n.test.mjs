/* Юнит-тест словаря и плюрализации. Запуск: npm run test:i18n (или node web/src/lib/i18n.test.mjs)
 *
 * Проверяем то, что ломается тихо: пустой перевод, забытый en/ru, кривую форму
 * множественного числа и то, что t() никогда не отдаёт «сырой» ключ. */
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  DICT, SERVER, LANGS, DEFAULT_LANG, plural, pluralIndex, getLang, setLang, t, translate,
  fmtDate, fmtNumber, fmtMoney, translateServerValue,
} from './i18n.js'

const KEYS = Object.keys(DICT)
const isStr = (v) => typeof v === 'string' && v.trim().length > 0
const formsOk = (v) => Array.isArray(v) ? v.length > 0 && v.every(isStr) : isStr(v)

test('словарь не пуст и ключи уникальны', () => {
  assert.ok(KEYS.length > 200, `в словаре всего ${KEYS.length} ключей`)
  assert.equal(new Set(KEYS).size, KEYS.length, 'есть дублирующиеся ключи')
  for (const k of KEYS) assert.match(k, /^[a-z0-9]+(_[a-z0-9]+)*(\.[a-z0-9_]+)+$/, `ключ «${k}» не в snake_case.dotted`)
})

test('у каждого ключа есть непустые ru и en', () => {
  for (const k of KEYS) {
    assert.ok(formsOk(DICT[k].ru), `«${k}»: пустой ru`)
    assert.ok(formsOk(DICT[k].en), `«${k}»: пустой en`)
  }
})

test('русская форма задана в трёх числах, английская — в одной или двух', () => {
  for (const k of KEYS) {
    if (Array.isArray(DICT[k].ru)) assert.equal(DICT[k].ru.length, 3, `«${k}»: нужно 3 русские формы`)
    if (Array.isArray(DICT[k].en)) assert.ok(DICT[k].en.length >= 1 && DICT[k].en.length <= 2, `«${k}»: в английском максимум 2 формы`)
  }
})

test('плейсхолдеры {…} одинаковы в ru и en', () => {
  const ph = (s) => (Array.isArray(s) ? s : [s]).join(' ').match(/\{[a-z_]+\}/g)?.sort().join(',') || ''
  for (const k of KEYS) {
    if (typeof DICT[k].ru === 'string' && typeof DICT[k].en === 'string') {
      assert.equal(ph(DICT[k].ru), ph(DICT[k].en), `«${k}»: плейсхолдеры разошлись`)
    }
  }
})

test('словари серверных значений тоже заполнены', () => {
  const sk = Object.keys(SERVER)
  assert.ok(sk.length > 20)
  for (const k of sk) {
    assert.ok(isStr(SERVER[k].ru), `SERVER.${k}: пустой ru`)
    assert.ok(isStr(SERVER[k].en), `SERVER.${k}: пустой en`)
  }
})

test('русская плюрализация 1/2/5/21/101', () => {
  assert.equal(pluralIndex(1, 'ru'), 0)
  assert.equal(pluralIndex(2, 'ru'), 1)
  assert.equal(pluralIndex(5, 'ru'), 2)
  assert.equal(pluralIndex(21, 'ru'), 0)
  assert.equal(pluralIndex(101, 'ru'), 0)
  assert.equal(pluralIndex(11, 'ru'), 2)
  assert.equal(pluralIndex(22, 'ru'), 1)
})

test('английская плюрализация: 1 → singular, всё остальное → plural', () => {
  assert.equal(pluralIndex(1, 'en'), 0)
  assert.equal(pluralIndex(0, 'en'), 1)
  assert.equal(pluralIndex(2, 'en'), 1)
  assert.equal(pluralIndex(101, 'en'), 1)
})

test('t() подставляет {name} и выбирает язык', () => {
  setLang('ru')
  assert.equal(getLang(), 'ru')
  // ключ с плейсхолдером: подстановка должна убрать {…} из результата
  const key = KEYS.find((k) => /\{(name|count|q|m|n|date)\}/.test(String(DICT[k].ru)))
  assert.ok(key, 'в словаре должен быть ключ с плейсхолдером')
  const out = translate(key, { name: 'Иван', count: 3, q: 'x', m: '₽1', n: 2, date: 'сегодня' })
  assert.ok(!/\{(name|count|q|m|n|date)\}/.test(out), `«${key}»: плейсхолдер остался — «${out}»`)
  // переводы реально различаются
  const diff = KEYS.find((k) => DICT[k].ru !== DICT[k].en)
  setLang('ru'); const ru = translate(diff)
  setLang('en'); const en = translate(diff)
  assert.notEqual(ru, en, `«${diff}»: ru и en совпадают`)
  setLang(DEFAULT_LANG)
})

test('t() никогда не отдаёт сырой ключ — фолбэк читаемый', () => {
  setLang('en')
  const out = translate('zzz.unknown_key')
  assert.ok(out && !out.includes('_') && !out.includes('.'), `фолбэк вернул «${out}»`)
  setLang(DEFAULT_LANG)
})

test('t.sv переводит значения, приходящие с сервера', () => {
  setLang('ru')
  assert.equal(translateServerValue('оплачен'), 'оплачен')
  setLang('en')
  assert.equal(translateServerValue('оплачен'), 'paid')
  assert.equal(translateServerValue('то что сервер не знает'), 'то что сервер не знает')
  setLang(DEFAULT_LANG)
})

test('форматы чисел и денег зависят от языка', () => {
  setLang('ru')
  assert.equal(fmtNumber(1234.5), '1\u00a0234,5')
  assert.equal(fmtMoney(1500), '1\u00a0500\u00a0₽')
  assert.equal(fmtMoney(-1500), '−1\u00a0500\u00a0₽')
  setLang('en')
  assert.equal(fmtNumber(1234.5), '1,234.5')
  assert.equal(fmtMoney(1500), '₽1,500')
  assert.equal(fmtDate('2026-10-02'), 'Oct 2, 2026')
  setLang(DEFAULT_LANG)
  assert.equal(fmtDate('2026-10-02'), '2 октября 2026')
})

test('язык по умолчанию — русский', () => {
  assert.equal(DEFAULT_LANG, 'ru')
  assert.deepEqual([...LANGS], ['ru', 'en'])
  setLang('xx')
  assert.equal(getLang(), 'ru', 'неизвестный язык должен откатываться на русский')
})