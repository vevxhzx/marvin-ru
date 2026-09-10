import { useSheetPresence } from './ui'
import { lower, name as aName, dat } from '../lib/name'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, X, Undo2, Check, CalendarDays, CheckSquare, Wallet, Brain, Cloud, Zap, Cpu, AlertCircle, HelpCircle, Link2, Sparkles } from 'lucide-react'
import { chatStream, api, dayLabel, hhmm, isSameDay, kbShiftEnter } from '../lib/api'
import { useRefresh } from '../App'

/* Что реально сделал ассистент — карточка результата, а не технический лог */
export const ACT = {
  add_expense: ['трата записана', Wallet], add_income: ['доход записан', Wallet], add_transfer: ['перевод проведён', Wallet], transfer: ['перевод проведён', Wallet],
  add_event: ['событие в календаре', CalendarDays], move_event: ['событие перенесено', CalendarDays], delete_event: ['событие удалено', CalendarDays], skip_event: ['пропуск отмечен', CalendarDays],
  add_task: ['задача добавлена', CheckSquare], complete_task: ['задача закрыта', CheckSquare], add_note: ['мысль сохранена', Brain], add_link: ['ссылка сохранена', Link2],
  add_debt: ['долг добавлен', Wallet], pay_debt: ['платёж по долгу', Wallet], set_balance: ['баланс сверен', Wallet], set_budget: ['бюджет задан', Wallet],
  add_recurring: ['регулярный платёж', Wallet], stop_recurring: ['платёж остановлен', Wallet], undo: ['отменено', Undo2], undo_last: ['отменено', Undo2],
  bulk_delete: ['удалено пачкой', Undo2], game_mode: ['режим переключён', Cpu], voice: ['голос сменён', Sparkles],
}
const VIA = { rules: ['правила', Zap], ollama: ['локально', Cpu], gemini: ['облако', Cloud], none: ['сбой', AlertCircle] }
const CH = { tg: 'telegram', 'tg-voice': 'telegram · голос', voice: 'голос', web: 'сайт', system: 'авто' }
const fromServer = (h) => h.map((m) => ({ id: m.id, role: m.role === 'user' ? 'me' : 'bot', text: m.text, channel: m.channel, at: m.at }))

/* Подсказки под контекст времени суток — 4 штуки, коротко */
function suggestions() {
  const h = new Date().getHours()
  const base = h < 12 ? ['что сегодня', 'план на неделю'] : h < 18 ? ['что сегодня', 'сколько потратил за неделю'] : ['что завтра', 'итоги дня']
  return [...base, 'потратил 700 на такси', 'задача: позвонить маме']
}

