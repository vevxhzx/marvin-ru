// Общие правила CRM для интерфейса. Две РАЗНЫЕ сущности, их нельзя смешивать:
//   • стадия ЗАКАЗА  — воронка из 9 стадий (core/crm/stages.py), двигается кнопкой «следующий шаг» и drag&drop;
//   • стадия КЛИЕНТА — лид/переговоры/клиент/постоянный/спит-ушёл (core/crm/client_stages.py),
//     обновляется автоматически по заказам, меняется вручную; ручное значение авто-логика не перетирает.
// Здесь только чтение справочников и обёртки над API стадии клиента (новых эндпоинтов не добавляем).
import { api } from './api'

/* ------------------------------------------------------- воронка ЗАКАЗА */
export const ORDER_STAGES = [
  ['lead', 'лид'], ['negotiation', 'переговоры'], ['spec', 'ТЗ согласовано'], ['in_work', 'в работе'],
  ['revisions', 'на правках'], ['delivered', 'сдан'], ['awaiting_payment', 'ждёт оплаты'], ['paid', 'оплачен'], ['lost', 'потерян'],
]
export const ORDER_STAGE_LABEL = Object.fromEntries(ORDER_STAGES)
export const LABEL_ORDER_STAGE = Object.fromEntries(ORDER_STAGES.map(([k, v]) => [v, k]))
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
  lead: { stage: 'negotiation', text: 'Начать переговоры', tip: 'двинуть заказ из «лид» в переговоры' },
  negotiation: { stage: 'spec', text: 'Согласовать ТЗ', tip: 'условия согласованы, можно писать ТЗ' },
  spec: { stage: 'in_work', text: 'Взять в работу', tip: 'начать делать заказ' },
  in_work: { stage: 'revisions', text: 'Отправить на правки', tip: 'отдать клиенту первую версию' },
  revisions: { stage: 'delivered', text: 'Сдать', tip: 'работа закончена, дальше — оплата' },
  delivered: { stage: 'awaiting_payment', text: 'Запросить оплату', tip: 'отметить, что ждём денег' },
  awaiting_payment: { stage: 'paid', text: 'Отметить оплату', tip: 'записать оплату и закрыть заказ' },
}

/* ------------------------------------------------------- воронка КЛИЕНТА */
export const CLIENT_STAGES = [
  ['lead', 'лид'], ['negotiation', 'переговоры'], ['client', 'клиент'], ['permanent', 'постоянный'], ['asleep', 'спит/ушёл'],
]
export const CLIENT_STAGE_LABEL = Object.fromEntries(CLIENT_STAGES)
/* лайм = деньги/ок (есть оплаты), красный = риск/ушёл, акцент = переговоры. */
export const CLIENT_STAGE_TONE = { lead: '', negotiation: 'accent', client: 'pos', permanent: 'pos', asleep: 'neg' }
/* Когда стадия ставится сама — короткими словами в подсказке. */
export const CLIENT_STAGE_HINT = {
  lead: 'заказов и оплат ещё нет',
  negotiation: 'обсуждаем условия',
  client: 'есть хотя бы один оплаченный заказ',
  permanent: 'два и больше оплаченных заказов',
  asleep: 'нет активности 90 дней',
}

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