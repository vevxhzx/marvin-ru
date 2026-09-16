import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, CalendarDays, CheckSquare, Wallet, FileText, Link2, MessageCircle, Cpu, ArrowUpRight, X, Pencil, Check, Star, RotateCcw, Plus } from 'lucide-react'
import { api, hhmm, dayLabel, shortDate, plural } from '../lib/api'
import { Empty, Seg, PageHead, ListSkeleton, Pills, toast } from '../components/ui'
import { useRefresh } from '../App'
import { name as aName } from '../lib/name'

/* Память — четыре вкладки: «сейчас» (свежее, живёт неделю), «о вас» (надолго + портрет), «события» (журнал
   всего, что ассистент понял и сделал) и «архив» (забытое и устаревшее — ничего не стирается, всё можно вернуть). */
const TABS = [['short', 'сейчас'], ['long', 'о вас'], ['journal', 'события'], ['archive', 'архив']]

export default function Memory() {
  const [tab, setTab] = useState('long')
  const [data, setData] = useState(null)
  const { tick } = useRefresh()
  const load = () => api.facts().then(setData).catch(() => setData({ items: [], stats: {}, enabled: false, categories: [] }))
  useEffect(() => { load() }, [tick])
  const st = data?.stats || {}
  const counts = { short: st.short, long: st.long, archive: st.archive }
  return (
    <div className="space-y-8">
      <PageHead kicker={`что ${aName().toLowerCase()} о вас знает и помнит`} title="память" />
      <div className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1 animate-rise">
        {TABS.map(([id, l]) => (
          <button key={id} onClick={() => setTab(id)} className={`pill shrink-0 ${tab === id ? 'on' : ''}`}>
            {l}{counts[id] ? <span className="idx !text-[10px] opacity-60">{counts[id]}</span> : null}
          </button>
        ))}
      </div>
      {tab === 'journal' ? <Journal /> : <Facts layer={tab} data={data} reload={load} />}
    </div>
  )
}

const CATS = { 'о человеке': 'var(--accent)', 'предпочтение': '#7c3aed', 'здоровье': 'var(--neg)', 'работа': 'var(--warn)', 'быт': 'var(--ink-3)', 'отношения': '#db2777', 'привычка': 'var(--pos)' }
const ago = (iso) => {
  if (!iso) return ''
  const d = Math.floor((Date.now() - new Date(iso)) / 864e5)
  return d <= 0 ? 'сегодня' : d === 1 ? 'вчера' : `${d} ${plural(d, 'день', 'дня', 'дней')} назад`
}

