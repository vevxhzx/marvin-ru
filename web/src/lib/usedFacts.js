/* Последний ответ чата: id фактов, которые в него попали.
   Пишет Chat.jsx из used_fact_ids ответа (/api/chat и стрим — инжектор вшивает
   их в done-событие). Читает Memory.jsx. */
let ids = []
const subs = new Set()
export const getUsedFactIds = () => ids
export const setUsedFactIds = (next) => {
  ids = Array.isArray(next) ? next.map(Number).filter((x) => Number.isFinite(x)) : []
  subs.forEach((fn) => { try { fn(ids) } catch {} })
}
export const subscribeUsedFactIds = (fn) => { subs.add(fn); return () => { subs.delete(fn) } }
