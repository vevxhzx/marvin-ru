import { useSheetPresence } from './ui'
import { lower, name as aName, dat } from '../lib/name'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, X, Undo2, Check, CalendarDays, CheckSquare, Wallet, Brain, Cloud, Zap, Cpu, AlertCircle, HelpCircle, Link2, Sparkles } from 'lucide-react'
import { chatStream, api, dayLabel, hhmm, isSameDay, kbShiftEnter } from '../lib/api'
import { useRefresh } from '../App'
import { MorningDigestCard, WeekSummaryCard } from './ReportCards'
import { useI18n, t as T } from '../lib/i18n'

/* Что реально сделал ассистент — карточка результата, а не технический лог.
   Первый элемент пары — ключ словаря, второй — иконка. */
export const ACT = {
  add_expense: ['act.a_expense', Wallet], add_income: ['act.a_income', Wallet], add_transfer: ['act.a_transfer', Wallet], transfer: ['act.a_transfer', Wallet],
  add_event: ['act.a_event', CalendarDays], move_event: ['act.a_move_event', CalendarDays], delete_event: ['act.a_delete_event', CalendarDays], skip_event: ['act.a_skip_event', CalendarDays],
  add_task: ['act.a_add_task', CheckSquare], complete_task: ['act.a_complete_task', CheckSquare], add_note: ['act.a_add_note', Brain], add_link: ['act.a_add_link', Link2],
  add_debt: ['act.a_debt', Wallet], pay_debt: ['act.a_pay_debt', Wallet], set_balance: ['act.a_set_balance', Wallet], set_budget: ['act.a_set_budget', Wallet],
  add_recurring: ['act.a_recurring', Wallet], stop_recurring: ['act.a_stop_recurring', Wallet], undo: ['act.a_undo', Undo2], undo_last: ['act.a_undo', Undo2],
  bulk_delete: ['act.a_bulk_delete', Undo2], game_mode: ['act.a_game_mode', Cpu], voice: ['act.a_voice', Sparkles],
}
const VIA = { rules: ['act.via_rules', Zap], ollama: ['act.via_ollama', Cpu], llm: ['act.via_llm', Cloud], gemini: ['act.via_llm', Cloud], none: ['act.via_none', AlertCircle] }
const CH = { tg: 'ch_tg', 'tg-voice': 'ch_tg_voice', voice: 'ch_voice', web: 'ch_web', system: 'ch_system', digest: 'act.ch_digest' }
const fromServer = (h) => h.map((m) => ({ id: m.id, role: m.role === 'user' ? 'me' : 'bot', text: m.text, channel: m.channel, at: m.at, actions: m.actions }))

/* Отмена живёт столько же, сколько в ядре: undo.last_action(max_age_min=24*60) — сутки (D6) */
const UNDO_AGE_MS = 24 * 60 * 60 * 1000
/* что можно отменить кнопкой: clarify/ask_cloud — не действие; undo/undo_last — отметка уже сделанной отмены */
const isUndoable = (a) => a !== 'clarify' && a !== 'ask_cloud' && a !== 'undo' && a !== 'undo_last' && !!ACT[a]
const isUndoMark = (a) => a === 'undo' || a === 'undo_last'
/* убрать отменяемые actions у последнего сообщения с ними (undo_last откатывает именно его) */
const dropLastUndoable = (ms) => {
  let i = -1
  for (let k = ms.length - 1; k >= 0; k--) {
    if (ms[k].role === 'bot' && (ms[k].actions || []).some(isUndoable)) { i = k; break }
  }
  if (i < 0) return ms
  const copy = ms.slice()
  copy[i] = { ...copy[i], actions: copy[i].actions.filter((a) => !isUndoable(a)) }
  return copy
}

/* Подсказки под контекст времени суток — 4 штуки, коротко.
   Это ТО ЖЕ, что уходит в ядро, поэтому строки должны быть понятны модели: оставляем на русском. */
function suggestions() {
  const h = new Date().getHours()
  const base = h < 12 ? ['доброе утро', 'план на неделю'] : h < 18 ? ['итоги недели', 'сколько потратил за неделю'] : ['итоги недели', 'что завтра']   // i18n-raw
  return [...base, 'потратил 700 на такси', 'задача: позвонить маме']   // i18n-raw
}

