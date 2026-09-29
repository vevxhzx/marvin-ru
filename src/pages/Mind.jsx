import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Graph from '../components/Graph'
import { api, relTime, plural } from '../lib/api'
import { useToast } from '../components/ui'
import { useRefresh } from '../App'

const URL_RE = /https?:\/\/[^\s]+/

export default function Mind() {
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState(() => (params.get('tab') === 'graph' ? 'graph' : 'all'))
  const [q, setQ] = useState(() => params.get('q') || '')
  const [notes, setNotes] = useState([])
  const [links, setLinks] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = () => {
    if (q.trim().length >= 3) {
      return api.semantic(q, 30).then((r) => {
        setNotes(r.items.filter((x) => x.kind === 'note'))
        setLinks(r.items.filter((x) => x.kind === 'link'))
      }).catch(() => Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setNotes(n || []); setLinks(l || []) }).catch(() => {}))
    }
    return Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setNotes(n || []); setLinks(l || []) }).catch(() => {})
  }

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0)
    return () => clearTimeout(t)
  }, [q, tick])

  const submit = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    const t = text.trim()
    if (!t || busy) return
    setBusy(true)
    try {
      const m = t.match(URL_RE)
      if (m) {
        await api.addLink(m[0], t.replace(m[0], '').trim() || null)
        show('Ссылка сохранена')
      } else {
        await api.addNote(t)
        show('Мысль сохранена')
      }
      setText('')
      load()
      bump()
    } catch (er) {
      show.err(er)
    } finally {
      setBusy(false)
    }
  }

  const items = [
    ...(notes || []).map((n) => ({ ...n, _t: 'note' })),
    ...(links || []).map((l) => ({ ...l, _t: 'link' })),
  ].filter((x) => {
    if (tab === 'all') return true
    if (tab === 'photo') return !!x.image
    if (tab === 'note') return x._t === 'note' && !x.image
    if (tab === 'link') return x._t === 'link'
    return true
  }).sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))

  const count = items.length || 25

  return (
    <div className="pg on" id="p-brain">
      {/* Шапка */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>мозг</h1>
          <p className="sub r" style={{ '--i': 1 }}>второй мозг · {count} {plural(count, 'запись', 'записи', 'записей')}</p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg">
            <span className={tab === 'all' ? 'on' : ''} onClick={() => setTab('all')}>всё</span>
            <span className={tab === 'note' ? 'on' : ''} onClick={() => setTab('note')}>мысли</span>
            <span className={tab === 'photo' ? 'on' : ''} onClick={() => setTab('photo')}>фото</span>
            <span className={tab === 'link' ? 'on' : ''} onClick={() => setTab('link')}>ссылки</span>
            <span className={tab === 'graph' ? 'on' : ''} onClick={() => setTab('graph')}>граф</span>
          </div>
        </div>
      </div>

      {/* Быстрый ввод */}
      <div className="comp r" style={{ '--i': 2 }}>
        <i></i>
        <input
          className="ph0"
          style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit' }}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit(e)}
          placeholder="мысль, идея, ссылка или фото — как есть, редактор причешет"
        />
        <span className="send" style={{ fontSize: '24px', cursor: 'pointer' }} onClick={submit}>+</span>
      </div>

      {/* Поисковая строка по смыслу */}
      <div className="search r" style={{ width: '100%', height: '54px', marginTop: '16px', '--i': 3 }}>
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <circle cx="9" cy="9" r="6" />
          <path d="m14 14 3.5 3.5" />
        </svg>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit', font: 'inherit', marginLeft: '8px' }}
          placeholder="поиск по смыслу: «та статья про сон», «идея для подарка»…"
        />
      </div>

      {/* Masonry-сетка заметок или Граф */}
      {tab === 'graph' ? (
        <div className="mt-8 animate-rise">
          <Graph height={Math.max(450, window.innerHeight - 300)} />
        </div>
      ) : (
        <div className="mas" style={{ marginTop: '28px' }}>
          {(items.length ? items : [
            {
              id: 'mock-1',
              text: 'что теперь надо переплачивать за пельмени: разница в 100 рублей не такая существенная. лучше качество, чем дешевить. как говорится, скупой платит дважды. запиши это в мысль',
              tags: ['решение'],
              created_at: new Date().toISOString(),
            },
            {
              id: 'mock-2',
              title: 'Опрос про Аполлона',
              text: 'На скриншоте опрос тестировщиков: «Насколько весело играть против героя Apollo?» со шкалой оценки от 1 до 5.',
              image: true,
              imgVariant: '',
              tags: ['игры', 'тестирование', 'apollo'],
              created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
            },
            {
              id: 'mock-3',
              title: 'Купить три бутылки пива',
              text: 'Хочу купить три бутылочки пива.',
              tags: ['покупки', 'развлечения', 'дом'],
              created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
            },
            {
              id: 'mock-4',
              title: 'Проблема в деньгах',
              text: 'Всё сводится к тварственным деньгам.',
              tags: ['деньги', 'проблемы', 'мысли'],
              created_at: new Date(Date.now() - 86400000 * 3).toISOString(),
            },
            {
              id: 'mock-5',
              title: 'Тест пельменей Мираторг',
              text: 'Будем тестировать пельмени Мираторг с говядиной. Делать вид, что не жалко, потому что просадил косарь.',
              tags: [],
              created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
            },
            {
              id: 'mock-6',
              text: 'На фото — мужчина в костюме в кресле, заголовок «ЭТИ ПРИВЫЧКИ СДЕЛАЮТ ТЕБЯ БОГАТЫМ» и список абсурдных пунктов.',
              image: true,
              imgVariant: 'b',
              tags: [],
              created_at: new Date(Date.now() - 86400000 * 10).toISOString(),
            },
          ]).map((it, idx) => (
            <section className="c r" key={it.id} style={{ '--i': 4 + (idx % 6) }}>
              {it.image && (
                <div className={`img ${it.imgVariant === 'b' ? 'b' : ''}`}>
                  {it.imgVariant === 'b' ? 'фото' : 'скриншот'}
                </div>
              )}
              {it.title && <h3>{it.title}</h3>}
              <p>{it.text || it.summary || it.body || it.url}</p>
              <div className="tg">
                <small>{relTime(it.created_at)}</small>
                {it.tags?.map((t) => <span key={t}>#{t}</span>)}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
