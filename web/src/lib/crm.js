// Общие правила CRM для интерфейса. Две РАЗНЫЕ сущности, их нельзя смешивать:
//   • стадия ЗАКАЗА  — воронка из 9 стадий (core/crm/stages.py), двигается кнопкой «следующий шаг» и drag&drop;
//   • стадия КЛИЕНТА — лид/переговоры/клиент/постоянный/спит-ушёл (core/crm/client_stages.py),
//     обновляется автоматически по заказам, меняется вручную; ручное значение авто-логика не перетирает.
// Здесь только чтение справочников и обёртки над API стадии клиента (новых эндпоинтов не добавляем).
import { api } from './api'
import { t } from './i18n'

/* ------------------------------------------------------- воронка ЗАКАЗА */
/* Второй элемент пары — ключ словаря, а не текст: подписи переключаются вместе с языком. */
export const ORDER_STAGES = [
  ['lead', 'crm.stage_lead'], ['negotiation', 'crm.stage_negotiation'], ['spec', 'crm.stage_spec'], ['in_work', 'crm.stage_in_work'],
  ['revisions', 'crm.stage_revisions'], ['delivered', 'crm.stage_delivered'], ['awaiting_payment', 'crm.stage_awaiting_payment'], ['paid', 'crm.stage_paid'], ['lost', 'crm.stage_lost'],
]
export const ORDER_STAGE_LABEL = Object.fromEntries(ORDER_STAGES)
export const LABEL_ORDER_STAGE = Object.fromEntries(ORDER_STAGES.map(([k, v]) => [v, k]))
/* Подпись стадии заказа текстом (то, что раньше лежало в самой таблице) */
export const orderStageLabel = (k) => (ORDER_STAGE_LABEL[k] ? t(ORDER_STAGE_LABEL[k]) : k)
/* Смысловой тинт по DESIGN.md: лайм = деньги/ок, янтарь = ожидание, красный = просрочка/риск. */
export const ORDER_STAGE_TONE = {
  lead: '', negotiation: '', spec: '', in_work: '',
  revisions: 'warn', delivered: 'pos', awaiting_payment: 'warn', paid: 'pos', lost: 'neg',
}
export const STAGE_TO_STATUS = { lead: 'new', negotiation: 'new', spec: 'new', in_work: 'work', revisions: 'review', delivered: 'done', awaiting_payment: 'done', paid: 'paid', lost: 'cancelled' }
export const STATUS_TO_STAGE = { new: 'lead', work: 'in_work', review: 'revisions', done: 'delivered', paid: 'paid', cancelled: 'lost' }
/* Стадия заказа: явная колонка `stage`, иначе старый статус (заказы до миграции). */
export const stageOf = (o) => (o?.stage && ORDER_STAGE_LABEL[o.stage] ? o.stage : STATUS_TO_STAGE[o?.status] || 'lead')

/* ГЛАВНОЕ действие строки: ровно одна кнопка с текстом по текущей стадии.
   «потерян» и «оплачен» шага не имеют — там либо причина, либо конец. */
export const NEXT_STEP = {
  lead: { stage: 'negotiation', text: 'crm.next_negotiation', tip: 'crm.next_negotiation_tip' },
  negotiation: { stage: 'spec', text: 'crm.next_spec', tip: 'crm.next_spec_tip' },
  spec: { stage: 'in_work', text: 'crm.next_in_work', tip: 'crm.next_in_work_tip' },
  in_work: { stage: 'revisions', text: 'crm.next_revisions', tip: 'crm.next_revisions_tip' },
  revisions: { stage: 'delivered', text: 'crm.next_delivered', tip: 'crm.next_delivered_tip' },
  delivered: { stage: 'awaiting_payment', text: 'crm.next_awaiting', tip: 'crm.next_awaiting_tip' },
  awaiting_payment: { stage: 'paid', text: 'crm.next_paid', tip: 'crm.next_paid_tip' },
}

/* ------------------------------------------------------- воронка КЛИЕНТА */
export const CLIENT_STAGES = [
  ['lead', 'crm.cstage_lead'], ['negotiation', 'crm.cstage_negotiation'], ['client', 'crm.cstage_client'], ['permanent', 'crm.cstage_permanent'], ['asleep', 'crm.cstage_asleep'],
]
export const CLIENT_STAGE_LABEL = Object.fromEntries(CLIENT_STAGES)
export const clientStageLabel = (k) => (CLIENT_STAGE_LABEL[k] ? t(CLIENT_STAGE_LABEL[k]) : k)
/* лайм = деньги/ок (есть оплаты), красный = риск/ушёл, акцент = переговоры. */
export const CLIENT_STAGE_TONE = { lead: '', negotiation: 'accent', client: 'pos', permanent: 'pos', asleep: 'neg' }
/* Когда стадия ставится сама — короткими словами в подсказке. */
export const CLIENT_STAGE_HINT = {
  lead: 'crm.chint_lead',
  negotiation: 'crm.chint_negotiation',
  client: 'crm.chint_client',
  permanent: 'crm.chint_permanent',
  asleep: 'crm.chint_asleep',
}
export const clientStageHint = (k) => (CLIENT_STAGE_HINT[k] ? t(CLIENT_STAGE_HINT[k]) : '')

export const clientStageApi = {
  list: () => api.get('/api/crm/client-stages'),
  get: (cid) => api.get(`/api/crm/clients/${cid}/stage`),
  set: (cid, stage) => api.put(`/api/crm/clients/${cid}/stage`, { stage }),
  clearManual: (cid) => api.del(`/api/crm/clients/${cid}/stage/manual`),
}

/* Стадии сразу для нескольких клиентов: эндпоинта «список» нет, поэтому по одному
   запросу на клиента, порциями по 6 — иначе браузер забивает все соединения. */
export async function loadClientStages(ids, { chunk = 6 } = {}) {
  const out = {}
  const list = [...new Set((ids || []).filter((x) => x != null))]
  for (let i = 0; i < list.length; i += chunk) {
    const part = await Promise.allSettled(list.slice(i, i + chunk).map((cid) => clientStageApi.get(cid)))
    part.forEach((r, j) => { if (r.status === 'fulfilled' && r.value) out[list[i + j]] = r.value })
  }
  return out
}