export default function Chat({ open, onClose, seed }) {
  const { t } = useI18n()
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const box = useRef(null)
  const inp = useRef(null)
  const { tick, bump } = useRefresh()
  const hints = useMemo(suggestions, [open])

  // одна история с Telegram: подгружаем при открытии и при каждом живом обновлении.
  // В истории карточек и actions нет (их отдаёт только живой ответ) — переносим их по совпадению роли и текста,
  // иначе кнопка «отменить последнее действие» гасла бы через один RTT (D6).
  useEffect(() => {
    if (!open) return
    const key = (m) => `${m.role}|${String(m.text || '').replace(/\s*(⚡|🧠|☁️)\s*$/u, '').trim()}`
    api.chatHistory(60).then((h) => {
      setMsgs((prev) => {
        const cards = new Map()
        const acts = new Map()
        for (const p of prev) {
          if (p.card) cards.set(key(p), p.card)
          if (p.actions?.length) acts.set(key(p), p.actions)
        }
        return fromServer(h).map((m) => (m)).reverse().map((m) => {
          const k = key(m)
          const card = cards.has(k) ? cards.get(k) : undefined
          if (card) cards.delete(k)          // карточку вешаем только на последнее подходящее сообщение
          const actions = acts.has(k) ? acts.get(k) : m.actions
          if (acts.has(k)) acts.delete(k)     // …и actions тоже: живём не один RTT
          return { ...m, card, actions }
        }).reverse()
      })
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [open, tick])
  useEffect(() => { box.current?.scrollTo({ top: 1e9, behavior: loaded ? 'smooth' : 'auto' }) }, [msgs, open, busy])
  useEffect(() => { if (open) setTimeout(() => inp.current?.focus(), 60) }, [open])
  useEffect(() => {
    if (!seed?.text) return
    if (seed.send) { setTimeout(() => send(seed.text), 120); return }
    setQ(seed.text); setTimeout(() => { inp.current?.focus(); const el = inp.current; if (el) el.setSelectionRange(el.value.length, el.value.length) }, 80)
  }, [seed?.n]) // eslint-disable-line
  useEffect(() => {
    if (!open) return
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  useEffect(() => { window.dispatchEvent(new CustomEvent('assistant:busy', { detail: busy })) }, [busy])

  // предложенный факт из последнего ответа (suggest_fact) — тост «Запомнить?» с кнопками да/нет
  const [sg, setSg] = useState(null)
  useEffect(() => {
    if (!sg) return
    const t = setTimeout(() => setSg((cur) => (cur === sg ? null : cur)), 45000)   // сам гаснет, если не трогают
    return () => clearTimeout(t)
  }, [sg])
  const decideSg = async (yes) => {
    const s = sg
    setSg(null)
    if (!s) return
    try {
      await fetch(yes ? '/api/memory/confirm' : '/api/memory/dismiss', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: s.text, category: s.category, fact_id: s.fact_id }),
      })
      if (yes) bump()                 // факт подтверждён — страницы «память» и сводки перечитываем
    } catch {}
  }

  const send = async (text) => {
    text = (text ?? q).trim(); if (!text || busy) return
    setQ(''); if (inp.current) inp.current.style.height = ''
    setMsgs((m) => [...m, { role: 'me', text, channel: 'web', at: new Date().toISOString() }]); setBusy(true)
    let streamed = false
    try {
      const r = await chatStream(text, (piece) => {
        setMsgs((m) => {
          const last = m[m.length - 1]
          if (streamed && last?.streaming) return [...m.slice(0, -1), { ...last, text: last.text + piece }]
          streamed = true
          return [...m, { role: 'bot', text: piece, channel: 'web', streaming: true, at: new Date().toISOString() }]
        })
      })
      setMsgs((m) => (streamed && m[m.length - 1]?.streaming ? m.slice(0, -1) : m).concat({ role: 'bot', text: r.text, via: r.via, actions: r.actions, card: r.card, channel: 'web', at: new Date().toISOString() }))
      setSg(r.suggest_fact || null)   // тост «Запомнить?» — только к свежему ответу, старый гасим
      // команда «отмена» пришла ответом — гасим отменяемые actions у прежнего сообщения,
      // иначе кнопка в шапке переживёт уже сделанную отмену
      if (r.actions?.some(isUndoMark)) setMsgs(dropLastUndoable)
      if (r.actions?.length) bump()
    } catch (e) {
      const denied = e?.status === 401
      setMsgs((m) => (streamed && m[m.length - 1]?.streaming ? m.slice(0, -1) : m).concat({
        role: 'bot', via: 'none', channel: 'web', retry: denied ? null : text, at: new Date().toISOString(),
        text: denied ? e.message : t('chat.core_down'),
      }))
    } finally { setBusy(false) }
  }

  const undo = async () => {
    if (busy) return
    setBusy(true)
    try {
      const r = await api.undo()
      setMsgs((m) => [...m, { role: 'bot', text: r.text, via: 'rules', channel: 'web', at: new Date().toISOString(), actions: r.ok ? ['undo'] : [] }])
      // ответ /api/undo в истории сервера не живёт — вычищаем actions у отменённого
      // сообщения, иначе после перезагрузки ленты кнопка «отменить» воскреснет
      if (r.ok) { setMsgs(dropLastUndoable); bump() }
    } catch {} finally { setBusy(false) }
  }

  // свежее неотменённое отменяемое действие: последнее сообщение с такими actions
  // (отметка undo мы её вычищает через dropLastUndoable) — кнопка живёт не один RTT (D6)
  const pendingUndo = [...msgs].reverse().find((m) => m.role === 'bot' && (m.actions || []).some(isUndoable))
  const undoAge = pendingUndo?.at ? Date.now() - Date.parse(pendingUndo.at) : 0
  const canUndo = !!pendingUndo && !(Number.isFinite(undoAge) && undoAge > UNDO_AGE_MS)

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() }
  }
  const grow = (el) => { el.style.height = ''; el.style.height = Math.min(160, el.scrollHeight) + 'px' }

  const [shown, closing] = useSheetPresence(open)
  if (!shown) return null
  return (
    <div className={`sheet-backdrop ${closing ? 'closing' : ''} sm:!items-end sm:!justify-end sm:!p-4`} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="elevated chat-panel flex h-[calc(92dvh/var(--ui-zoom))] w-full flex-col !rounded-t-4xl !rounded-b-none sm:h-[min(760px,calc(100vh/var(--ui-zoom)-32px))] sm:w-[440px] sm:!rounded-[24px]" style={{ animation: 'rise .3s var(--ease-out) both' }}>
        <div className="sheet-grip" aria-hidden="true" />
        {/* шапка */}
        <div className="flex items-center justify-between gap-3 border-b hair px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className={`inline-block h-2 w-2 rounded-full ${busy ? 'dot-live' : ''}`} style={{ background: busy ? 'var(--accent)' : 'var(--pos)', color: 'var(--accent)' }} />
            <div>
              <div className="text-[14px] font-semibold tracking-[-0.02em]">{aName()}</div>
              <div className="faint text-[11.5px] leading-none">{busy ? t('chat.thinking') : t('chat.one_history')}</div>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            {canUndo && <button className="btn-ghost btn-sm" onClick={undo} data-tip={t('chat.undo_tip')}><Undo2 size={13} /> {t('common.undo')}</button>}
            <button className="btn-icon !h-8 !w-8" onClick={onClose} aria-label={t('common.close')}><X size={16} /></button>
          </div>
        </div>

        {/* лента */}
        <div ref={box} className="scroll-thin flex-1 overflow-y-auto overscroll-contain px-4 py-3">
          {!loaded && <div className="space-y-3 pt-2">{[70, 45, 60].map((w, i) => <div key={i} className={`fill animate-pulseSoft h-9 rounded-2xl ${i % 2 ? 'ml-auto' : ''}`} style={{ width: `${w}%` }} />)}</div>}
          {loaded && msgs.length === 0 && (
            <div className="flex h-full flex-col items-start justify-end pb-4">
              <div className="h3">{t('chat.hello')}</div>
              <div className="muted mt-1 text-[13.5px] leading-relaxed">{t('chat.hello_hint')}</div>
            </div>
          )}
          {msgs.map((m, i) => {
            const prev = msgs[i - 1]
            const newDay = m.at && (!prev?.at || !isSameDay(prev.at, m.at))
            const grouped = prev && prev.role === m.role && !newDay
            const next = msgs[i + 1]
            // время показываем в конце серии сообщений одного автора (как в мессенджерах)
            const showMeta = !next || next.role !== m.role || (next.at && m.at && new Date(next.at) - new Date(m.at) > 5 * 60000)
            return (
              <div key={m.id || i}>
                {newDay && <div className="my-3 flex items-center gap-3"><span className="rule flex-1" /><span className="label !text-[10px]">{dayLabel(m.at)}</span><span className="rule flex-1" /></div>}
                <Message m={m} grouped={grouped} showMeta={showMeta} onRetry={send} />
              </div>
            )
          })}
          {busy && !msgs[msgs.length - 1]?.streaming && (
            <div className="mt-2 flex items-center gap-2.5">
              <span className="msg-bot px-3.5 py-2.5" style={{ background: 'var(--bubble)' }}><span className="thinking flex items-center gap-1 text-accent"><span /><span /><span /></span></span>
              <span className="faint text-[11.5px]">{t('chat.thinks', { name: lower() })}</span>
            </div>
          )}
        </div>

        {/* композер */}
        <div className="px-3 pb-3 pt-1 safe-b">
          {msgs.length < 3 && (
            <div className="no-scrollbar mb-2 flex gap-1.5 overflow-x-auto px-1">
              {hints.map((h) => <button key={h} onClick={() => send(h)} className="chip shrink-0 !py-1.5 hover:text-accent">{h}</button>)}
            </div>
          )}
          {sg && (
            <div className="act-card mb-2">
              <span className="act-ic"><Brain size={14} strokeWidth={2.6} /></span>
              <span className="font-medium">{t('chat.remember_q', { text: sg.text })}</span>
              <button className="btn-ghost btn-sm ml-auto" onClick={() => decideSg(true)}><Check size={13} strokeWidth={2.6} /> {t('common.yes')}</button>
              <button className="btn-ghost btn-sm" onClick={() => decideSg(false)}><X size={13} strokeWidth={2.6} /> {t('common.no')}</button>
            </div>
          )}
          <form onSubmit={(e) => { e.preventDefault(); send() }} className="composer flex items-end gap-2 py-2 pl-4 pr-2">
            <textarea ref={inp} rows={1} value={q} onChange={(e) => { setQ(e.target.value); grow(e.target) }} onKeyDown={onKey} placeholder={t('chat.placeholder', { name: dat() })} className="max-h-40 py-1.5" />
            <button type="submit" disabled={!q.trim() || busy} className="btn-primary grid !h-9 !w-9 shrink-0 !rounded-full !p-0" aria-label={t('chat.send')}><ArrowUp size={16} strokeWidth={2.4} /></button>
          </form>
          <div className="faint mt-1.5 hidden justify-between px-2 text-[10.5px] sm:flex"><span><span className="kbd">↵</span> {t('chat.send')} · <span className="kbd">{kbShiftEnter}</span> {t('chat.newline')}</span><span><span className="kbd">esc</span> {t('chat.close')}</span></div>
        </div>
      </div>
    </div>
  )
}


