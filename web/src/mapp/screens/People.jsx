/* MPeople — мобильные люди. Живые данные: GET /api/people,
   GET /api/crm/clients/summary (стадии + следующие шаги), GET /api/crm/followups
   и /api/finance/debts (текст ai-подсказки). Кит из ../ui.jsx. */
import { useEffect, useMemo, useState } from 'react'
import { CalendarDays, MessageCircle, Phone, Sparkles } from 'lucide-react'
import { api, listOf, money, shortDate } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { CLIENT_STAGES, CLIENT_STAGE_TONE, clientStageLabel } from '../../lib/crm'
import { Avatar, Card, Chip, MEmpty, MLoadError, MLoading, Pill, ScreenTitle } from '../ui.jsx'

const initialsOf = (s) => (s || '?').split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('') || '?'
const hueOf = (s) => [...String(s || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % 6
const HAS_STAGE = new Set(['client', 'company'])
const isClientKind = (p) => p.kind === 'client' || p.kind === 'company'
const STAGE_TONE = { lead: 'gray', negotiation: 'amber', client: 'green', permanent: 'green', asleep: 'gray' }
const KIND_LABEL = { person: 'people.k_person', family: 'people.k_family', friend: 'people.k_friend', client: 'people.k_client', company: 'people.k_company', colleague: 'people.k_colleague' }
const STAGE_COLOR = { lead: '#a9b3e0', negotiation: '#ffc24d', client: '#3ddc97', permanent: '#3ddc97', asleep: 'rgba(255,255,255,0.22)' }

export default function MPeople() {
  const { t } = useI18n()
  const [list, setList] = useState(null)
  const [stages, setStages] = useState({})
  const [steps, setSteps] = useState({})
  const [followups, setFollowups] = useState([])
  const [debts, setDebts] = useState([])
  const [err, setErr] = useState(null)
  const [group, setGroup] = useState('all')
  const [stage, setStage] = useState(null)
  const [toastMsg, setToastMsg] = useState(null)

  const load = () => {
    setErr(null)
    return api.people().then(async (l) => {
      setList(l || [])
      const ids = (l || []).filter(isClientKind).map((p) => p.id).filter((x) => x != null).slice(0, 60)
      if (ids.length) {
        try {
          const r = await api.crmClientsSummary(ids)
          const map = r?.clients || {}
          const st = {}, sp = {}
          for (const cid of ids) {
            const e = map[cid] ?? map[String(cid)]
            if (!e) continue
            if (e.stage) st[cid] = typeof e.stage === 'string' ? { stage: e.stage } : e.stage
            const card = e.card || {}
            const step = e.next_step ?? card.next_step ?? ''
            const at = e.next_step_at ?? card.next_step_at ?? null
            if (step) sp[cid] = { step, at }
          }
          setStages(st); setSteps(sp)
        } catch { /* стадии — необязательное обогащение */ }
      }
    }).catch(() => setErr(true))
  }
  useEffect(() => {
    load()
    api.crmFollowups().then((f) => setFollowups(f || [])).catch(() => {})
    api.debts().then((d) => setDebts(d || [])).catch(() => {})
  }, [])

  const toast = (text) => {
    setToastMsg(text)
    window.clearTimeout(toast._t)
    toast._t = window.setTimeout(() => setToastMsg(null), 3000)
  }

  const counts = useMemo(() => {
    const c = { lead: 0, negotiation: 0, client: 0, permanent: 0 }
    for (const p of list || []) {
      if (!isClientKind(p)) continue
      const s = stages[p.id]?.stage
      if (s && c[s] != null) c[s] += 1
    }
    return c
  }, [list, stages])
  const ltvTotal = useMemo(() => (list || []).reduce((s, p) => s + (p.paid || 0), 0), [list])
  const leadsWait = (counts.lead || 0) + (counts.negotiation || 0)

  const filtered = useMemo(() => {
    let l = list || []
    if (group === 'clients') l = l.filter(isClientKind)
    else if (group === 'family') l = l.filter((p) => p.kind === 'family')
    else if (group === 'friends') l = l.filter((p) => p.kind === 'friend')
    if (stage) l = l.filter((p) => stages[p.id]?.stage === stage)
    return [...l].sort((a, b) => (b.open - a.open) || (b.unpaid - a.unpaid) || String(a.name).localeCompare(String(b.name), 'ru'))
  }, [list, group, stage, stages])

  /* ai-подсказка: сначала followup про этого человека, потом его долг, потом неоплата. */
  const hintFor = (p) => {
    const nm = String(p.name || '').toLowerCase()
    const f = followups.find((x) => String(x.text || '').toLowerCase().includes(nm) || x.client_id === p.id || (x.client && String(x.client).toLowerCase() === nm))
    if (f) return f.text
    const d = debts.find((x) => String(x.counterparty || x.title || x.name || '').toLowerCase().includes(nm))
    if (d) return `${t('m.waiting', { v: money(d.left ?? d.amount ?? 0) })} · ${d.title || d.counterparty || ''}`.trim()
    if (p.unpaid) return t('m.waiting', { v: money(p.unpaid) })
    return null
  }

  if (err) {
    return <MLoadError onRetry={load} />
  }
  if (!list) return <MLoading rows={5} rowH={74} />

  const showFunnel = group === 'all' || group === 'clients'

  return (
    <div>
      <ScreenTitle
        title={t('m.people')}
        count={list.length}
        subtitle={leadsWait ? t('m.leads_wait', { count: leadsWait }) : undefined}
      />

      <div className="no-scrollbar mt-5 flex gap-2 overflow-x-auto px-4">
        {[['all', 'm.g_all'], ['clients', 'm.g_clients'], ['family', 'm.g_family'], ['friends', 'm.g_friends']].map(([id, k]) => (
          <Chip
            key={id}
            active={group === id}
            onClick={() => { setGroup(id); if (id !== 'clients' && id !== 'all') setStage(null) }}
          >
            {t(k)}
          </Chip>
        ))}
      </div>

      {showFunnel && (
        <div className="mt-3 px-4">
          <div className="m-glass rounded-[24px] p-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[14px] font-semibold">{t('m.funnel')}</span>
              <span className="tnum text-[12px] text-white/55">{t('m.ltv_all', { v: money(ltvTotal) })}</span>
            </div>
            <div className="mt-3 flex h-2.5 gap-1">
              {['lead', 'negotiation', 'client', 'permanent'].map((s) => (
                <div
                  key={s}
                  className="rounded-full transition-opacity"
                  style={{ flex: Math.max(1, counts[s] || 0), background: STAGE_COLOR[s], opacity: stage && stage !== s ? 0.25 : 1 }}
                />
              ))}
            </div>
            <div className="mt-2.5 grid grid-cols-4 gap-1">
              {['lead', 'negotiation', 'client', 'permanent'].map((s) => (
                <button
                  type="button"
                  key={s}
                  onClick={() => { setStage(stage === s ? null : s); setGroup('clients') }}
                  className={`rounded-[14px] px-2 py-1.5 text-left transition active:scale-95${stage === s ? ' bg-white/[0.14]' : ''}`}
                >
                  <div className="tnum text-[18px] font-semibold">{counts[s] || 0}</div>
                  <div className="truncate text-[11.5px] text-white/55">{clientStageLabel(s)}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 space-y-3 px-4">
        {filtered.map((p) => (
          <PersonCard key={p.id} p={p} stageKey={stages[p.id]?.stage} next={steps[p.id]} hint={hintFor(p)} onToast={toast} />
        ))}
        {filtered.length === 0 && (
          <Card className="px-4 py-5">
            <MEmpty
              compact
              glyph="search"
              text={stage || group !== 'all' ? t('m.search_none') : t('m.people_empty')}
              sub={stage || group !== 'all' ? t('m.search_none_sub') : t('m.people_empty_sub')}
              hint={stage || group !== 'all' ? undefined : t('m.people_hint')}
            />
          </Card>
        )}
      </div>

      {toastMsg && (
        <div className="anim-toast fixed bottom-24 left-1/2 z-50 -translate-x-1/2 rounded-full border border-white/10 bg-[#121a46]/95 px-4 py-2.5 text-[13.5px] shadow-xl backdrop-blur-xl">{toastMsg}</div>
      )}
    </div>
  )
}

function PersonCard({ p, stageKey, next, hint, onToast }) {
  const { t } = useI18n()
  const tags = listOf(p.tags)
  const sub = p.aliases || (tags.length ? tags.map((x) => `#${x}`).join(' ') : null) || p.contact || ''
  const tone = stageKey ? (STAGE_TONE[stageKey] || 'gray') : null
  void CLIENT_STAGE_TONE
  void CLIENT_STAGES
  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <Avatar initials={initialsOf(p.name)} hue={hueOf(p.name)} size={46} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[16.5px] font-semibold leading-snug">{p.name}</div>
          {sub ? <div className="mt-0.5 truncate text-[12.5px] text-white/45">{sub}</div> : null}
        </div>
        {isClientKind(p)
          ? <Pill tone={tone || 'gray'} dot>{stageKey ? clientStageLabel(stageKey) : clientStageLabel('lead')}</Pill>
          : <Pill tone="violet">{KIND_LABEL[p.kind] ? t(KIND_LABEL[p.kind]) : (p.kind || '')}</Pill>}
      </div>

      {next?.step && (
        <div className="mt-3 flex items-center gap-2.5 rounded-[16px] bg-white/[0.05] px-3 py-2.5">
          <CalendarDays size={16} className="shrink-0 text-[#8ea3ff]" />
          <span className="min-w-0 flex-1 truncate text-[14px] leading-snug">{next.step}</span>
          {next.at && <span className="tnum shrink-0 text-[12.5px] text-white/55">{shortDate(next.at)}</span>}
        </div>
      )}

      {hint && (
        <div className="mt-3 flex items-center gap-2.5 rounded-[16px] bg-[#7d95ff]/14 px-3 py-2.5">
          <Sparkles size={14} className="shrink-0 text-[#a9bbff]" />
          <span className="min-w-0 flex-1 truncate text-[13px] leading-snug text-[#c9d4ff]">{hint}</span>
          <button type="button" onClick={() => onToast(t('m.write_toast', { name: p.name }))} className="shrink-0 text-[13px] font-semibold text-white">{t('m.reply')}</button>
        </div>
      )}

      <div className="mt-3 flex items-center gap-3">
        {isClientKind(p) ? (
          <div className="tnum flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[13px]">
            {p.unpaid ? <span className="font-semibold text-[#ffd581]">{t('m.waiting', { v: money(p.unpaid) })}</span> : <span className="text-white/45">{t('m.no_debts')}</span>}
            <span className="text-white/45">{t('m.ltv', { v: money(p.paid || 0) })}</span>
          </div>
        ) : <div className="flex-1" />}
        <div className="flex shrink-0 gap-1.5">
          <button type="button" aria-label={t('m.reply')} onClick={() => onToast(t('m.write_toast', { name: p.name }))} className="grid h-9 w-9 place-items-center rounded-full bg-white/[0.08] text-white/80 transition active:scale-90">
            <MessageCircle size={16} />
          </button>
          <button type="button" aria-label={t('m.call_toast', { name: p.name })} onClick={() => onToast(t('m.call_toast', { name: p.name }))} className="grid h-9 w-9 place-items-center rounded-full bg-white/[0.08] text-white/80 transition active:scale-90">
            <Phone size={16} />
          </button>
        </div>
      </div>
    </Card>
  )
}