function Facts({ layer, data, reload }) {
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  if (!data) return <ListSkeleton n={5} />
  const st = data.stats || {}
  const items = (data.items || []).filter((f) => f.layer === layer).sort((a, b) => (b.core - a.core) || (new Date(b.updated_at) - new Date(a.updated_at)))
  const run = async (fn, ok) => { setBusy(true); try { await fn(); ok && toast(ok); await reload() } catch (e) { toast('Не вышло', { sub: e.message, kind: 'err' }) } finally { setBusy(false) } }
  const add = () => { const t = draft.trim(); if (!t) return; run(() => api.addFact({ text: t, layer: layer === 'archive' ? 'long' : layer }), 'Запомнил').then(() => { setDraft(''); setAdding(false) }) }
  const sub = { short: 'Свежее из разговоров. Через неделю сам решу: оставить надолго или в архив.', long: 'То, что я знаю о вас надолго. Звёздочка — всегда в голове, даже когда тема другая.', archive: 'Забытое, устаревшее и старые версии фактов. Ничего не стирается — можно вернуть.' }[layer]

  return (
    <div className="space-y-6 animate-rise">
      {!data.enabled && <div className="rule"><div className="row"><span className="muted text-[13.5px]">Память о вас выключена в настройках (brain.memory.enabled). Записи ниже — то, что было собрано раньше.</span></div></div>}

      {layer === 'long' && (
        <section>
          <div className="mb-1.5 flex items-baseline justify-between gap-2">
            <div className="label">портрет</div>
            <span className="faint text-[11px]">{st.portrait_at ? `собран ${ago(st.portrait_at)}` : 'ещё не собран'}</span>
          </div>
          <div className="panel p-4 sm:p-5">
            {st.portrait ? (
              <div className="whitespace-pre-line text-[14.5px] leading-relaxed">{st.portrait}</div>
            ) : <div className="muted text-[13.5px]">Соберу, когда наберётся хотя бы три факта «о вас». Или нажмите кнопку — соберу из того, что есть.</div>}
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
              <button className="text-accent hover:underline disabled:opacity-40" disabled={busy || (st.long || 0) < 3} onClick={() => run(() => api.rebuildPortrait(), 'Портрет пересобран')}>пересобрать портрет</button>
              <span className="faint">· пересобирается сам раз в неделю</span>
            </div>
          </div>
        </section>
      )}

      {layer === 'long' && <StyleBlock st={st} busy={busy} run={run} />}

      <section>
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          <div className="label">{items.length} {plural(items.length, 'факт', 'факта', 'фактов')}</div>
          <div className="flex items-center gap-3 text-[12px]">
            {layer === 'short' && items.length > 0 && <button className="text-accent hover:underline disabled:opacity-40" disabled={busy} onClick={() => run(() => api.memoryTidy(), 'Убрался')}>убраться сейчас</button>}
            {layer !== 'archive' && <button className="text-accent flex items-center gap-1 hover:underline" onClick={() => setAdding((v) => !v)}><Plus size={12} /> добавить</button>}
          </div>
        </div>
        {sub && <div className="muted mb-3 text-[13px]">{sub}</div>}
        {adding && (
          <div className="composer mb-3 flex items-center gap-2 py-1.5 pl-4 pr-2">
            <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add(); if (e.key === 'Escape') setAdding(false) }}
              className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder="Например: не ем мясо · работаю по ночам · у меня кот Барсик" />
            <button className="btn-primary btn-sm" disabled={!draft.trim() || busy} onClick={add}>запомнить</button>
          </div>
        )}
        {items.length === 0 ? (
          <div className="rule"><Empty glyph="memory" text="Пусто" sub={{ short: 'Появится само из разговоров — я замечаю, что вы о себе рассказываете', long: 'Скажите в чате «запомни, что у меня…» или добавьте здесь', archive: 'Сюда попадает то, что вы попросили забыть, и старые версии фактов' }[layer]} /></div>
        ) : (
          <div className="rule">
            {items.map((f) => <FactRow key={f.id} f={f} busy={busy} run={run} cats={data.categories} />)}
          </div>
        )}
      </section>

      {layer === 'long' && <Lessons />}
    </div>
  )
}