function Message({ m, grouped, showMeta = true, onRetry }) {
  const { t } = useI18n()
  const me = m.role === 'me'
  const acts = [...new Set((m.actions || []).filter((a) => ACT[a]))]
  const clarify = m.actions?.includes('clarify')
  const via = m.via && VIA[m.via]
  const meta = [me ? null : via && m.via !== 'none' ? t(via[0]) : null, m.channel && m.channel !== 'web' ? t('chat.from', { ch: t(CH[m.channel] || m.channel) }) : null, m.at ? hhmm(m.at) : null].filter(Boolean)

  // Ответы LLM остаются на русском — это данные, а не интерфейс. i18n-raw
  const isMorningDigest = !me && /доброе утро/i.test(m.text || '')   // i18n-raw
  const isWeekSummary = !me && /итоги недели|недельный отчёт/i.test(m.text || '')   // i18n-raw

  return (
    <div className={`flex flex-col ${me ? 'items-end' : 'items-start'} ${grouped ? 'mt-1' : 'mt-3'} w-full`}>
      {!me && !grouped && <div className="label mb-1 ml-1 !text-[10px] !tracking-[.06em]">{aName()}</div>}
      
      {isMorningDigest ? (
        <div className="w-full max-w-[94%] sm:max-w-[420px]">
          <MorningDigestCard ownerName={(m.text || '').match(/доброе утро,\s*\**\s*([^\n*]+)/i)?.[1]?.trim()} />   // i18n-raw
        </div>
      ) : isWeekSummary ? (
        <div className="w-full max-w-[94%] sm:max-w-[420px]">
          <WeekSummaryCard />
        </div>
      ) : (
        <div className={`bubble-in ${me ? 'me msg-me' : 'msg-bot'} max-w-[88%] px-3.5 py-2 text-[14.5px] leading-[1.45] ${m.via === 'none' ? 'soft-neg' : ''}`} style={me || m.via === 'none' ? {} : { background: 'var(--bubble)' }}>
          <div className={`md whitespace-pre-wrap ${m.streaming ? 'cursor' : ''}`}>{renderMd(m.text.replace(/\s*(⚡|🧠|☁️)\s*$/u, ''))}</div>
          {m.retry && <button className="btn-ghost btn-sm mt-2" style={{ color: 'inherit', borderColor: 'currentColor' }} onClick={() => onRetry(m.retry)}>{t('chat.retry')} ↻</button>}
        </div>
      )}

      {(m.card || acts.length > 0 || clarify) && (
        <div className="mt-1.5 flex max-w-[88%] flex-col gap-1.5">
          {m.card && (
            <a href={m.card} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-2xl border hair" style={{ boxShadow: '0 12px 28px -16px rgba(0,0,0,.4)' }}>
              <img src={m.card} alt={t('chat.card_alt')} className="block w-full" loading="lazy" />
            </a>
          )}
          {acts.map((a) => { const [label, I] = ACT[a]; return (
            <div key={a} className="act-card bubble-in">
              <span className="act-ic"><Check size={14} strokeWidth={2.6} /></span>
              <span className="font-medium">{t(label)}</span>
              <I size={14} className="faint ml-auto" />
            </div>
          ) })}
          {clarify && !acts.length && <div className="act-card bubble-in"><span className="act-ic soft-warn"><HelpCircle size={14} /></span><span className="muted">{t('chat.waiting')}</span></div>}
        </div>
      )}
      {meta.length > 0 && showMeta && <div className={`faint mt-1 text-[10.5px] ${me ? 'mr-1' : 'ml-1'}`}>{meta.join(' · ')}</div>}
    </div>
  )
}