export default function Chat({ open, onClose, seed }) {
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const box = useRef(null)
  const inp = useRef(null)
  const { tick, bump } = useRefresh()
  const hints = useMemo(suggestions, [open])

  // одна история с Telegram: подгружаем при открытии и при каждом живом обновлении
  useEffect(() => {
    if (!open) return
    api.chatHistory(60).then((h) => { setMsgs(fromServer(h)); setLoaded(true) }).catch(() => setLoaded(true))
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
      setMsgs((m) => (streamed && m[m.length - 1]?.streaming ? m.slice(0, -1) : m).concat({ role: 'bot', text: r.text, via: r.via, actions: r.actions, channel: 'web', at: new Date().toISOString() }))
      if (r.actions?.length) bump()
    } catch (e) {
      const denied = e?.status === 401
      setMsgs((m) => (streamed && m[m.length - 1]?.streaming ? m.slice(0, -1) : m).concat({
        role: 'bot', via: 'none', channel: 'web', retry: denied ? null : text, at: new Date().toISOString(),
        text: denied ? e.message : 'Ядро не ответило. Если start.bat запущен — просто повторите: ничего не потерялось.',
      }))
    } finally { setBusy(false) }
  }

  const undo = async () => {
    if (busy) return
    setBusy(true)
    try {
      const r = await api.undo()
      setMsgs((m) => [...m, { role: 'bot', text: r.text, via: 'rules', channel: 'web', at: new Date().toISOString(), actions: r.ok ? ['undo'] : [] }])
      if (r.ok) bump()
    } catch {} finally { setBusy(false) }
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() }
  }
  const grow = (el) => { el.style.height = ''; el.style.height = Math.min(160, el.scrollHeight) + 'px' }

  const [shown, closing] = useSheetPresence(open)
  if (!shown) return null
  const lastBot = [...msgs].reverse().find((m) => m.role === 'bot')
  const canUndo = lastBot?.actions?.some((a) => a !== 'clarify' && a !== 'ask_cloud' && ACT[a])
  return (
    <div className={`sheet-backdrop ${closing ? 'closing' : ''} sm:!items-end sm:!justify-end sm:!p-4`} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="elevated flex h-[92dvh] w-full flex-col !rounded-t-4xl !rounded-b-none sm:h-[min(760px,calc(100vh-32px))] sm:w-[440px] sm:!rounded-[24px]" style={{ animation: 'rise .3s var(--ease-out) both' }}>
        {/* шапка */}
        <div className="flex items-center justify-between gap-3 border-b hair px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className={`inline-block h-2 w-2 rounded-full ${busy ? 'dot-live' : ''}`} style={{ background: busy ? 'var(--accent)' : 'var(--pos)', color: 'var(--accent)' }} />
            <div>
              <div className="text-[14px] font-semibold tracking-[-0.02em]">{aName()}</div>
              <div className="faint text-[11.5px] leading-none">{busy ? 'думаю…' : 'одна история с telegram'}</div>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            {canUndo && <button className="btn-ghost btn-sm" onClick={undo} data-tip="отменить последнее действие"><Undo2 size={13} /> отменить</button>}
            <button className="btn-icon !h-8 !w-8" onClick={onClose} aria-label="Закрыть"><X size={16} /></button>
          </div>
        </div>

        {/* лента */}
        <div ref={box} className="scroll-thin flex-1 overflow-y-auto px-4 py-3">
          {!loaded && <div className="space-y-3 pt-2">{[70, 45, 60].map((w, i) => <div key={i} className={`fill animate-pulseSoft h-9 rounded-2xl ${i % 2 ? 'ml-auto' : ''}`} style={{ width: `${w}%` }} />)}</div>}
          {loaded && msgs.length === 0 && (
            <div className="flex h-full flex-col items-start justify-end pb-4">
              <div className="h3">Слушаю, сэр.</div>
              <div className="muted mt-1 text-[13.5px] leading-relaxed">Пишите как человеку: «ужин в 7», «потратил 700 на такси», «что завтра». Всё, что я сделаю, покажу карточкой под ответом.</div>
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
              <span className="faint text-[11.5px]">{lower()} думает</span>
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
          <form onSubmit={(e) => { e.preventDefault(); send() }} className="composer flex items-end gap-2 py-2 pl-4 pr-2">
            <textarea ref={inp} rows={1} value={q} onChange={(e) => { setQ(e.target.value); grow(e.target) }} onKeyDown={onKey} placeholder={`сказать ${dat()}…`} className="max-h-40 py-1.5" />
            <button type="submit" disabled={!q.trim() || busy} className="btn-primary grid !h-9 !w-9 shrink-0 !rounded-full !p-0" aria-label="Отправить"><ArrowUp size={16} strokeWidth={2.4} /></button>
          </form>
          <div className="faint mt-1.5 hidden justify-between px-2 text-[10.5px] sm:flex"><span><span className="kbd">↵</span> отправить · <span className="kbd">{kbShiftEnter}</span> новая строка</span><span><span className="kbd">esc</span> закрыть</span></div>
        </div>
      </div>
    </div>
  )
}


function Message({ m, grouped, showMeta = true, onRetry }) {
  const me = m.role === 'me'
  const acts = [...new Set((m.actions || []).filter((a) => ACT[a]))]
  const clarify = m.actions?.includes('clarify')
  const via = m.via && VIA[m.via]
  const meta = [me ? null : via && m.via !== 'none' ? via[0] : null, m.channel && m.channel !== 'web' ? `из ${CH[m.channel] || m.channel}` : null, m.at ? hhmm(m.at) : null].filter(Boolean)
  return (
    <div className={`flex flex-col ${me ? 'items-end' : 'items-start'} ${grouped ? 'mt-1' : 'mt-3'}`}>
      {!me && !grouped && <div className="label mb-1 ml-1 !text-[10px] !tracking-[.06em]">{aName()}</div>}
      <div className={`bubble-in ${me ? 'me msg-me' : 'msg-bot'} max-w-[88%] px-3.5 py-2 text-[14.5px] leading-[1.45] ${m.via === 'none' ? 'soft-neg' : ''}`} style={me || m.via === 'none' ? {} : { background: 'var(--bubble)' }}>
        <div className={`md whitespace-pre-wrap ${m.streaming ? 'cursor' : ''}`}>{renderMd(m.text.replace(/\s*(⚡|🧠|☁️)\s*$/u, ''))}</div>
        {m.retry && <button className="btn-ghost btn-sm mt-2" style={{ color: 'inherit', borderColor: 'currentColor' }} onClick={() => onRetry(m.retry)}>повторить ↻</button>}
      </div>
      {(acts.length > 0 || clarify) && (
        <div className="mt-1.5 flex max-w-[88%] flex-col gap-1.5">
          {acts.map((a) => { const [label, I] = ACT[a]; return (
            <div key={a} className="act-card bubble-in">
              <span className="act-ic"><Check size={14} strokeWidth={2.6} /></span>
              <span className="font-medium">{label}</span>
              <I size={14} className="faint ml-auto" />
            </div>
          ) })}
          {clarify && !acts.length && <div className="act-card bubble-in"><span className="act-ic soft-warn"><HelpCircle size={14} /></span><span className="muted">жду вашего ответа</span></div>}
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