/* «Как вы пишете» — 3–5 строк о стиле, собирается раз в неделю из ваших реплик; правится руками */
function StyleBlock({ st, busy, run }) {
  const [edit, setEdit] = useState(false)
  const [text, setText] = useState(st.style || '')
  useEffect(() => { if (!edit) setText(st.style || '') }, [st.style, edit])
  const save = () => run(() => api.setStyle(text), 'Стиль поправлен').then(() => setEdit(false))
  return (
    <section>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <div className="label">как вы пишете</div>
        <span className="faint text-[11px]">{st.style_at ? `подмечено ${ago(st.style_at)}` : 'ещё не подмечал'}</span>
      </div>
      <div className="panel p-4 sm:p-5">
        {edit ? (
          <textarea autoFocus value={text} onChange={(e) => setText(e.target.value)} rows={5} className="input !h-auto w-full resize-none py-2 text-[14px] leading-relaxed" placeholder="— коротко, по делу, без воды" />
        ) : st.style ? (
          <div className="whitespace-pre-line text-[14.5px] leading-relaxed">{st.style}</div>
        ) : <div className="muted text-[13.5px]">Подмечу сам, когда наберётся хотя бы 20 ваших реплик: длина фраз, тон, любимые слова, что вы как называете. Под это подстраиваются ответы.</div>}
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
          {edit ? (
            <>
              <button className="text-accent hover:underline" disabled={busy} onClick={save}>сохранить</button>
              <button className="muted hover:underline" onClick={() => setEdit(false)}>отмена</button>
            </>
          ) : (
            <>
              <button className="text-accent hover:underline disabled:opacity-40" disabled={busy} onClick={() => run(() => api.rebuildStyle(), 'Подметил заново')}>подметить заново</button>
              <button className="text-accent hover:underline" onClick={() => setEdit(true)}>поправить</button>
              <span className="faint">· обновляется сам раз в неделю</span>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

/* Уроки — на чём переучился: «сайт 15000» → доход. Крестик — забыть урок */
const LESSON_RU = { expense: 'трата', income: 'доход', debt: 'долг', order: 'заказ', task: 'задача', event: 'событие', note: 'заметка', mute: 'не напоминать' }
function Lessons() {
  const [items, setItems] = useState(null)
  const load = () => api.lessons().then(setItems).catch(() => setItems([]))
  useEffect(() => { load() }, [])
  if (!items || items.length === 0) return null
  const del = async (id) => { try { await api.delLesson(id); toast('Урок забыт'); load() } catch (e) { toast('Не вышло', { sub: e.message, kind: 'err' }) } }
  return (
    <section>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <div className="label">чему научился</div>
        <span className="faint text-[11px]">{items.length} {plural(items.length, 'урок', 'урока', 'уроков')}</span>
      </div>
      <div className="muted mb-3 text-[13px]">Ваши поправки «это заказ», «это долг» и «не надо про это». Похожую фразу в следующий раз пойму сразу.</div>
      <div className="rule">
        {items.map((l) => (
          <div key={l.id} className="row group">
            <div className="min-w-0 flex-1 text-[14px]">
              <span className="truncate">«{l.text}»</span>
              <span className="faint"> → </span>
              <span className="muted">{LESSON_RU[l.kind] || l.kind}</span>
              {l.wrong && <span className="faint text-[12px]"> (было: {LESSON_RU[l.wrong] || l.wrong})</span>}
            </div>
            {l.uses > 0 && <span className="faint hidden shrink-0 text-[11px] sm:block">пригодился {l.uses}</span>}
            <button className="btn-icon !h-7 !w-7 shrink-0" onClick={() => del(l.id)} aria-label="Забыть урок"><X size={13} /></button>
          </div>
        ))}
      </div>
    </section>
  )
}

function FactRow({ f, busy, run, cats }) {
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState(false)
  const [text, setText] = useState(f.text)
  const save = () => { const t = text.trim(); if (!t || t === f.text) return setEdit(false); run(() => api.updateFact(f.id, { text: t }), 'Поправил').then(() => setEdit(false)) }
  const color = CATS[f.category] || 'var(--ink-3)'
  return (
    <div className={`row cursor-pointer !items-start ${open ? '' : 'row-hover'}`} onClick={() => !edit && setOpen((v) => !v)} style={open ? { background: 'var(--fill)' } : {}}>
      <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />
      <div className="min-w-0 flex-1">
        {edit ? (
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <input autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { setText(f.text); setEdit(false) } }} className="input !h-9" />
            <button className="btn-icon !h-8 !w-8" onClick={save} aria-label="Сохранить"><Check size={14} /></button>
          </div>
        ) : (
          <div className={`text-[14.5px] leading-snug ${open ? '' : 'truncate'}`}>{f.core && <Star size={12} className="mr-1 inline -mt-0.5" style={{ color: 'var(--warn)', fill: 'var(--warn)' }} />}{f.text}</div>
        )}
        {open && !edit && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px]" style={{ animation: 'fade .16s ease-out' }} onClick={(e) => e.stopPropagation()}>
            <span className="muted">{f.category}</span>
            <span className="faint">· {ago(f.updated_at || f.created_at)}</span>
            {f.uses > 0 && <span className="faint">· пригодился {f.uses} {plural(f.uses, 'раз', 'раза', 'раз')}</span>}
            {f.layer === 'archive' && f.archive_reason && <span className="faint">· {f.archive_reason}{f.replaced_by ? ` → #${f.replaced_by}` : ''}</span>}
            {f.layer !== 'archive' ? (
              <>
                <button className="text-accent flex items-center gap-1 hover:underline" disabled={busy} onClick={() => setEdit(true)}><Pencil size={12} /> поправить</button>
                <button className="text-accent flex items-center gap-1 hover:underline" disabled={busy} onClick={() => run(() => api.updateFact(f.id, { core: !f.core }), f.core ? 'Больше не в ядре' : 'Теперь всегда в голове')}><Star size={12} /> {f.core ? 'не так важно' : 'это важно'}</button>
                {f.layer === 'short' && <button className="text-accent hover:underline" disabled={busy} onClick={() => run(() => api.updateFact(f.id, { layer: 'long' }), 'Оставил надолго')}>оставить надолго</button>}
                <button className="hover:underline" style={{ color: 'var(--neg)' }} disabled={busy} onClick={() => run(() => api.forgetFact(f.id), 'Забыл — лежит в архиве')}>забыть</button>
              </>
            ) : (
              <button className="text-accent flex items-center gap-1 hover:underline" disabled={busy} onClick={() => run(() => api.restoreFact(f.id), 'Вернул')}><RotateCcw size={12} /> вернуть</button>
            )}
            {f.layer !== 'archive' && <Pills className="w-full" value={f.category} onChange={(c) => c !== f.category && run(() => api.updateFact(f.id, { category: c }))} options={(cats || []).map((c) => [c, c])} />}
          </div>
        )}
      </div>
      {!open && <span className="faint hidden shrink-0 text-[11px] sm:block">{ago(f.updated_at || f.created_at)}</span>}
    </div>
  )
}