/* Лёгкий markdown: абзацы, списки, ```код```, `код`, **жирный**, *курсив*, ссылки */
export function renderMd(text) {
  const src = String(text || '')
  const blocks = src.split(/(```[\s\S]*?```)/g)
  return blocks.map((b, bi) => {
    if (/^```/.test(b)) return <pre key={bi}><code>{b.replace(/^```[a-z]*\n?/, '').replace(/```$/, '')}</code></pre>
    const lines = b.split('\n')
    const out = []; let list = null
    const flush = () => { if (list) { out.push(<ul key={out.length}>{list}</ul>); list = null } }
    lines.forEach((ln, li) => {
      const m = ln.match(/^\s*(?:[-•*]|\d+[.)])\s+(.*)$/)
      if (m) { (list ||= []).push(<li key={li}>{inline(m[1])}</li>); return }
      flush()
      out.push(<span key={li}>{inline(ln)}{li < lines.length - 1 ? '\n' : ''}</span>)
    })
    flush()
    return <span key={bi}>{out}</span>
  })
}
function inline(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`\n]+`|(?<![\w*])\*[^*\n]+\*(?![\w*])|https?:\/\/[^\s)]+)/g)
  return parts.map((p, i) => {
    if (/^\*\*[^*]+\*\*$/.test(p)) return <b key={i} className="font-semibold">{p.slice(2, -2)}</b>
    if (/^`[^`]+`$/.test(p)) return <code key={i}>{p.slice(1, -1)}</code>
    if (/^\*[^*]+\*$/.test(p)) return <i key={i}>{p.slice(1, -1)}</i>
    if (/^https?:\/\//.test(p)) return <a key={i} href={p} target="_blank" rel="noreferrer">{p.replace(/^https?:\/\//, '').slice(0, 48)}</a>
    return p
  })
}
