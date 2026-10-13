import { readFileSync } from 'node:fs'

const s = readFileSync('web/src/lib/i18n.js', 'utf8')
const keys = ['m.empty', 'm.empty_sub', 'm.empty_brain', 'm.empty_orders', 'm.list_empty', 'm.load_err', 'm.retry', 'm.loading',
  'm.no_events', 'm.free_day', 'm.free_day_sub', 'm.open', 'm.save', 'm.plan', 'm.qa_hint', 'm.qa_title', 'm.in_list',
  'm.tasks_sub', 'm.finance_sub', 'm.set_sub', 'm.brain_sub', 'm.more_sub', 'm.ready', 'm.persons', 'm.person',
  'm.subs_empty', 'm.goals', 'm.debts', 'm.no_debts', 'm.soon_sub', 'common.retry', 'state.error_title']
for (const k of keys) {
  const esc = k.replace(/\./g, '\\.')
  const m = s.match(new RegExp(`'${esc}':\\s*\\{[^}]*\\}`))
  console.log(k, '=>', m ? m[0] : 'NOT FOUND')
}