/* ---------------- события: журнал всего, что ассистент понял и сделал ---------------- */
const KINDS = [
  { id: '', label: 'всё' },
  { id: 'event', label: 'события', icon: CalendarDays, color: 'var(--accent)', to: '/calendar' },
  { id: 'task', label: 'задачи', icon: CheckSquare, color: 'var(--pos)', to: '/tasks' },
  { id: 'finance', label: 'деньги', icon: Wallet, color: 'var(--warn)', to: '/finance' },
  { id: 'note', label: 'мысли', icon: FileText, color: '#7c3aed', to: '/mind' },
  { id: 'link', label: 'ссылки', icon: Link2, color: '#0891b2', to: '/mind' },
  { id: 'chat', label: 'разговор', icon: MessageCircle, color: 'var(--ink-3)' },
  { id: 'system', label: 'система', icon: Cpu, color: 'var(--ink-3)' },
]
const K = Object.fromEntries(KINDS.map((k) => [k.id, k]))
const CH = { tg: 'telegram', 'tg-voice': 'telegram · голос', voice: 'голос', web: 'сайт', system: 'авто', test: 'тест' }
const clean = (s) => s.replace(/^(Мысль|Задача|Запланировано|Трата|Доход|Регулярный платёж|Ссылка):\s*/i, '')

function Journal() {
  const [kind, setKind] = useState('')
  const [days, setDays] = useState(30)
  const [q, setQ] = useState('')
  const [items, setItems] = useState(null)
  const [openId, setOpenId] = useState(null)
  const { tick } = useRefresh()

  useEffect(() => {
    const t = setTimeout(() => api.memory(days, kind || undefined, q || undefined).then(setItems).catch(() => setItems([])), q ? 250 : 0)
    return () => clearTimeout(t)
  }, [kind, days, q, tick])

  const counts = useMemo(() => { const c = {}; for (const x of items || []) c[x.kind] = (c[x.kind] || 0) + 1; return c }, [items])
  const groups = useMemo(() => {
    const m = new Map()
    for (const x of items || []) { const k = new Date(x.created_at).toDateString(); if (!m.has(k)) m.set(k, []); m.get(k).push(x) }
    return [...m.entries()]
  }, [items])

  const n = (items || []).length
  return (
    <div className="space-y-6">
      {/* поиск + категории */}
      <div className="animate-rise space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="label">{n} {plural(n, 'запись', 'записи', 'записей')}</div>
          <Seg value={days} onChange={setDays} options={[[7, '7 дн'], [30, '30 дн'], [365, 'год']]} />
        </div>
        <div className="composer flex items-center gap-2 py-1.5 pl-4 pr-2">
          <Search size={16} className="faint shrink-0" />
          <input value={q} onChange={(e) => setQ(e.target.value)} className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder="Когда у меня была встреча с… / сколько на такси…" />
          {q && <button className="btn-icon !h-8 !w-8" onClick={() => setQ('')} aria-label="Очистить"><X size={14} /></button>}
        </div>
        <div className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1">
          {KINDS.map((k) => (
            <button key={k.id} onClick={() => setKind(k.id)} className={`pill shrink-0 ${kind === k.id ? 'on' : ''}`}>
              {k.icon && <span className="h-1.5 w-1.5 rounded-full" style={{ background: kind === k.id ? 'currentColor' : k.color }} />}
              {k.label}{k.id && counts[k.id] && !kind ? <span className="idx !text-[10px] opacity-60">{counts[k.id]}</span> : null}
            </button>
          ))}
        </div>
      </div>

      {!items ? <ListSkeleton n={6} /> : groups.length === 0 ? (
        <div className="rule"><Empty glyph="memory" text={q ? 'Ничего не нашёл' : 'Пусто'} sub={q ? 'Попробуйте другими словами — я ищу по смыслу, а не по буквам' : 'Всё, что вы говорите ассистенту, появится здесь с датой и источником'} hint={q ? undefined : 'мысль: идея для проекта'} /></div>
      ) : (
        <div className="space-y-7">
          {groups.map(([day, list]) => (
            <section key={day} className="animate-rise">
              <div className="mb-1.5 flex items-baseline gap-2"><div className="label">{dayLabel(day)}</div><span className="faint text-[11px]">{shortDate(day)} · {list.length} {plural(list.length, 'запись', 'записи', 'записей')}</span></div>
              <div className="rule">
                {list.map((m) => <Entry key={m.id} m={m} open={openId === m.id} onToggle={() => setOpenId(openId === m.id ? null : m.id)} />)}
              </div>
            </section>
          ))}
          {n >= 300 && <div className="faint text-center text-[12px]">показаны последние 300 — уточните поиск или период</div>}
        </div>
      )}
    </div>
  )
}

function Entry({ m, open, onToggle }) {
  const k = K[m.kind] || {}
  const I = k.icon || MessageCircle
  const text = clean(m.text)
  return (
    <div className={`row cursor-pointer !items-start ${open ? '' : 'row-hover'}`} onClick={onToggle} style={open ? { background: 'var(--fill)' } : {}}>
      <span className="faint num mt-[3px] w-11 shrink-0 text-[12px]">{hhmm(m.created_at)}</span>
      <span className="mt-[3px] grid h-[18px] w-[18px] shrink-0 place-items-center" style={{ color: k.color || 'var(--ink-3)' }}><I size={14} /></span>
      <div className="min-w-0 flex-1">
        <div className={`text-[14.5px] leading-snug ${open ? '' : 'truncate'}`}>{text}</div>
        {open && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]" style={{ animation: 'fade .16s ease-out' }}>
            <span className="muted">{k.label || m.kind}</span>
            <span className="faint">· источник: {CH[m.channel] || m.channel}</span>
            <span className="faint">· {new Date(m.created_at).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}</span>
            {k.to && <Link to={k.to} className="text-accent flex items-center gap-0.5 hover:underline" onClick={(e) => e.stopPropagation()}>открыть в «{k.label}» <ArrowUpRight size={12} /></Link>}
            {m.kind !== 'system' && <button className="text-accent hover:underline" onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: `про «${text.slice(0, 60)}»: ` } })) }}>спросить ассистента</button>}
          </div>
        )}
      </div>
      {!open && m.channel && m.channel !== 'web' && <span className="faint hidden shrink-0 text-[11px] sm:block">{CH[m.channel] || m.channel}</span>}
    </div>
  )
}
