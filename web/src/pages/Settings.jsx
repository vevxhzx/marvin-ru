import { createPortal } from 'react-dom'
import { useEffect, useState } from 'react'
import { Bell, BellOff, Download, HardDriveDownload, RefreshCw, Eye, EyeOff, Smartphone, Volume2, ChevronDown } from 'lucide-react'
import { playChime } from '../lib/sound'
import { api, relTime, kb } from '../lib/api'
import { Card, Field, PageHead, Section, useToast, Skeleton, Seg, Switch, ListSkeleton, Confirm } from '../components/ui'
import { enableNotifications, disableNotifications, notifyEnabled, notifyState } from '../lib/notify'
import { usePrefs, prefs as PREFS, ACCENTS, TINTS, FONT_SIZES, RADII, setPageAccent } from '../lib/prefs'
import { SwatchRow } from '../components/ColorSwatches'
import { useTheme, NAV_GROUPS, useRefresh } from '../App'
import { RotateCcw } from 'lucide-react'
import { canInstall, installPwa } from '../lib/sw'
import { pushState, enablePush, disablePush } from '../lib/push'
import pkg from '../../package.json'
import { useI18n, t as T } from '../lib/i18n'

/* Подстрока в серверном значении GPU (данные, не интерфейс) — i18n-raw */
const SERVER_VRAM = 'целиком' // i18n-raw

/* Версия веба — из package.json проекта (ядро приходит из /api/status → version) */
const WEB_VER = pkg.version

const GROUPS = [
  ['telegram', 'telegram', T('st.d_telegram')],
  ['notifications', T('st.g_notifications'), T('st.d_notifications')],
  ['brain.cloud', T('st.g_cloud'), T('st.d_cloud')],
  ['brain', T('st.g_brain'), T('st.d_brain')],
  ['voice', T('st.g_voice'), T('st.d_voice')],
  ['cards', T('st.g_cards'), T('st.d_cards')],
  ['google', T('st.g_gcal'), T('st.d_gcal2')],
  ['backup', T('st.g_backups'), T('st.d_backups')],
  ['owner', T('st.g_owner'), ''],
  ['assistant', T('st.g_assistant'), T('st.d_name')],
  ['persona', T('st.g_persona'), T('st.d_persona')],
  ['finance', T('st.g_finance'), ''],
  ['server', T('st.g_server'), ''],
]
/* Категории — только из того, что реально есть в config.yaml и статусе. Ничего нового не выдумываем. */
const CATS = [
  { id: 'general', label: T('st.g_general'), groups: ['owner', 'assistant', 'persona', 'finance', 'notifications'], extra: ['browser-notif', 'phone'] },
  { id: 'look', label: T('st.g_look'), groups: [], extra: ['look'] },
  { id: 'desktop', label: T('st.g_win'), groups: [], extra: ['desktop'] },
  { id: 'freelance', label: T('st.g_freelance'), groups: [], extra: ['freelance', 'pomodoro'] },
  { id: 'ai', label: T('st.g_brain'), groups: ['brain', 'brain.cloud'] },
  { id: 'voice', label: T('st.g_voice2'), groups: ['voice', 'cards'], extra: ['organizer'] },
  { id: 'memory', label: T('st.g_data'), groups: ['backup'], extra: ['data', 'cloud', 'english'] },
  { id: 'integrations', label: T('st.g_integrations'), groups: ['telegram', 'google'] },
  { id: 'system', label: T('st.g_system'), groups: ['server'], extra: ['status', 'diag'] },
]

export default function Settings({ health }) {
  const { t } = useI18n()
  const [data, setData] = useState(null)
  const [draft, setDraft] = useState({})
  const [status, setStatus] = useState(null)
  const [diag, setDiag] = useState(undefined) // самопроверка: undefined — не грузили, null — не ответил
  const [saving, setSaving] = useState(false)
  const [restart, setRestart] = useState(false)
  const [, show] = useToast()
  const [notif, setNotif] = useState(notifyState())
  const [gem, setGem] = useState(null)
  const [small, setSmall] = useState(null)   // результат проверки малой модели
  const [llm, setLlm] = useState(null)       // внешняя модель из .env (если сервер её умеет)
  const [pcBusy, setPcBusy] = useState(false) // идёт запуск/перезапуск voice.bat
  const [cat, setCat] = useState(() => (location.hash.replace('#', '') || localStorage.getItem('settings.cat') || 'general'))
  const pick = (id) => { setCat(id); localStorage.setItem('settings.cat', id); history.replaceState(null, '', '#' + id); window.scrollTo({ top: 0, behavior: 'smooth' }) }

  const load = () => Promise.all([api.settings().then(setData), api.status().then(setStatus),
    api.get('/api/llm').then(setLlm).catch(() => setLlm(null)),
    // самопроверка — отдельно: если /api/diagnose не ответил, остальное грузить не мешает
    api.get('/api/diagnose').then(setDiag).catch(() => setDiag(null))]).catch(show.err)
  useEffect(() => { load() }, [])

  // сервер может не вернуть пункт (например, brain.cloud.provider) — страница не должна от этого падать
  const val = (it) => (it ? (it.key in draft ? draft[it.key] : it.value) : undefined)
  const dirty = Object.keys(draft).length > 0
  const dirtyCats = new Set(Object.keys(draft).map((k) => CATS.find((c) => c.groups.some((g) => k.startsWith(g + '.')))?.id))

  const save = async () => {
    setSaving(true)
    try {
      const r = await api.saveSettings(draft)
      setDraft({}); await load()
      if (r.restart) setRestart(true)
      show(r.changed.length ? t('st.saved_n', { n: r.changed.length }) : t('st.nothing_to_save'), '', r.restart ? t('st.need_restart') : undefined)
    } catch (e) { show.err(e) } finally { setSaving(false) }
  }

  const toggleNotif = async () => {
    if (notifyEnabled()) { disableNotifications(); setNotif('off'); return }
    const p = await enableNotifications(); setNotif(p === 'granted' ? 'granted' : p)
  }

  const launchPc = async (restart) => {
    setPcBusy(true)
    try {
      const r = await api.post('/api/pc/launch', { restart })
      if (r?.ok) { show(r.message || (restart ? t('st.restarting_voice') : t('st.starting_voice')), '', t('st.window_soon')); setTimeout(load, 4000) }
      else show(r?.error || t('st.launch_failed'), 'err', t('st.manual_voice'))
    } catch (e) { show.err(e) } finally { setPcBusy(false) }
  }

  const groupBlock = ([prefix, title, hint]) => {
    if (!data) return <ListSkeleton key={prefix} n={3} />
    let items = data.items.filter((it) => it.key.startsWith(prefix + '.'))
    const provNow = val(data.items.find((it) => it.key === 'brain.cloud.provider')) || 'gemini'
    const CLOUD_EXTRA = ['brain.gemini.auto', 'brain.gemini.anonymize', 'brain.gemini.mark_source']
    if (prefix === 'brain') items = items.filter((it) => !it.key.startsWith('brain.cloud.') && !it.key.startsWith('brain.gemini.'))
    if (prefix === 'brain.cloud') {
      items = data.items.filter((it) => it.key.startsWith('brain.cloud.') || CLOUD_EXTRA.includes(it.key) || (provNow === 'gemini' && it.key.startsWith('brain.gemini.') && !CLOUD_EXTRA.includes(it.key)))
      items = items.filter((it) => it.key !== 'brain.cloud.base_url' || provNow === 'custom')
      if (provNow === 'gemini') items = items.filter((it) => !['brain.cloud.api_key', 'brain.cloud.model', 'brain.cloud.proxy'].includes(it.key))
      items.sort((a, b) => (a.key === 'brain.cloud.provider' ? -1 : b.key === 'brain.cloud.provider' ? 1 : 0))
    }
    if (prefix === 'voice') items = items.filter((it) => !['voice.tts.engine', 'voice.tts.speaker', 'voice.tts.edge_voice'].includes(it.key))
    if (!items.length) return null
    return (
      <Section key={prefix} title={title} hint={hint}>
        {prefix === 'voice' && <VoicePicker show={show} />}
        {prefix === 'google' && <GoogleConnect show={show} dirty={dirty} />}
        {prefix === 'telegram' && <MiniApp current={val(items.find((it) => it.key === 'telegram.webapp_url')) || ''} onUse={(u) => setDraft((d) => ({ ...d, 'telegram.webapp_url': u }))} />}
        <Card className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {items.map((it) => <SettingField key={it.key} it={it} value={val(it)} onChange={(v) => setDraft((d) => ({ ...d, [it.key]: v }))} providers={status?.gemini?.providers} />)}
          {prefix === 'brain.cloud' && <CloudHint prov={val(items.find((it) => it.key === 'brain.cloud.provider')) || 'gemini'} providers={status?.gemini?.providers} />}
          {prefix === 'brain.cloud' && <CloudPreview />}
        </Card>
      </Section>
    )
  }

  const extras = {
    organizer: <FileOrganizer key="organizer" show={show} />,
    look: <Appearance key="look" />,
    freelance: <Freelance key="freelance" />,
    pomodoro: <Pomodoro key="pomodoro" />,
    status: (
      <Section key="status" title={t('st.status')} action={<button className="btn-icon outlined" data-tip={t('common.retry')} onClick={load}><RefreshCw size={15} /></button>}>
        {!status ? <ListSkeleton n={3} /> : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <StatusCard ok={status.ollama.ok} warn={status.game_mode} title={t('st.local_brain')} line1={status.game_mode ? 'игровой режим · спит' : status.ollama.model}
              line2={status.game_mode ? t('st.gpu_unloaded') : status.ollama.ok ? (status.ollama.gpu && !status.ollama.gpu.includes(SERVER_VRAM) ? status.ollama.gpu : status.ollama.embed ? t('st.semantic_yes') + (status.ollama.gpu ? t('st.vram_all5') : '') : t('st.semantic_no', { m: status.ollama.embed_model })) : status.ollama.diag}
              action={<button className="btn-ghost btn-sm" data-tip={t('st.unload_gpu')} onClick={() => api.post('/api/game', { on: !status.game_mode }).then(() => load()).catch(show.err)}>{status.game_mode ? t('st.game_over') : t('st.going_play')}</button>} />
            <StatusCard ok={!!status.ollama.small_model && status.ollama.small_ok && small?.ok !== false} warn={!status.ollama.small_model || (status.ollama.small_model && !status.ollama.small_ok)} title={t('st.small_model')}
              line1={!status.ollama.small_model ? t('st.not_set') : small?.pending ? t('st.checking') : small ? (small.ok ? t('st.model_answers', { m: status.ollama.small_model }) : t('st.not_responding')) : status.ollama.small_ok ? status.ollama.small_model : t('st.not_in_ollama', { m: status.ollama.small_model })}
              line2={small && !small.pending ? (small.detail + (small.hint ? t('st.dot_join', { x: small.hint }) : '')) : !status.ollama.small_model ? t('st.small_model_hint') : !status.ollama.small_ok ? t('st.pull_in_cmd', { m: status.ollama.small_model }) : status.ollama.small_last ? t('st.small_last_task', { when: relTime(new Date(status.ollama.small_last.at * 1000).toISOString()), s: status.ollama.small_last.seconds, keep: status.ollama.small_keep_alive }) : t('st.small_never_called', { keep: status.ollama.small_keep_alive })}
              action={!!status.ollama.small_model && <button className="btn-ghost btn-sm" onClick={() => { setSmall({ pending: true }); api.post('/api/status/small').then(setSmall).catch((e) => setSmall({ ok: false, detail: e.message })) }}>{small?.pending ? t('st.checking') : t('st.check')}</button>} />
            <StatusCard ok={status.telegram.running} warn={status.telegram.configured && !status.telegram.running} title="telegram"
              line1={!status.telegram.configured ? t('st.not_configured') : status.telegram.running ? t('st.bot_ok') : t('st.configured_not_running')}
              line2={status.telegram.last_message ? t('st.last_message', { when: relTime(status.telegram.last_message) }) : t('st.no_messages')} />
            <StatusCard ok={status.backup.enabled && !!status.backup.last} warn={status.backup.enabled && !status.backup.last} title={t('st.backup')}
              line1={!status.backup.enabled ? t('st.off_short') : status.backup.last ? t('st.last_one', { when: relTime(status.backup.last) }) : t('st.backup_not_done')}
              line2={t('st.copies_n', { n: status.backup.count, dir: status.backup.dir, extra: status.backup.extra_dir || '' })} />
            <StatusCard ok={status.gemini.enabled && !status.gemini.last_error && gem?.ok !== false} warn={!status.gemini.enabled || (status.gemini.enabled && !status.gemini.last_error && !gem)} title={t('st.cloud_with', { x: status.gemini.title || 'gemini' })}
              line1={!status.gemini.enabled ? t('st.off_short') : status.gemini.last_error && gem?.ok === false ? t('st.error') : gem?.ok ? t('st.answers_short') : status.gemini.last_error ? t('st.error') : t('st.connected')}
              line2={gem && !gem.ok ? gem.detail : status.gemini.last_error ? status.gemini.last_error
                : t('st.configured_model', { m: status.gemini.model })
                  + (status.gemini.model_last && status.gemini.model_last !== status.gemini.model ? t('st.really_answers', { m: status.gemini.model_last }) : '')
                  + (status.gemini.proxy ? t('st.via_proxy') : t('st.direct'))}
              action={status.gemini.enabled && <button className="btn-ghost btn-sm" onClick={() => { setGem({ pending: true }); api.post('/api/status/gemini').then(setGem).catch((e) => setGem({ ok: false, detail: e.message })) }}>{gem?.pending ? t('st.checking') : t('st.check')}</button>} />
            {llm && <StatusCard ok={!!llm.enabled} warn={llm.mode === 'off'} title={t('st.which_model')}
              line1={llm.mode === 'cloud' ? t('st.cloud_only', { m: status.gemini.model_last || llm.model })
                : llm.mode === 'off' ? t('st.brain_off')
                : t('st.local_only', { m: status.ollama?.model || llm.model })}
              line2={llm.mode === 'cloud' ? t('st.mode_cloud')
                : llm.mode === 'hybrid' ? t('st.hybrid_chain', { local: status.ollama?.model || t('st.local_model5'), cloud: status.gemini.title || '' })
                : llm.mode === 'local' ? t('st.mode_local')
                : t('st.set_model_hint')} />}
            {status.voice && <StatusCard ok={status.voice.stt && status.voice.stt_ready && (!status.voice.tts || status.voice.tts_ready)} warn={status.voice.stt && !status.voice.stt_ready} title={t('st.g_voice3')}
              line1={!status.voice.stt ? t('st.not_installed') : !status.voice.stt_ready ? (status.voice.stt_error ? t('st.error') : t('st.loading')) : `whisper-${status.voice.stt_model} · ${status.voice.tts ? status.voice.tts_engine : t('st.no_voice_out')}`}
              line2={status.voice.stt_error || status.voice.tts_error || (!status.voice.stt ? t('st.run_update') : status.voice.stt_ready ? t('st.voice_in_tg') + ' ' + ({ voice: t('st.for_voice'), always: t('st.always'), never: t('common.never') }[status.voice.reply] || status.voice.reply) : t('st.first_run'))} />}
            {status.screen && <StatusCard ok={status.screen.enabled && !!status.pc?.alive && !!status.screen.last && (Date.now() - new Date(status.screen.last)) < 120000} warn={status.screen.enabled} title={t('st.screen_time')}
              line1={!status.screen.enabled ? t('st.disabled2') : !status.pc?.alive ? (status.pc?.seen ? t('st.client_quiet') : t('st.no_pulse')) : status.screen.today_min > 0 || (status.screen.last && (Date.now() - new Date(status.screen.last)) < 120000) ? t('st.writing_today', { h: Math.floor(status.screen.today_min / 60), m: String(status.screen.today_min % 60).padStart(2, '0') }) : t('st.waiting_data')}
              line2={!status.screen.enabled ? t('st.enable_screen') : !status.pc?.alive ? (status.pc?.seen ? t('st.voicebat_quiet', { when: relTime(status.pc.seen) }) : t('st.pulse_from_voicebat')) : t('st.screen_block_hint')} />}
            <StatusCard ok={!!status.pc?.alive} warn={!status.pc?.alive} title={t('st.pc_client')}
              line1={status.pc?.alive ? ({ idle: t('st.waiting'), listening: t('live.mode_listening'), thinking: t('live.mode_thinking'), speaking: t('live.mode_speaking'), off: t('live.mode_mic_off') }[status.pc.mode] || status.pc.mode) : t('st.not_started')}
              line2={status.pc?.alive ? t('st.online_pulse', { when: status.pc.seen ? relTime(status.pc.seen) : t('time.just_now') })
                : status.pc?.seen ? t('st.quiet_restart', { when: relTime(status.pc.seen) }) : t('st.never_online')}
              action={<div className="flex flex-wrap gap-2"><button className="btn-ghost btn-sm" disabled={pcBusy || status.pc?.alive} onClick={() => launchPc(false)}>{t('st.launch')}</button><button className="btn-ghost btn-sm" disabled={pcBusy} onClick={() => launchPc(true)}>{t('st.restart')}</button></div>} />
          </div>
        )}
        {status && (
          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-[13px] sm:grid-cols-3 lg:grid-cols-4">
            {[[t('st.core'), `v${status.version}`], [t('st.base'), t('st.mb', { v: (status.db.size / 1024 / 1024).toFixed(1) })], [t('st.events'), status.db.events], [t('graph.kind_tasks'), status.db.tasks], [t('st.txs'), status.db.transactions], [t('st.notes'), status.db.notes], [t('st.links'), status.db.links], [t('st.vision'), status.vision || '—']].map(([k, v]) => (
              <div key={k}><dt className="label !text-[10px]">{k}</dt><dd className="num mt-0.5 font-medium">{v}</dd></div>
            ))}
            {status.errors.length > 0 && (
              <div className="col-span-full neg text-[12.5px]">{t('st.errors_colon5')} {status.errors.length} · {status.errors[status.errors.length - 1].text} <span className="faint">{t('st.errors_more2')}</span></div>
            )}
          </dl>
        )}
      </Section>
    ),
    diag: <Diagnostics key="diag" status={status} diag={diag} onRefresh={load} />,
    phone: (
      <Section key="phone" title={t('st.phone')} hint={t('st.d_phone2')}>
        <PhoneAccess />
        <div className="mt-4"><InstallApp /></div>
      </Section>
    ),
    'browser-notif': (
      <Section key="bn" title={t('st.browser_notifications')} hint={t('st.d_browser_notif2')}>
        <Card className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {notifyEnabled() ? <Bell size={20} className="text-accent" /> : <BellOff size={20} className="faint" />}
            <div>
              <div className="h4">{notifyEnabled() ? t('st.on') : notif === 'denied' ? t('st.blocked') : notif === 'unsupported' ? t('st.unsupported') : t('st.off')}</div>
              <div className="muted text-[13px]">{notif === 'denied' ? t('st.allow_hint') : t('st.browser_notif_desc')}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a className="btn-ghost" href="/manifest.json" target="_blank" rel="noreferrer" data-tip={t('st.pwa')}><Smartphone size={15} /> {t('st.to_phone')}</a>
            <Switch on={notifyEnabled()} onChange={toggleNotif} label={notifyEnabled() ? t('st.on') : t('st.enable')} />
          </div>
        </Card>
        <div className="mt-3"><PushToggle /></div>
      </Section>
    ),
    data: (
      <Section key="data" title={t('st.data')} hint={t('st.d_data')}>
        <Card className="flex flex-wrap items-center gap-2">
          <button className="btn-ghost" onClick={() => api.backupNow().then((r) => show(r.ok ? `${t('st.copy_colon')} ${r.name || t('common.done')}` : t('st.no_db'))).catch(show.err)}><HardDriveDownload size={15} /> {t('st.backup_now')}</button>
          <a className="btn-ghost" href="/api/export/transactions.csv"><Download size={15} /> {t('st.f_txs')}</a>
          <a className="btn-ghost" href="/api/export/events.csv"><Download size={15} /> {t('st.f_cal')}</a>
          <a className="btn-ghost" href="/api/export/tasks.csv"><Download size={15} /> {t('st.f_tasks')}</a>
          <a className="btn-ghost" href="/api/export/notes.csv"><Download size={15} /> {t('st.f_notes')}</a>
          <a className="btn-soft" href="/api/export/all.json"><Download size={15} /> {t('st.f_json')}</a>
          <button className="btn-soft" onClick={() => api.reindex().then((r) => show(`${t('st.indexed_colon')} ${r.indexed}`)).catch(show.err)}><RefreshCw size={15} /> {t('st.reindex2')}</button>
        </Card>
        <BackupRestore show={show} />
      </Section>
    ),
    cloud: <CloudBackups key="cloud" show={show} />,
    english: <English key="english" />,
    desktop: (
      <Section key="desktop" title={t('st.win_title')} hint={t('st.win_desc2')}>
        <DesktopClientSection />
      </Section>
    ),
  }

  const current = CATS.find((c) => c.id === cat) || CATS[0]
  const order = current.id === 'general' ? ['owner', 'assistant', 'persona', 'finance', 'browser-notif', 'notifications', 'phone'] : current.id === 'memory' ? ['backup', 'cloud', 'data', 'english'] : [...current.groups, ...(current.extra || [])]

  return (
    <div className="pg on" id="p-set">
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>{t('st.settings')}</h1>
          <p className="sub r" style={{ '--i': 1 }}>{t('st.cfg_only2')}</p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          {dirty && (
            <button className="btn" disabled={saving} onClick={save}>
              {saving ? t('people.saving') : t('st.save_n', { n: Object.keys(draft).length })}
            </button>
          )}
        </div>
      </div>

      {restart && (
        <div className="panel animate-rise flex flex-wrap items-center justify-between gap-3 p-4 mb-6" style={{ borderColor: 'var(--warn)' }}>
          <div className="text-[14px]"><span className="warn font-medium">{t('st.restart_needed')}</span> <span className="muted">{t('st.restart_hint2')}</span></div>
          <button className="btn-ghost btn-sm" onClick={() => setRestart(false)}>{t('st.got_it')}</button>
        </div>
      )}

      <div className="set">
        {/* категории */}
        <div className="sn r" style={{ '--i': 2 }}>
          {CATS.map((c) => (
            <a key={c.id} className={cat === c.id ? 'on' : ''} onClick={() => pick(c.id)}>
              {c.label}
              {dirtyCats.has(c.id) && ' •'}
            </a>
          ))}
        </div>
        <div key={cat} className="st2 min-w-0">
          {order.map((k) => extras[k] || groupBlock(GROUPS.find((g) => g[0] === k)))}
        </div>
      </div>

      {dirty && createPortal(<div className="toast-in fixed inset-x-0 z-[70] flex justify-center md:bottom-8" style={{ bottom: 'calc(5.5rem + env(safe-area-inset-bottom, 0px))' }}><button className="btn-dark shadow-lg" disabled={saving} onClick={save}>{saving ? t('people.saving') : t('st.save_changes_n', { n: Object.keys(draft).length })}</button></div>, document.body)}
    </div>
  )
}

/* Список вкладок для персонального цвета (переехал сюда из шапок страниц). */
const PAGE_ACCENT_LIST = [['today', T('common.today')], ['tasks', T('nav.tasks')], ['calendar', T('nav.calendar')], ['finance', T('nav.finance')], ['orders', T('nav.orders')], ['mind', T('nav.mind')], ['people', T('nav.people')]]

/* Вид: тема, акцент, размер, углы, анимации, навигация. Всё — в этом браузере. */
function Appearance() {
  const { t, lang, setLang } = useI18n()
  const [p, set] = usePrefs()
  const [mode, setMode] = useTheme()
  const [colorsOpen, setColorsOpen] = useState(false) // «цвет для каждого раздела» — аккордеон, по умолчанию закрыт
  const activeAcc = p.accentHex || '#0a3cff'

  const applyAccent = (hex) => set({ accentHex: hex })
  const resetPageAccents = () => PREFS.set({ pageAccents: {} }) // возврат всех разделов к цвету приложения

  const toggleMotion = () => {
    const next = !p.motion
    set({ motion: next })
    document.documentElement.classList.toggle('no-anim', !next)
  }

  return (
    <>
      <section className="c r" style={{ '--i': 3 }}>
        <div className="hd"><h2>{t('st.theme_colour')}</h2><small></small></div>
        <p style={{ color: 'var(--ink2)' }}>{t('st.theme_colour_desc2')}</p>
        <div className="lbl">{t('st.theme')}</div>
        <div className="sg">
          <span className={mode === 'auto' ? 'on' : ''} onClick={() => setMode('auto')}>{t('st.theme_auto')}</span>
          <span className={mode === 'light' ? 'on' : ''} onClick={() => setMode('light')}>{t('st.theme_light')}</span>
          <span className={mode === 'dark' ? 'on' : ''} onClick={() => setMode('dark')}>{t('st.theme_dark')}</span>
        </div>
        <div className="lbl">{t('st.accent_now2')}</div>
        <SwatchRow value={activeAcc} onChange={applyAccent} />
        <div className="lbl">{t('st.tint2')}</div>
        <div className="sg">
          {[['neutral', t('tint.neutral')], ['warm', t('tint.warm')], ['cool', t('tint.cool')], ['ink', t('tint.ink')], ['accent', t('tint.accent')]].map(([id, label]) => (
            <span key={id} className={p.tint === id ? 'on' : ''} onClick={() => set({ tint: id })}>{label}</span>
          ))}
        </div>
      </section>

      <section className="c r" style={{ '--i': 3 }}>
        <div className="hd" style={{ marginBottom: colorsOpen ? undefined : 0 }}>
          <button type="button" className="flex min-w-0 items-center gap-1.5"
            style={{ background: 'transparent', border: 0, padding: 0, cursor: 'pointer' }}
            onClick={() => setColorsOpen((v) => !v)} aria-expanded={colorsOpen}
            title={colorsOpen ? t('common.less') : t('st.show')}>
            <h2 className="truncate">{t('st.per_section_colour2')}</h2>
            <ChevronDown size={16} className="faint shrink-0 transition-transform" style={{ transform: colorsOpen ? 'rotate(180deg)' : 'none' }} />
          </button>
          <button type="button" className="btn-ghost btn-sm shrink-0" onClick={resetPageAccents}
            title={t('st.reset_colour')}>
            <RotateCcw size={13} /> {t('common.reset')}
          </button>
        </div>
        {colorsOpen && (
          <div className="space-y-3">
            <p style={{ color: 'var(--ink2)' }}>
              {t('st.page_color_hint')}
            </p>
            {PAGE_ACCENT_LIST.map(([id, label]) => (
              <SwatchRow key={id} label={label} showDefault
                value={(p.pageAccents || {})[id] || ''}
                onChange={(hex) => setPageAccent(id, hex)} />
            ))}
          </div>
        )}
      </section>

      <section className="c r" style={{ '--i': 4 }}>
        <div className="hd"><h2>{t('st.size_shape')}</h2><small></small></div>
        <div className="lbl">{t('st.scale')}</div>
        <div className="sg">
          {[['sm', t('font.sm')], ['md', t('font.md')], ['lg', t('font.lg')]].map(([id, label]) => (
            <span key={id} className={p.font === id ? 'on' : ''} onClick={() => set({ font: id })}>{label}</span>
          ))}
        </div>
        <div className="lbl">{t('st.corners')}</div>
        <div className="sg">
          {[['soft', t('radius.soft')], ['sharp', t('radius.sharp')], ['round', t('radius.round')]].map(([id, label]) => (
            <span key={id} className={p.radius === id ? 'on' : ''} onClick={() => set({ radius: id })}>{label}</span>
          ))}
        </div>
        <div className="hr" style={{ marginTop: '26px', justifyContent: 'space-between', flexWrap: 'nowrap' }}>
          <div>
            <b style={{ fontWeight: 600 }}>{t('st.animations')}</b><br/>
            <span style={{ color: 'var(--ink2)', fontSize: '14px' }}>{t('st.animations_desc2')}</span>
          </div>
          <span className={`tgl ${p.motion ? '' : 'off'}`} onClick={toggleMotion}></span>
        </div>
      </section>

      <button className="btn-ghost btn-sm" onClick={() => { PREFS.reset(); setMode('auto') }}><RotateCcw size={13} /> {t('st.reset_look')}</button>

      {/* Язык интерфейса: тот же переключатель, что в шапке — состояние одно (lib/i18n.js) */}
      <div className="mb-6">
        <div className="label mb-2">{t('st.lang_title')}</div>
        <div className="flex flex-wrap gap-2">
          {[['ru', t('st.lang_ru')], ['en', t('st.lang_en')]].map(([code, name]) => (
            <button
              key={code}
              type="button"
              lang={code}
              onClick={() => setLang(code)}
              className={`btn ${lang === code ? 'on' : 'g'}`}
              aria-pressed={lang === code}
            >
              {name}
            </button>
          ))}
        </div>
        <div className="faint mt-2 text-[12px]">{t('st.lang_hint')}</div>
      </div>
    </>
  )
}

/* Помодоро: длина фокуса/перерывов, авто-перерыв, звук и голос. Хранится в базе — общее для сайта, Telegram и голоса, без перезапуска. */
const POMO_SOUNDS = [['bell', T('st.bell')], ['ding', T('st.ding')], ['tick', T('st.clicks')], ['off', T('st.no_sound')]]
/* Режим фрилансера: один выключатель на все «денежные» штуки для заказов, под ним — каждая ручка отдельно.
   Выключен — раздел «Заказы», пульс, налог и строки в дайджесте не показываются; данные не трогаются. */
function Freelance() {
  const { t } = useI18n()
  const [p, setP] = useState(null)
  const [, show] = useToast()
  const { bump } = useRefresh()
  useEffect(() => { api.freelance().then(setP).catch(show.err) }, []) // eslint-disable-line
  if (!p) return <Section title={t('st.freelance_mode')}><Skeleton h={160} /></Section>
  const save = (patch) => { const next = { ...p, ...patch }; setP(next); api.saveFreelance(patch).then((r) => { setP(r); bump(); window.dispatchEvent(new CustomEvent('freelance:changed', { detail: r })) }).catch(show.err) }
  const Row = ({ title, sub, k }) => (
    <div className="flex items-center justify-between gap-4"><div><div className="text-[14px] font-medium">{title}</div><div className="muted text-[12.5px]">{sub}</div></div><Switch on={!!p[k]} onChange={(v) => save({ [k]: v })} /></div>
  )
  return (
    <Section title={t('st.freelance_mode')} hint={t('st.freelance_desc2')}>
      <Card className="space-y-5">
        <div className="flex items-center justify-between gap-4"><div><div className="text-[15px] font-medium">{t('st.i_am_freelancer')}</div><div className="muted text-[12.5px]">{t('st.freelancer_hint')}</div></div><Switch on={p.enabled} onChange={(v) => save({ enabled: v })} /></div>
        {p.enabled && (
          <div className="space-y-5 animate-rise">
            <div className="rule" />
            <Row k="late_nudge" title={t('st.watch_payments')} sub={t('st.watch_pay_desc')} />
            {p.late_nudge && (
              <Block label={t('st.count_delay')} hint={p.late_days === 0 ? t('st.right_after') : t('st.days_after_handover', { n: p.late_days })}>
                <input type="range" min={0} max={30} step={1} value={p.late_days} onChange={(e) => setP({ ...p, late_days: Number(e.target.value) })} onMouseUp={(e) => save({ late_days: Number(e.target.value) })} onTouchEnd={(e) => save({ late_days: Number(e.target.value) })} onKeyUp={(e) => save({ late_days: Number(e.target.value) })} className="range w-full" />
              </Block>
            )}
            <Row k="rate_check" title={t('st.rate_actual')} sub={t('st.rate_actual_desc')} />
            {p.rate_check && (
              <Block label={t('st.nag_from')} hint={t('st.pct_over_estimate', { n: p.rate_tolerance })}>
                <input type="range" min={10} max={100} step={5} value={p.rate_tolerance} onChange={(e) => setP({ ...p, rate_tolerance: Number(e.target.value) })} onMouseUp={(e) => save({ rate_tolerance: Number(e.target.value) })} onTouchEnd={(e) => save({ rate_tolerance: Number(e.target.value) })} onKeyUp={(e) => save({ rate_tolerance: Number(e.target.value) })} className="range w-full" />
              </Block>
            )}
            <Block label={t('st.tax_on_orders')} hint={p.tax_percent ? t('st.tax_pct_hint', { n: p.tax_percent }) : t('st.dont_count')}>
              <Seg value={String(p.tax_percent)} onChange={(v) => save({ tax_percent: Number(v) })} options={[['0', t('common.no')], ['4', t('st.vat4')], ['6', t('st.vat6')], ['13', '13 %']]} />
            </Block>
            <Row k="weekly" title={t('st.freelance_weekly')} sub={t('st.freelance_weekly_desc')} />
          </div>
        )}
      </Card>
    </Section>
  )
}

function Pomodoro() {
  const { t } = useI18n()
  const [p, setP] = useState(null)
  const [, show] = useToast()
  useEffect(() => { api.pomodoro().then(setP).catch(show.err) }, []) // eslint-disable-line
  if (!p) return <Section title={t('st.pomodoro')}><Skeleton h={160} /></Section>
  const save = (patch) => { const next = { ...p, ...patch }; setP(next); api.savePomodoro(patch).then(setP).catch(show.err) }
  const num = (key, min, max, label, hint) => (
    <Block label={label} hint={hint}>
      <div className="flex items-center gap-2">
        <input type="range" min={min} max={max} step={1} value={p[key]} onChange={(e) => setP({ ...p, [key]: Number(e.target.value) })} onMouseUp={(e) => save({ [key]: Number(e.target.value) })} onTouchEnd={(e) => save({ [key]: Number(e.target.value) })} onKeyUp={(e) => save({ [key]: Number(e.target.value) })} className="range flex-1" />
        <span className="num w-[52px] text-right text-[13px] font-medium tabular-nums">{p[key]} мин</span>
      </div>
    </Block>
  )
  return (
    <Section title={t('st.pomodoro')} hint={t('st.pomodoro_desc2')}>
      <Card className="space-y-5">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {num('focus', 5, 90, t('st.focus'))}
          {num('short', 1, 30, t('st.short_break'))}
          {num('long', 5, 60, t('st.long_break'))}
          <Block label={t('st.long_break_every')} hint={p.long_every ? t('st.nth_tomato', { n: p.long_every }) : t('common.never')}>
            <Seg value={String(p.long_every)} onChange={(v) => save({ long_every: Number(v) })} options={[['0', t('common.never')], ['2', '2'], ['3', '3'], ['4', '4'], ['6', '6']]} />
          </Block>
        </div>
        <div className="flex items-center justify-between gap-4"><div><div className="text-[14px] font-medium">{t('st.break_alone2')}</div><div className="muted text-[12.5px]">{t('st.auto_break_hint')}</div></div><Switch on={p.auto_break} onChange={(v) => save({ auto_break: v })} /></div>
        <Block label={t('st.sound_done')} hint={t('st.here_and_pc')}>
          <div className="flex flex-wrap items-center gap-3">
            <Seg value={p.sound} onChange={(v) => { save({ sound: v }); if (v !== 'off') playChime(v, p.volume) }} options={POMO_SOUNDS} />
            {p.sound !== 'off' && <button type="button" className="btn-ghost btn-sm" onClick={() => playChime(p.sound, p.volume)}><Volume2 size={13} /> {t('st.listen')}</button>}
          </div>
        </Block>
        {p.sound !== 'off' && (
          <Block label={t('st.volume')} hint={`${Math.round(p.volume * 100)}%`}>
            <input type="range" min={0.1} max={1} step={0.05} value={p.volume} onChange={(e) => setP({ ...p, volume: Number(e.target.value) })} onMouseUp={(e) => { save({ volume: Number(e.target.value) }); playChime(p.sound, Number(e.target.value)) }} onTouchEnd={(e) => save({ volume: Number(e.target.value) })} className="range w-full" />
          </Block>
        )}
        <div className="flex items-center justify-between gap-4"><div><div className="text-[14px] font-medium">{t('live.speak')}</div><div className="muted text-[12.5px]">{t('st.speak_hint')}</div></div><Switch on={p.voice} onChange={(v) => save({ voice: v })} /></div>
      </Card>
    </Section>
  )
}

const Block = ({ label, hint, children, className = '' }) => (
  <div className={className}>
    <div className="mb-1.5 flex items-baseline justify-between"><span className="label">{label}</span>{hint && <span className="faint text-[11px]">{hint}</span>}</div>
    {children}
  </div>
)

function VoicePicker({ show }) {
  const { t } = useI18n()
  const [data, setData] = useState(null)
  const [playing, setPlaying] = useState(null)   // id голоса, который сейчас грузится/играет
  const [audio] = useState(() => (typeof Audio !== 'undefined' ? new Audio() : null))
  const load = () => api.get('/api/voice/voices').then(setData).catch(() => setData({ voices: [], current: {} }))
  useEffect(() => { load(); return () => audio?.pause() }, [])
  if (!data) return <Skeleton h={120} />
  const isCur = (v) => data.current.engine === v.engine && (v.engine === 'silero' ? data.current.speaker === v.id : data.current.edge_voice === v.id)
  const play = async (v) => {
    if (!audio) return
    if (playing === v.id) { audio.pause(); setPlaying(null); return }
    setPlaying(v.id)
    audio.src = `/api/voice/demo?engine=${v.engine}&voice=${encodeURIComponent(v.id)}&t=${Date.now()}`
    audio.onended = () => setPlaying(null)
    audio.onerror = () => { setPlaying(null); show.err(new Error(v.engine === 'edge' ? t('st.ms_voices') : t('st.voice_failed'))) }
    try { await audio.play() } catch (e) { setPlaying(null) }
  }
  const pick = (v) => api.post('/api/voice/pick', { engine: v.engine, voice: v.id }).then(() => { show(t('st.voice_picked', { name: v.name })); load() }).catch(show.err)
  return (
    <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {data.voices.map((v) => {
        const cur = isCur(v)
        return (
          <Card key={v.engine + v.id} className={`!p-3 flex items-center gap-3 ${cur ? 'ring-1 ring-[var(--accent)]' : ''}`}>
            <button className={`grid h-10 w-10 shrink-0 place-items-center rounded-full ${playing === v.id ? 'bg-accent text-accent-ink' : 'btn-ghost !p-0'}`} onClick={() => play(v)} title={t('st.listen2')}>
              {playing === v.id ? '■' : '▶'}
            </button>
            <div className="min-w-0 flex-1">
              <div className="h4 truncate">{v.name}{cur && <span className="ml-2 text-[11px] font-normal text-accent">{t('st.selected')}</span>}</div>
              <div className="muted truncate text-[12px]">{v.kind}{v.engine === 'silero' ? t('st.offline') : ''}</div>
            </div>
            {!cur && <button className="btn-ghost !py-1 !text-[12px]" onClick={() => pick(v)}>{t('common.select')}</button>}
          </Card>
        )
      })}
      <div className="faint text-[12px] sm:col-span-2 lg:col-span-3">{t('st.voice_first2')}</div>
    </div>
  )
}


function GoogleConnect({ show, dirty }) {
  const { t } = useI18n()
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState(false)
  const [askOff, setAskOff] = useState(false) // подтверждение вместо нативного confirm()
  const load = () => api.get('/api/google/status').then(setSt).catch(() => setSt({ error: true }))
  useEffect(() => { load() }, [])
  useEffect(() => {
    const on = (e) => { if (e.detail?.kind === 'google') load() }
    window.addEventListener('assistant:event', on)
    return () => window.removeEventListener('assistant:event', on)
  }, [])
  if (!st) return <Skeleton h={90} />
  const connect = async () => {
    setBusy(true)
    try {
      const r = await api.get('/api/google/connect')
      window.location.href = r.url   // Google → согласие → обратно на localhost:8765/api/google/callback
    } catch (e) { show.err(e); setBusy(false) }
  }
  const sync = () => { setBusy(true); api.post('/api/google/sync').then((r) => { show(t('st.pushed_out', { pushed: r.pushed, total: r.total }) + (r.error ? t('st.err_suffix5') + r.error : '')); load() }).catch(show.err).finally(() => setBusy(false)) }
  const off = () => setAskOff(true)
  const doOff = () => {
    setAskOff(false)
    api.post('/api/google/disconnect').then(() => { show(t('st.disabled')); load() }).catch(show.err)
  }
  const ok = st.connected && st.enabled && !st.last_error
  return (
    <Card className="mb-4 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? 'bg-emerald-500' : st.connected ? 'bg-amber-500' : 'bg-neutral-400'}`} />
        <div>
          <div className="h4">{!st.configured ? t('st.need_keys') : !st.connected ? t('st.not_connected') : ok ? t('st.connected') + (st.email ? ' · ' + st.email : '') : st.last_error ? t('st.sync_error') : t('st.connected_off')}</div>
          <div className="muted text-[13px]">
            {!st.configured ? <>{t('st.gcal_keys_hint2')} <code>{st.redirect_uri}</code></>
              : !st.connected ? <>{t('st.press_connect2')} <b>{t('st.on_this_pc')}</b> ({t('st.gcal_returns')} <code>localhost</code>{t('st.gcal_then2')}</>
              : st.last_error ? st.last_error
              : <>{t('st.gcal_progress', { synced: st.synced, total: st.total })}{st.queued ? t('st.gcal_queued', { n: st.queued }) : ''}{st.last_sync ? t('st.gcal_synced_at', { when: relTime(st.last_sync) }) : ''}{st.proxy ? t('st.via_proxy') : ''}</>}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {st.configured && !st.connected && <button className="btn-primary" disabled={busy || dirty} title={dirty ? t('st.save_settings_first') : ''} onClick={connect}>{busy ? t('st.opening_google') : t('st.connect')}</button>}
        {st.connected && <button className="btn-ghost" disabled={busy} onClick={sync}><RefreshCw size={15} /> {t('st.unload_all')}</button>}
        {st.connected && <button className="btn-ghost" onClick={off}>{t('st.disconnect')}</button>}
      </div>
      <Confirm open={askOff} onClose={() => setAskOff(false)} title={t('st.gcal_off_q')}
        text={t('st.gcal_off_text')} onOk={doOff} danger />
    </Card>
  )
}

function PhoneAccess() {
  const { t } = useI18n()
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState(null)
  const [askRotate, setAskRotate] = useState(false) // подтверждение вместо нативного confirm()
  useEffect(() => { api.get('/api/phone').then(setInfo).catch((e) => setErr(e.message)) }, [])
  const [rotating, setRotating] = useState(false)
  const rotate = async () => {
    setAskRotate(false)
    setRotating(true)
    try { await api.post('/api/phone/rotate'); setInfo(await api.get('/api/phone')) } catch (e) { setErr(e.message) } finally { setRotating(false) }
  }
  if (err) return <Card><div className="neg text-[13px]">{/403/.test(err) ? t('st.qr_only_pc') : err}</div></Card>
  if (!info) return <Skeleton h={120} />
  const remote = info.opened_from && !/^(localhost|127\.0\.0\.1)/.test(info.opened_from)
  return (
    <div className="space-y-3">
      {!info.tailscale && (
        <Card className="text-[14px]">
          <div className="h4">{t('st.no_tailscale2')}</div>
          <div className="muted mt-1 leading-relaxed">
            {t('st.step1')} <a className="text-accent underline" href="https://tailscale.com/download/windows" target="_blank" rel="noreferrer">tailscale.com/download</a> {t('st.step2b')}<br />
            {t('st.step2_phone')}<br />
            {t('st.step4b')} <code>phone.bat</code> {t('st.step4_tail')}
          </div>
        </Card>
      )}
      {Array.isArray(info?.items) && info.items.length > 0 && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {info.items.map((it) => (
            <Card key={it.kind} className="flex items-center gap-4">
              {it.qr ? <img src={it.qr} alt="QR" width={112} height={112} className="shrink-0 rounded-lg bg-white p-1" /> : null}
              <div className="min-w-0">
                <div className="label">{it.title}</div>
                <a className="h4 mt-1 block truncate text-accent" href={it.url} target="_blank" rel="noreferrer">{it.url.replace(/\?t=.*$/, '')}</a>
                <div className="faint mt-2 text-[12px]">{info.note || t('st.step5')}</div>
              </div>
            </Card>
          ))}
        </div>
      )}
      {info.can_rotate !== false && (
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-ghost" onClick={() => setAskRotate(true)} disabled={rotating}><RefreshCw size={14} className={rotating ? 'animate-spin' : ''} /> {t('st.new_access_key')}</button>
          <span className="faint text-[12px]">{t('st.new_key_desc2')}</span>
        </div>
      )}
      <Confirm open={askRotate} onClose={() => !rotating && setAskRotate(false)} title={t('st.new_key_q')}
        text={t('st.new_key_text2')}
        onOk={rotate} danger />
      <div className="faint text-[12px]">
        {remote ? <span className="pos">{t('st.not_from_pc5')} ({info.opened_from}) — {t('st.access_ok')}</span>
          : info.local_only
            ? <>{t('st.localhost_only2')}<code>127.0.0.1</code>{t('st.localhost_only_tail')} <code>HOST=0.0.0.0</code>.</>
            : <>{t('st.firewall_hint2')} <code>phone.bat</code> {t('st.firewall_tail')}</>}
      </div>
    </div>
  )
}


function MiniApp({ current, onUse }) {
  const { t } = useI18n()
  // сайт внутри Telegram: нужен публичный https-адрес от Tailscale Funnel (funnel.bat) и он же — в telegram.webapp_url
  const [st, setSt] = useState(null)
  useEffect(() => { api.get('/api/tg/miniapp').then(setSt).catch(() => setSt({ error: true })) }, [])
  if (!st) return <Skeleton h={72} />
  const f = st.funnel || {}
  const url = f.url || ''
  const matches = url && current && url.replace(/\/$/, '') === current.replace(/\/$/, '')
  const ok = !!current && (matches || !st.local)
  return (
    <Card className="mb-3 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: ok ? 'var(--pos)' : current ? 'var(--warn)' : 'var(--ink-3)' }} />
        <div>
          <div className="h4">{t('st.tg_app5')} {ok ? t('st.dot_connected') : current ? t('st.tunnel_unknown') : t('st.dot_not_connected')}</div>
          <div className="muted mt-0.5 text-[13px]">
            {!st.local ? t('st.tunnel_pc_only')
              : f.installed === false ? <>{t('st.tailscale_first2')} <code>funnel.bat</code>.</>
              : f.on && url ? <>{t('st.tunnel_ok')} <span className="num">{url}</span>{matches ? t('st.tunnel_also_bot') : t('st.tunnel_press_use')}</>
              : <>{t('st.tunnel_not_run2')} <code>funnel.bat</code> — он покажет адрес https://…ts.net и включит его. Подробно: <code>docs/telegram-miniapp.md</code></>}
          </div>
        </div>
      </div>
      {st.local && f.on && url && !matches && <button className="btn-ghost" onClick={() => onUse(url)}>{t('st.use_address2')}</button>}
    </Card>
  )
}

/* Список backup-*.db + «восстановить» (ROADMAP P1). После restore — перезапуск start.bat. */
function BackupRestore({ show }) {
  const { t } = useI18n()
  const [list, setList] = useState(null)
  const [pick, setPick] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.backups().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [])
  const doRestore = async () => {
    if (!pick) return
    setBusy(true)
    try {
      const r = await api.restoreBackup(pick.name)
      setPick(null)
      show(t('st.restored_from', { name: r.restored }) + (r.safety ? t('st.safety_net', { x: r.safety }) : ''))
      load()
    } catch (e) { show.err(e) } finally { setBusy(false) }
  }
  const fmtSize = (n) => (n >= 1e6 ? t('st.mb', { v: (n / 1e6).toFixed(1) }) : t('st.kb', { v: Math.max(1, Math.round(n / 1024)) }))
  return (
    <Card className="mt-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="h4">{t('st.restore_from2')}</div>
          <div className="muted text-[12.5px]">{t('st.restore_hint')}</div>
        </div>
        <button className="btn-icon outlined" data-tip={t('st.refresh_list')} onClick={load} aria-label={t('st.refresh')}><RefreshCw size={14} /></button>
      </div>
      {list === null ? <Skeleton h={72} /> : list.length === 0 ? (
        <div className="muted text-[13px]">{t('st.no_copies2')}</div>
      ) : (
        <ul className="divide-y hair max-h-[280px] overflow-y-auto">
          {list.map((b) => (
            <li key={b.name} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13.5px] font-medium">{b.pre_restore ? t('st.restore_backup_note') : relTime(b.at)} <span className="faint mono text-[11px]">· {b.name.replace(/^backup-(?:pre-restore-)?/, '').replace(/\.db$/, '')}</span></div>
                <div className="faint text-[12px]">{fmtSize(b.size)}{b.pre_restore ? ' · pre-restore' : ''}</div>
              </div>
              <button className="btn-soft btn-sm !h-7" onClick={() => setPick(b)}>{t('st.restore')}</button>
            </li>
          ))}
        </ul>
      )}
      <Confirm open={!!pick} onClose={() => !busy && setPick(null)} title={t('st.restore_q')}
        text={pick ? t('st.restore_q', { name: pick.name, when: relTime(pick.at) }) : ''}
        onOk={doRestore} danger />
      {busy && <div className="muted text-[12.5px]">{t('st.restoring')}</div>}
    </Card>
  )
}

/* Облачные бэкапы (WebDAV: Яндекс.Диск, Nextcloud…). Файл уходит зашифрованным
   (AES-256-GCM + пароль шифрования), поэтому переживает и смерть ПК, и сломанную базу.
   Секреты сервер не отдаёт вообще — только «задан/не задан»: пустое поле пароля
   при сохранении означает «не менять», а не «стереть». */
function CloudBackups({ show }) {
  const { t } = useI18n()
  const [st, setSt] = useState(null)        // GET /api/backups/cloud — без секретов
  const [f, setF] = useState(null)          // черновик формы (пароли всегда пустые)
  const [busy, setBusy] = useState('')      // какая кнопка крутится: save/test/upload/d:<имя>/x:<имя>
  const [check, setCheck] = useState(null)  // ответ «проверить соединение»
  const [rev, setRev] = useState({ pass: false, enc: false })
  const [del, setDel] = useState(null)      // имя файла, которое просим подтвердить на удаление
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }))
  const load = () => api.get('/api/backups/cloud').then((s) => {
    setSt(s)
    setF({ enabled: !!s.enabled, url: s.url || '', user: s.user || '', pass: '', encrypt_pass: '',
      dir: s.dir || '', every_hours: s.every_hours, keep: s.keep })
  }).catch(show.err)
  useEffect(() => { load() }, [])
  if (!st || !f) return <Skeleton h={160} />

  const sz = (n) => (n >= 1e6 ? t('st.mb', { v: (n / 1e6).toFixed(1) }) : t('st.kb', { v: Math.max(1, Math.round(n / 1024)) }))
  const own = (n) => /^backup-(?:pre-restore-)?\d{8}-\d{4}\.db(\.enc)?$/.test(n)  // только свои файлы
  // единая обёртка: «крутится кнопка + ловим ошибку», результат — null при ошибке
  const run = async (tag, fn) => {
    setBusy(tag)
    try { return await fn() } catch (e) { show.err(e); return null } finally { setBusy('') }
  }
  const save = async () => {
    const r = await run('save', () => api.put('/api/backups/cloud', f))
    if (r) { show(t('st.cloud_ok')); await load() }
  }
  // «проверить» и «отправить» читают сохранённые настройки (так же их читает планировщик),
  // поэтому сначала тихо сохраняем черновик, потом действуем.
  const saveThen = async (tag, fn) => {
    const s = await run('save', () => api.put('/api/backups/cloud', f))
    if (!s) return null
    return run(tag, fn)
  }
  const checkConn = async () => {
    const r = await saveThen('test', () => api.post('/api/backups/cloud/test'))
    if (!r) return
    setCheck(r)
    await load()
    if (r.ok) { show(r.detail || t('st.conn_ok')) } else { show.err(r.error) }
  }
  const up = async () => {
    const r = await saveThen('upload', () => api.post('/api/backups/cloud/upload'))
    if (!r) return
    show(t('st.sent_cloud', { name: r.name, size: sz(r.size), enc: sz(r.enc_size), rotated: r.rotated || '' }))
    await load()
  }
  const down = async (name) => {
    const r = await run('d:' + name, () => api.get('/api/backups/cloud/download?name=' + encodeURIComponent(name)))
    if (r) { show(t('st.downloaded', { local: r.local, size: sz(r.size) })); await load() }
  }
  const doDelete = async () => {
    const name = del
    setDel(null)
    const r = await run('x:' + name, () => api.post('/api/backups/cloud/delete?name=' + encodeURIComponent(name)))
    if (r) { show(t('st.deleted_cloud', { names: r.deleted.join(', ') })); await load() }
  }

  const secret = (key, on) => {  // поле-пароль: значение сервер никогда не отдаёт
    const fld = key === 'enc' ? 'encrypt_pass' : 'pass'
    return (
      <div className="relative">
        <input className="input pr-10" type={rev[key] ? 'text' : 'password'} value={f[fld]}
          placeholder={on ? t('st.dots_saved') : key === 'enc' ? t('st.set_password') : t('st.pass_or_token')}
          autoComplete="new-password" onChange={(e) => set(fld, e.target.value)} />
        <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 faint"
          onClick={() => setRev((r) => ({ ...r, [key]: !r[key] }))}>{rev[key] ? <EyeOff size={15} /> : <Eye size={15} />}</button>
      </div>
    )
  }

  return (
    <Section title={t('st.cloud_backups')} hint={t('st.d_cloud_backup2')}
      action={<button className="btn-icon outlined" data-tip={t('common.retry')} onClick={load} disabled={!!busy} aria-label={t('st.refresh')}><RefreshCw size={14} /></button>}>
      <Card className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Switch on={f.enabled} onChange={(v) => set('enabled', v)} label={t('st.cloud_backups2')} />
            <div>
              <div className="h4">{f.enabled ? t('st.on') : t('st.off')}</div>
              <div className="muted text-[12.5px]">{st.configured ? `${st.url} · ${st.dir}` : t('st.addr_not_set')}</div>
            </div>
          </div>
          {st.enabled && <div className="muted text-[12.5px]">{t('st.sched_sends5')} {st.every_hours} {t('unit.hour')} · {t('st.keeps', { n: st.keep })}</div>}
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label={t('st.webdav_addr')} hint={t('st.yandex_ph')}>
            <input className="input" value={f.url} placeholder="https://…" autoComplete="off" onChange={(e) => set('url', e.target.value)} />
          </Field>
          <Field label={t('st.login')} hint={st.user ? t('st.saved') : t('st.not_set2')}>
            <input className="input" value={f.user} autoComplete="off" onChange={(e) => set('user', e.target.value)} />
          </Field>
          <Field label={t('st.pass_or_token')} hint={st.pass_set ? t('st.saved_replace') : t('st.not_set2')}>
            {secret('pass', st.pass_set)}
          </Field>
          <Field label={t('st.enc_pass')} hint={st.encrypt_pass_set ? t('st.saved_replace') : t('st.not_set2')}>
            {secret('enc', st.encrypt_pass_set)}
          </Field>
          <Field label={t('st.cloud_dir')} hint={t('st.dir_autocreate')}>
            <input className="input" value={f.dir} placeholder="/jarvis-backups" onChange={(e) => set('dir', e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label={t('st.send_every')} hint="1–720">
              <input className="input" inputMode="numeric" value={f.every_hours} onChange={(e) => set('every_hours', e.target.value)} />
            </Field>
            <Field label={t('st.keep_copies')} hint="1–1000">
              <input className="input" inputMode="numeric" value={f.keep} onChange={(e) => set('keep', e.target.value)} />
            </Field>
          </div>
        </div>

        {f.enabled && !st.encrypt_pass_set && !f.encrypt_pass && (
          <div className="warn text-[12.5px]">{t('st.no_enc_pass2')}</div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <button className="btn" disabled={!!busy} onClick={save}>{busy === 'save' ? t('people.saving') : t('common.save')}</button>
          <button className="btn-ghost" disabled={!!busy} onClick={checkConn}>{busy === 'test' ? t('st.checking') : t('st.test_conn')}</button>
          <button className="btn-soft" disabled={!!busy || !f.enabled} onClick={up}>{busy === 'upload' ? t('st.sending') : t('st.send_now')}</button>
        </div>
        {check && <div className={`text-[13px] ${check.ok ? 'pos' : 'neg'}`}>{check.ok ? `${check.detail} · ${check.auth}` : check.error}</div>}

        <div className="space-y-1 text-[13px]">
          {st.last_uploaded
            ? <div>{t('st.last_send2b')} <b>{relTime(st.last_uploaded.at)}</b> · <span className="faint mono text-[11.5px]">{st.last_uploaded.name}</span> · {sz(st.last_uploaded.size)}</div>
            : <div className="muted">{t('st.never_sent2')}</div>}
          {st.last_error && <div className="neg">{t('st.last_try5')} {relTime(st.last_attempt)} — {t('st.failed_colon')} {st.last_error}</div>}
          {!st.last_error && st.last_ok && <div className="muted">{t('st.last_try_ok5')} {relTime(st.last_ok)}</div>}
          {st.list_error && <div className="warn">{t('st.cloud_list_err5')} {st.list_error}</div>}
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="h4">{t('st.cloud_files')} <span className="faint font-normal">· {st.remote.length}</span></div>
            <button className="btn-ghost btn-sm" disabled={!!busy} onClick={load}>{t('st.refresh_list')}</button>
          </div>
          {st.remote.length === 0 ? (
            <div className="muted text-[13px]">{st.enabled ? t('st.cloud_empty') : t('st.cloud_off_hint')}</div>
          ) : (
            <ul className="divide-y hair max-h-[300px] overflow-y-auto">
              {st.remote.map((r) => (
                <li key={r.name} className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13.5px] font-medium">{r.mtime ? relTime(r.mtime) : t('st.date_unknown')} <span className="faint mono text-[11px]">· {r.name.replace(/\.enc$/, '')}</span></div>
                    <div className="faint text-[12px]">{sz(r.size)}{r.name.endsWith('.enc') ? t('st.encrypted') : ''}</div>
                  </div>
                  {own(r.name) && <>
                    <button className="btn-soft btn-sm !h-7" disabled={!!busy} onClick={() => down(r.name)}>{busy === 'd:' + r.name ? t('st.downloading') : t('common.copy_dl')}</button>
                    <button className="btn-ghost btn-sm !h-7" disabled={!!busy} onClick={() => setDel(r.name)}>{t('common.delete')}</button>
                  </>}
                </li>
              ))}
            </ul>
          )}
          <div className="muted mt-2 text-[12.5px]">{t('st.cloud_download_hint')}</div>
        </div>

        <Confirm open={!!del} onClose={() => !busy && setDel(null)} title={t('st.del_cloud_q')}
          text={del ? t('st.cloud_del_q', { name: del }) : ''}
          onOk={doDelete} danger />
      </Card>
    </Section>
  )
}

function FileOrganizer({ show }) {
  const { t } = useI18n()
  const [path, setPath] = useState('')
  const [logs, setLogs] = useState([])
  const [preview, setPreview] = useState(null)
  const load = () => Promise.all([api.get('/api/pc/organize/log').then(setLogs), api.organizePreview().then((p) => setPreview(p.status === 'ready' ? p : null))]).catch(() => {})
  useEffect(() => { load() }, [])
  const run = async () => {
    if (!path.trim()) return show(t('st.set_mnt_path'))
    try {
      await api.chat(`организуй монтажную папку «${path.trim()}»`)   // фраза уходит в ядро — всегда по-русски   // i18n-raw
      show(t('st.plan_prep'))
      let p = null
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 500))
        p = await api.organizePreview()
        if (p.status === 'ready') break
      }
      setPreview(p?.status === 'ready' ? p : null)
      load()
    } catch (e) { show.err(e) }
  }
  return (
    <Section title={t('st.organise')} hint={t('st.mnt_path_desc2')}>
      <Card className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input className="input flex-1" value={path} onChange={(e) => setPath(e.target.value)} placeholder={t('st.mnt_path_ph4')} />
          <button className="btn-primary" onClick={run}>{t('st.show_plan')}</button>
        </div>
        <div className="muted text-[12px]">{t('st.organise_hint')}</div>
        {preview && (
          <div className="rounded-2xl border border-accent/30 bg-accent/5 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2"><b>{t('st.preview_ready')}</b><span className="muted text-[12px]">{preview.root}</span></div>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">{Object.entries(preview.by_category || {}).map(([k, n]) => <div key={k} className="fill rounded-xl p-3"><div className="text-[12px]">{k}</div><div className="num mt-1 text-lg font-semibold">{n}</div></div>)}</div>
            <div className="mt-3 text-[13px]">{t('st.total_files')} <b>{preview.total}</b>. {preview.profile === 'sound' && <><b>{t('st.sounds_in_sfx')}</b> </>}{t('st.nothing_moved')} {preview.cleanup_dirs?.length ? t('st.empty_old_dirs', { n: preview.cleanup_dirs.length }) : ''} {t('st.confirm_yes')} {t('st.accept_plan2')}</div>
            <details className="mt-3"><summary className="cursor-pointer text-[12px]">{t('st.show_moves2')}</summary><div className="mt-2 max-h-48 overflow-auto text-[11px]">{(preview.moves || []).map((m, i) => <div key={i} className="py-0.5">{m.src} → {m.dst}</div>)}</div></details>
          </div>
        )}
        <div className="flex items-center justify-between"><div className="label">{t('st.log2')}</div><button className="btn-ghost btn-sm" onClick={load}>{t('st.refresh3')}</button></div>
        {!logs.length ? <div className="muted text-[13px]">{t('st.no_ops')}</div> : (
          <div className="space-y-2">
            {logs.map((l, i) => (
              <div key={i} className="fill rounded-xl p-3 text-[13px]">
                <div className="flex justify-between gap-3"><b>{l.kind === 'organize_undo' ? t('st.cancel_organise') : t('st.organise_done')}</b><span className="muted">{l.at}</span></div>
                <div className="muted mt-1">{l.text}</div>
                {(l.log?.moved || []).slice(0, 8).map((m, j) => <div key={j} className="mt-1 truncate text-[11px]">{m.src} → {m.dst}</div>)}
                {(l.log?.moved || []).length > 8 && <div className="muted mt-1 text-[11px]">{t('st.and_more5')} {l.log.moved.length - 8}</div>}
              </div>
            ))}
          </div>
        )}
      </Card>
    </Section>
  )
}


function StatusCard({ ok, warn, title, line1, line2, action }) {
  const color = ok ? 'var(--pos)' : warn ? 'var(--warn)' : 'var(--neg)'
  return (
    <Card className="!p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2"><span className="inline-block h-2 w-2 rounded-full" style={{ background: color, boxShadow: `0 0 0 3px color-mix(in srgb, ${color} 18%, transparent)` }} /><span className="label">{title}</span></div>
        {action}
      </div>
      <div className="h4 mt-2 truncate" title={line1}>{line1}</div>
      {line2 && <div className="muted mt-1 line-clamp-3 text-[12px] leading-snug" title={line2}>{line2}</div>}
    </Card>
  )
}

const PROV_LABELS = { openrouter: 'OpenRouter', groq: 'Groq', nvidia: 'NVIDIA', deepseek: 'DeepSeek', gemini: 'Gemini', custom: T('st.own') }
const PROV_HINT = {
  openrouter: [T('st.prov_openrouter2'), 'https://openrouter.ai/keys', T('st.prov_openrouter_how')],
  groq: [T('st.prov_groq2'), 'https://console.groq.com/keys', T('st.prov_groq_how')],
  nvidia: [T('st.prov_silicon'), 'https://build.nvidia.com/', T('st.prov_nvidia_how')],
  deepseek: [T('st.prov_deepseek2'), 'https://platform.deepseek.com/api_keys', 'platform.deepseek.com → API keys → Create → «sk-…»'],
  gemini: [T('st.prov_gemini2'), 'https://aistudio.google.com/apikey', 'aistudio.google.com → Get API key'],
  custom: [T('st.prov_custom2'), '', ''],
}

function CloudHint({ prov, providers }) {
  const { t } = useI18n()
  const [text, url, steps] = PROV_HINT[prov] || PROV_HINT.custom
  return (
    <div className="md:col-span-2 rounded-2xl fill px-4 py-3 text-[13px] leading-relaxed">
      <div>{text}</div>
      {steps && <div className="muted mt-1">{t('st.how_to_key5')} {steps}</div>}
      {url && <a className="text-accent mt-1 inline-block" href={url} target="_blank" rel="noreferrer">{t('st.open_keys2')}</a>}
      <div className="faint mt-1">{t('st.cloud_how')}</div>
    </div>
  )
}

function CloudPreview() {
  const { t } = useI18n()
  // ФАЗА 6: «что именно уйдёт в облако» — только просмотр, ничего не отправляет (POST /api/cloud/preview).
  const [text, setText] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = () => {
    if (!text.trim()) return
    setBusy(true)
    api.post('/api/cloud/preview', { text }).then(setRes).catch(() => setRes(null)).finally(() => setBusy(false))
  }
  return (
    <div className="md:col-span-2 rounded-2xl fill px-4 py-3">
      <div className="label">{t('st.what_goes')}</div>
      <div className="faint mt-1 text-[12.5px]">{t('st.preview_hint2')}</div>
      <textarea className="input mt-2 w-full" rows={2} value={text} onChange={(e) => setText(e.target.value)}
                placeholder={t('st.ph_example')} />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button className="btn-ghost btn-sm" disabled={busy || !text.trim()} onClick={run}>{busy ? '…' : t('st.show')}</button>
        {res && <span className="faint text-[12px]">{res.will_send ? t('st.will_go') : t('st.wont_go')}{res.anonymized ? t('st.anonymised') : ''}</span>}
      </div>
      {res && <pre className="mt-2 whitespace-pre-wrap break-words text-[12.5px]">{res.text || '—'}</pre>}
      {res && res.mode === 'cloud' && (
        <div className="faint mt-2 text-[12px]">
          {res.personal_tools
            ? t('st.cloud_instead_on')
            : t('st.cloud_instead2')}
        </div>
      )}
    </div>
  )
}

function SettingField({ it, value, onChange, providers }) {
  const { t } = useI18n()
  const [reveal, setReveal] = useState(false)
  if (it.key === 'brain.cloud.provider') {
    return <Field label={t('st.provider')}><Seg value={value || 'gemini'} onChange={onChange} options={['openrouter', 'groq', 'nvidia', 'deepseek', 'gemini', 'custom'].map((p) => [p, PROV_LABELS[p]])} /></Field>
  }
  if (it.type === 'bool') {
    return (
      <Field label={it.label}>
        <Seg value={value ? 'on' : 'off'} onChange={(v) => onChange(v === 'on')} options={[['on', t('common.yes')], ['off', t('common.no')]]} />
      </Field>
    )
  }
  if (it.key === 'brain.mode') {
    return <Field label={it.label}><Seg value={value} onChange={onChange} options={[['local', t('st.local_only')], ['hybrid', t('st.hybrid')], ['cloud', t('st.g_cloud')]]} /></Field>
  }
  if (it.key === 'brain.sorter.where') {
    return <Field label={t('st.lists')} hint={t('st.lists_desc')}><Seg value={value || 'cloud'} onChange={onChange} options={[['cloud', t('st.g_cloud')], ['auto', t('st.pc_fallback')], ['local', t('st.pc_only')]]} /></Field>
  }
  if (it.key === 'brain.ollama.small_model') {
    const presets = [['', t('st.off_main')], ['qwen2.5:1.5b', t('st.m_15')], ['qwen2.5:3b', t('st.m_3b')], ['gemma3:1b', t('st.m_gemma')]]
    return (
      <Field label={t('st.small_model_desc')} hint={t('st.small_model_desc3')}>
        <Seg value={presets.some(([v]) => v === (value || '')) ? (value || '') : '__custom'} onChange={(v) => v !== '__custom' && onChange(v)} options={[...presets, ['__custom', t('st.custom')]]} />
        <input className="input mt-2" value={value ?? ''} onChange={(e) => onChange(e.target.value)} placeholder={t('st.model_name')} />
      </Field>
    )
  }
  if (it.key === 'brain.vision.where') {
    return <Field label={t('st.sees_images')}><Seg value={value || 'auto'} onChange={onChange} options={[['auto', t('st.pc_fallback')], ['cloud', t('st.g_cloud')], ['local', t('st.pc_only')]]} /></Field>
  }
  return (
    <Field label={it.label} hint={it.secret ? (it.set ? t('st.saved_replace') : t('st.not_set2')) : undefined}>
      <div className="relative">
        <input className="input pr-10" type={it.secret && !reveal ? 'password' : 'text'} inputMode={it.type === 'int' ? 'numeric' : undefined}
          value={it.secret && value === it.value ? '' : (value ?? '')} onChange={(e) => onChange(e.target.value)} placeholder={it.secret && it.set ? it.value : ''} autoComplete="off" />
        {it.secret && <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 faint" onClick={() => setReveal((v) => !v)}>{reveal ? <EyeOff size={15} /> : <Eye size={15} />}</button>}
      </div>
    </Field>
  )
}

function DesktopClientSection() {
  const { t } = useI18n()
  const [info, setInfo] = useState(null)
  const [edition, setEdition] = useState('marvin')
  const [, show] = useToast()

  useEffect(() => {
    api.get('/api/client/info').then(setInfo).catch(() => {})
    api.get('/api/edition').then((res) => { if (res?.edition) setEdition(res.edition) }).catch(() => {})
  }, [])

  const switchEdition = async (ed) => {
    try {
      setEdition(ed)
      await api.post('/api/edition', { edition: ed })
      show(ed === 'marvin' ? t('st.profile_marvin') : t('st.profile_jarvis'))
      setTimeout(() => window.location.reload(), 300)
    } catch (err) {
      show.err(err)
    }
  }

  const launchStandalone = () => {
    window.open(window.location.origin, '_blank', 'toolbar=no,menubar=no,location=no,status=no,directories=no,width=1280,height=840')
    show(t('st.win_app_mode'), t('st.win_no_tabs'))
  }

  return (
    <Card className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="h4 flex items-center gap-2">
            <span>{t('st.win_client_title')}</span>
            <span className="badge pos">{t('state.ready')}</span>
          </div>
          <div className="muted mt-1 text-[13px] leading-relaxed">
            {t('st.win_proj_desc2')}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-primary shrink-0" onClick={launchStandalone}>
            {t('st.open_window')}
          </button>
        </div>
      </div>

      {/* Переключатель профиля: Джарвис (личный) vs Марвин (публичный) */}
      <div className="rounded-xl border hair p-4 space-y-3" style={{ background: 'var(--surface-2)' }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="font-medium text-[13.5px]">{t('st.version_profile2')}</div>
            <div className="muted text-[12.5px] mt-0.5">
              {edition === 'marvin'
                ? t('st.profile_marvin_desc')
                : t('st.profile_jarvis_desc')}
            </div>
          </div>
          <div className="flex items-center rounded-lg p-1 border hair" style={{ background: 'var(--fill)' }}>
            <button
              className={`px-3 py-1 text-[12.5px] rounded-md font-medium transition ${edition === 'jarvis' ? 'bg-[var(--surface)] shadow-sm text-accent' : 'faint hover:text-ink'}`}
              onClick={() => switchEdition('jarvis')}
            >
              {t('st.z_jarvis2')}
            </button>
            <button
              className={`px-3 py-1 text-[12.5px] rounded-md font-medium transition ${edition === 'marvin' ? 'bg-[var(--surface)] shadow-sm text-accent' : 'faint hover:text-ink'}`}
              onClick={() => switchEdition('marvin')}
            >
              {t('st.z_marvin')}
            </button>
          </div>
        </div>

        <div className="rule pt-3 flex flex-wrap items-center gap-2 text-[12.5px]">
          <span className="faint">{t('st.download_builds2')}</span>
          <a
            href="/api/download/jarvis.zip"
            download="jarvis-complete.zip"
            className="btn-soft !h-7 !px-3 !text-[12px]"
          >
            {t('st.z_zip_jarvis2')}
          </a>
          <a
            href="/api/download/marvin.zip"
            download="github-marvin.zip"
            className="btn-soft !h-7 !px-3 !text-[12px]"
          >
            {t('st.z_zip_marvin2')}
          </a>
        </div>
      </div>

      <div className="rule pt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 text-[13px]">
        <div className="rounded-xl border hair p-3.5" style={{ background: 'var(--fill)' }}>
          <div className="label mb-1">{t('st.no_bat2')}</div>
          <div className="font-medium mt-1">{t('st.one_script2')}</div>
          <code className="mono block mt-1.5 p-2 rounded-lg bg-[var(--surface-2)] text-[12px]">npm run desktop</code>
          <div className="muted text-[12px] mt-2">{t('st.win_client_hint')}</div>
        </div>

        <div className="rounded-xl border hair p-3.5" style={{ background: 'var(--fill)' }}>
          <div className="label mb-1">{t('st.sysint2')}</div>
          <div className="space-y-1.5 mt-1.5 text-[12.5px]">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: 'var(--pos)' }} />
              <span>{t('st.single2')}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: 'var(--pos)' }} />
              <span>{t('st.tray2')}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: 'var(--pos)' }} />
              <span>{t('st.webview2_pwa')}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: 'var(--pos)' }} />
              <span>{t('st.hotkeys_desc2')}</span>
            </div>
          </div>
        </div>
      </div>
    </Card>
  )
}

/* ---------- логи и диагностика (раздел «система») ----------

   Всё берётся только из существующих ответов: GET /api/status (сырое состояние),
   GET /api/diagnose (выводы словами: {ok, items:[{level,what,fix}], at})
   и GET /api/backups (список файлов копий — по нему проверяем последнюю копию).
   Секция сворачивается, обновляется кнопкой, пустые состояния — честные. */
function Diagnostics({ status, diag, onRefresh }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(true)
  const [busy, setBusy] = useState(false)
  const [backups, setBackups] = useState(undefined) // undefined — грузим, null — не ответил, [] — пусто

  const refresh = async () => {
    setBusy(true)
    try {
      await Promise.all([
        Promise.resolve(onRefresh?.()),
        api.backups().then(setBackups).catch(() => setBackups(null)),
      ])
    } finally { setBusy(false) }
  }
  useEffect(() => { api.backups().then(setBackups).catch(() => setBackups(null)) }, [])

  const errs = status?.errors || []
  const db = status?.db
  const bk = Array.isArray(backups) ? backups[0] : null
  const fmtSize = (n) => (n >= 1e6 ? t('st.mb', { v: (n / 1e6).toFixed(1) }) : t('st.kb', { v: Math.max(1, Math.round(n / 1024)) }))
  const total = db ? db.events + db.tasks + db.transactions + db.notes + db.links : 0

  // «результат проверки» последней копии: файл из списка есть и не пустой
  const bkCheck = backups === undefined ? null
    : backups === null ? { tone: 'warn', text: t('st.no_copies_api') }
    : !backups.length ? { tone: 'neg', text: t('st.no_copy_files') }
    : bk && !bk.size ? { tone: 'neg', text: t('st.last_copy_empty', { when: relTime(bk.at) }) }
    : bk ? { tone: 'pos', text: `${t('st.copy_ok')} ${fmtSize(bk.size)} · ${relTime(bk.at)}${bk.pre_restore ? t('st.restore_note4') : ''}` }
    : { tone: 'warn', text: t('st.no_copies_list') }
  const bkDot = bkCheck?.tone === 'pos' ? 'var(--pos)' : bkCheck?.tone === 'neg' ? 'var(--neg)' : 'var(--warn)'

  const lvlDot = (level) => (level === 'bad' ? 'var(--neg)' : level === 'warn' ? 'var(--warn)' : 'var(--pos)')

  return (
    <Section title={t('st.logs')} hint={t('st.d_logs2')}
      action={<>
        <button className="btn-ghost btn-sm" disabled={busy} onClick={refresh}>
          <RefreshCw size={13} className={busy ? 'animate-spin' : ''} /> {t('st.refresh3')}
        </button>
        <button className="btn-icon outlined" onClick={() => setOpen((v) => !v)} aria-expanded={open}
          aria-label={open ? t('st.collapse3') : t('st.show3')} data-tip={open ? t('common.less') : t('st.show')}>
          <ChevronDown size={15} style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .18s' }} />
        </button>
      </>}>
      {!open ? null : !status ? <ListSkeleton n={4} /> : (
        <div className="space-y-3">
          {/* версии и база */}
          <Card>
            <div className="label mb-2">{t('st.versions_db')}</div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[13px] sm:grid-cols-4">
              {[[t('st.core'), `v${status.version}`], [t('st.web'), `v${WEB_VER}`],
                [t('st.base'), t('st.mb', { v: (db.size / 1024 / 1024).toFixed(1) })], [t('st.records'), total],
                [t('mem.k_events'), db.events], [t('nav.tasks'), db.tasks],
                [t('st.txs2'), db.transactions], [t('st.notes_links'), `${db.notes} · ${db.links}`]].map(([k, v]) => (
                <div key={k}><dt className="label !text-[10px]">{k}</dt><dd className="num mt-0.5 font-medium">{v}</dd></div>
              ))}
            </dl>
            <div className="faint mt-3 truncate text-[11.5px]" title={db.path}>{t('st.db_file4')} {db.path}</div>
          </Card>

          {/* ошибки этой сессии */}
          <Card>
            <div className="flex items-center justify-between gap-2">
              <div className="label">{t('st.session_errors')}</div>
              <span className="num text-[12px] font-medium" style={{ color: errs.length ? 'var(--neg)' : 'var(--pos)' }}>{errs.length}</span>
            </div>
            {errs.length === 0 ? (
              <div className="muted mt-2 text-[13px]">{t('st.no_errors2')}</div>
            ) : (
              <ul className="mt-1 divide-y hair">
                {[...errs].reverse().map((e, i) => (
                  <li key={i} className="flex items-start gap-3 py-2">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: 'var(--neg)' }} />
                    <span className="min-w-0 flex-1 break-words text-[13px]">{e.text}</span>
                    <span className="faint shrink-0 text-[11.5px]">{e.at ? relTime(e.at) : ''}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="faint mt-2 text-[11.5px]">{t('st.errs_in_memory2')}</div>
          </Card>

          {/* самопроверка */}
          <Card>
            <div className="flex items-center justify-between gap-2">
              <div className="label">{t('st.selfcheck')}</div>
              {diag?.at && <span className="faint text-[11.5px]">{relTime(diag.at)}</span>}
            </div>
            {diag === undefined ? <Skeleton h={72} className="mt-2" />
              : diag === null ? <div className="muted mt-2 text-[13px]">Самопроверка недоступна: /api/diagnose не ответил. Нажмите «обновить».</div>
              : !diag.items?.length ? <div className="mt-2 text-[13px] pos">{t('st.selfcheck_ok2')}</div>
              : (
                <ul className="mt-2 space-y-2">
                  {diag.items.map((it, i) => (
                    <li key={i} className="flex items-start gap-2.5">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: lvlDot(it.level) }} />
                      <span className="min-w-0 flex-1">
                        <span className="text-[13px]">{it.what}</span>
                        {it.fix && <span className="faint block text-[12px]">→ {it.fix}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            {diag?.ok === false && <div className="neg mt-2 text-[12.5px]">{t('st.selfcheck_bad2')}</div>}
          </Card>

          {/* бэкап: дата последнего + результат проверки */}
          <Card>
            <div className="flex items-center justify-between gap-2">
              <div className="label">{t('st.backup')}</div>
              {status.backup.last && <span className="faint text-[11.5px]">{relTime(status.backup.last)}</span>}
            </div>
            {!status.backup.enabled ? (
              <div className="muted mt-2 text-[13px]">{t('st.backup_off_desc2')}</div>
            ) : (
              <div className="mt-2 space-y-1.5 text-[13px]">
                <div>{t('st.last4')} {status.backup.last ? relTime(status.backup.last) : t('st.not_done_yet')} · копий: {status.backup.count}{status.backup.size ? ` · ${fmtSize(status.backup.size)}` : ''}</div>
                <div className="faint truncate text-[12px]" title={status.backup.dir}>{t('st.folder4')} {status.backup.dir}{status.backup.extra_dir ? t('st.second_dir', { x: status.backup.extra_dir }) : ''}</div>
                <div className="flex items-start gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: bkDot }} />
                  <span className="muted text-[12.5px]">{t('st.check_label4')} {bkCheck?.text || t('st.checking_files')}</span>
                </div>
              </div>
            )}
          </Card>

          {/* состояния систем */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Card className="!p-4">
              <div className="label">{t('st.ollama2')}</div>
              <div className="h4 mt-1.5 truncate">{status.ollama.ok ? (status.ollama.model || t('st.model_ok')) : t('st.not_responding')}</div>
              <div className="faint mt-0.5 line-clamp-3 text-[12px]">{status.ollama.ok ? (status.ollama.gpu || status.ollama.url || '') : (status.ollama.diag || t('st.start_ollama'))}</div>
            </Card>
            <Card className="!p-4">
              <div className="label">telegram</div>
              <div className="h4 mt-1.5">{!status.telegram.configured ? t('st.not_configured') : status.telegram.running ? t('st.bot_ok') : t('st.cfg_not_run')}</div>
              <div className="faint mt-0.5 line-clamp-3 text-[12px]">{status.telegram.last_message ? t('st.last_message', { when: relTime(status.telegram.last_message) }) : t('st.no_messages')}</div>
            </Card>
            <Card className="!p-4">
              <div className="label">{t('st.cloud_colon4')} {status.gemini.title || status.gemini.provider}</div>
              <div className="h4 mt-1.5 truncate">{!status.gemini.enabled ? t('st.disabled2') : status.gemini.last_error ? t('st.error') : t('st.connected')}</div>
              <div className="faint mt-0.5 line-clamp-3 text-[12px]">
                {status.gemini.last_error
                  ? status.gemini.last_error
                  : !status.gemini.enabled ? t('st.cloud_hint')
                  : `${status.gemini.model || ''}${status.gemini.model_last && status.gemini.model_last !== status.gemini.model ? t('st.really_answers', { m: status.gemini.model_last }) : ''}${status.gemini.proxy ? t('st.via_proxy') : ''}`}
              </div>
            </Card>
          </div>
        </div>
      )}
    </Section>
  )
}

/* ---------- web push: тумблер подписки (секция «уведомления в браузере») ----------

   Логика — в lib/push.js (WebCrypto, PushManager, POST /api/push/subscribe).
   Здесь — только честные состояния: браузер не умеет / нет https / dev-режим /
   серверной части ещё нет («появится позже») — без ошибок и без падений. */
const PUSH_TEXT = {
  idle: [T('st.checking'), T('st.push_look')],
  on: [T('st.push_on'), T('st.push_on_desc')],
  off: [T('st.push_none'), T('st.push_desc')],
  pending: [T('st.push_later'), T('st.push_noep')],
  denied: [T('st.push_blocked'), T('st.allow_browser')],
  unsupported: [T('st.not_supported'), T('st.need_push_browser')],
  insecure: [T('st.https_only'), T('st.secure_ctx')],
  dev: [T('st.dev_only'), T('st.sw_prod_only')],
}
function PushToggle() {
  const { t } = useI18n()
  const [state, setState] = useState('idle')
  const [busy, setBusy] = useState(false)
  const [, show] = useToast()
  useEffect(() => { pushState().then(setState).catch(() => setState('unsupported')) }, [])

  const locked = state === 'unsupported' || state === 'insecure' || state === 'dev'
  const toggle = async () => {
    if (busy || locked) return
    setBusy(true)
    try {
      if (state === 'on') {
        const r = await disablePush()
        if (r.ok) { setState('off'); show(t('st.push_off')) }
        else show(r.message || t('st.push_off_fail'), 'err')
        return
      }
      const r = await enablePush()
      if (r.ok) { setState('on'); show(t('st.push_enabled'), '', t('st.push_sent')) }
      else if (r.reason === 'no-endpoint') { setState('pending'); show(t('st.push_later2'), '', t('st.push_no_endpoint')) }
      else if (r.reason === 'permission') setState('denied')
      else if (r.reason === 'insecure') setState('insecure')
      else if (r.reason === 'dev') setState('dev')
      else if (r.reason === 'unsupported') setState('unsupported')
      else { setState('off'); show(r.message || t('st.push_subscribe_fail'), 'err') }
    } finally { setBusy(false) }
  }

  const [title, hint] = PUSH_TEXT[state] || PUSH_TEXT.off
  return (
    <Card className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        {state === 'on' ? <Bell size={20} className="text-accent" /> : <BellOff size={20} className="faint" />}
        <div>
          <div className="h4">{busy ? t('st.subscribing') : title}</div>
          <div className="muted text-[13px]">{hint}</div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {state === 'pending' && <span className="faint text-[12px]">{t('st.push_404')}</span>}
        <Switch on={state === 'on'} onChange={toggle} label={t('st.push_sub')} />
      </div>
    </Card>
  )
}

/* ---------- английский: направление, абзац дня, прогресс, свои тексты ----------
   Всё живёт в settings KV на сервере (core/services/learn_en.py): направление запоминается,
   абзац детерминирован по дате. Генерация нейросетью выключена по умолчанию — тогда абзац
   берётся из встроенного корпуса, и если модель недоступна, честно пишем об этом, а не
   придумываем текст. */
const EN_TRACK_CHIPS = [
  ['video', T('st.tech_docs')],
  ['general', T('st.en_general')],
  ['custom', T('st.own_texts')],
]
const EN_SOURCES = { builtin: T('st.builtin_corpus'), llm: T('st.gen_by_ai'), custom: T('st.your_text') }

function English() {
  const { t } = useI18n()
  const [st, setSt] = useState(null)        // GET /api/english/settings — направление, флаг llm, лимит
  const [day, setDay] = useState(null)      // GET /api/english/today
  const [prog, setProg] = useState(null)    // GET /api/english/progress
  const [mine, setMine] = useState(null)    // GET /api/english/custom
  const [showRu, setShowRu] = useState(false) // перевод показан/скрыт
  const [busy, setBusy] = useState('')      // какая кнопка в работе
  const [del, setDel] = useState(null)      // индекс своего текста, который просим удалить
  const [draft, setDraft] = useState({ text_en: '', text_ru: '', note: '' })
  const [, show] = useToast()

  const load = () => Promise.all([
    api.get('/api/english/settings').then(setSt),
    api.get('/api/english/today').then((d) => { setDay(d); setShowRu(false) }),
    api.get('/api/english/progress').then(setProg),
    api.get('/api/english/custom').then(setMine),
  ]).catch(show.err)
  useEffect(() => { load() }, []) // eslint-disable-line

  // «крутится кнопка + ловим ошибку», результат — null при ошибке
  const run = async (tag, fn) => {
    setBusy(tag)
    try { return await fn() } catch (e) { show.err(e); return null } finally { setBusy('') }
  }

  const setTrack = (track) => run('track', () => api.put('/api/english/settings', { track }))
    .then(async (s) => { if (!s) return; setSt(s); const d = await api.get('/api/english/today'); setDay(d); setShowRu(false); show(t('st.direction_set', { track: EN_TRACK_CHIPS.find((c) => c[0] === track)?.[1] || track })) })
  const setLlm = (on) => run('llm', () => api.put('/api/english/settings', { llm: on }))
    .then((s) => { if (s) { setSt(s); show(on ? t('st.ai_paras') : t('st.builtin_paras')) } })

  const markDone = () => run('done', () => api.post('/api/english/done'))
    .then((p) => { if (!p) return; setProg(p); show(p.already ? t('st.already_today') : t('st.marked_streak', { n: p.streak })) })
  const addMine = () => run('add', () => api.post('/api/english/custom', {
    text_en: draft.text_en, text_ru: draft.text_ru, note: draft.note }))
    .then((r) => { if (!r) return; setDraft({ text_en: '', text_ru: '', note: '' }); load().catch(() => {}) ; show(t('st.text_added')) })
  const doDelete = () => {
    const i = del
    setDel(null)
    run('x:' + i, () => api.del(`/api/english/custom/${i}`))
      .then((r) => { if (r) { load().catch(() => {}); show(t('st.text_removed')) } })
  }

  if (!st || !day || !prog || !mine) return <Section title={t('st.english')}><Skeleton h={220} /></Section>
  const track = st.track
  const words = day.words || []

  return (
    <Section title={t('st.english')} hint={t('st.d_en2')}
      action={<button className="btn-icon outlined" data-tip={t('common.retry')} aria-label={t('st.refresh')} disabled={!!busy} onClick={() => load().catch(() => {})}><RefreshCw size={14} /></button>}>
      <Card className="space-y-5">
        <div>
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <span className="label">{t('st.direction')}</span>
            <span className="faint text-[11px]">
              {track === 'custom' ? t('st.your_texts_count', { n: mine.items.length, limit: mine.limit }) : t('st.builtin_count', { n: st.tracks_count[track] || 0 })}
            </span>
          </div>
          <div className="chips !m-0 !gap-1.5">
            {EN_TRACK_CHIPS.map(([id, label]) => (
              <button key={id} type="button" disabled={!!busy || track === id}
                className={`chip !mt-0 ${track === id ? 'on' : ''}`} onClick={() => setTrack(id)}>{label}</button>
            ))}
          </div>
          <div className="muted mt-2 text-[12.5px]">
            {track === 'custom'
              ? t('st.today_from_own2')
              : st.tracks.find((t) => t.id === track)?.title}
          </div>
        </div>

        <div className="rule" />

        {/* абзац дня */}
        <div>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <div className="flex items-baseline gap-2">
              <span className="h4">{t('st.paragraph')}</span>
              {day.title && <span className="faint text-[12px]">· {day.title}</span>}
            </div>
            <div className="flex items-center gap-2">
              <span className="chip !mt-0 !py-0.5">{EN_SOURCES[day.source] || day.source}</span>
              {prog.today_done && <span className="chip on !mt-0 !py-0.5">{t('st.read')}</span>}
            </div>
          </div>
          {day.empty ? (
            <div className="muted text-[13px]">{t('st.no_own_texts2')}</div>
          ) : (
            <>
              <div className="text-[16px] leading-relaxed">{day.text_en}</div>
              {showRu ? (
                <div className="muted mt-2 animate-rise text-[14px] leading-relaxed">{day.text_ru || t('st.no_translation')}</div>
              ) : (
                <button type="button" className="btn-ghost btn-sm mt-2" onClick={() => setShowRu(true)}>{t('st.show_translation')}</button>
              )}
              {words.length > 0 && (
                <ul className="mt-4 divide-y hair">
                  {words.map((w) => (
                    <li key={w.word} className="py-2">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <b className="text-[14px] font-medium">{w.word}</b>
                        <span className="mono faint text-[12.5px]">{w.phonetic}</span>
                      </div>
                      {w.note && <div className="muted text-[12.5px]">{w.note}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button className="btn" disabled={!!busy || day.empty} onClick={markDone}>
              {busy === 'done' ? t('st.marking') : prog.today_done ? t('st.already_read') : t('st.read_done')}
            </button>
            {showRu && <button type="button" className="btn-ghost btn-sm" onClick={() => setShowRu(false)}>{t('st.hide_translation')}</button>}
          </div>
        </div>

        <div className="rule" />

        {/* прогресс */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div><div className="label !text-[10px]">{t('st.streak')}</div><div className="num mt-0.5 text-[17px] font-medium">{prog.streak ? t('st.days_n', { n: prog.streak }) : '—'}</div></div>
          <div><div className="label !text-[10px]">{t('st.total_days')}</div><div className="num mt-0.5 text-[17px] font-medium">{prog.total_days || '—'}</div></div>
          <div><div className="label !text-[10px]">{t('st.last_time')}</div><div className="num mt-0.5 text-[17px] font-medium">{prog.last_date ? relTime(prog.last_date) : '—'}</div></div>
          <div><div className="label !text-[10px]">{t('st.direction')}</div><div className="num mt-0.5 text-[17px] font-medium">{EN_TRACK_CHIPS.find((c) => c[0] === track)?.[1] || track}</div></div>
        </div>
        {prog.by_track && Object.keys(prog.by_track).length > 1 && (
          <div className="chips !m-0 !gap-1.5">
            {Object.entries(prog.by_track).map(([t, v]) => (
              <span key={t} className="chip !mt-0 !py-0.5">{EN_TRACK_CHIPS.find((c) => c[0] === t)?.[1] || t} · {v.days}</span>
            ))}
          </div>
        )}

        <div className="rule" />

        {/* генерация нейросетью */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[14px] font-medium">{t('st.gen_ai2')}</div>
            <div className="muted text-[12.5px]">
              {t('st.gen_off_desc2')}
            </div>
          </div>
          <Switch on={st.llm} onChange={setLlm} label={t('st.gen_ai')} />
        </div>
        {st.llm && day.source === 'builtin' && (
          <div className="warn text-[12.5px]">{t('st.gen_fallback2')}</div>
        )}

        <div className="rule" />

        {/* свои тексты */}
        <div>
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <span className="h4">{t('st.own_texts')}</span>
            <span className="faint text-[11px]">{mine.items.length} из {mine.limit}</span>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label={t('st.en_text')} hint={t('st.what_read')}>
              <textarea className="input min-h-[92px]" value={draft.text_en} rows={3}
                placeholder="The edit is ready for review."
                onChange={(e) => setDraft({ ...draft, text_en: e.target.value })} />
            </Field>
            <Field label={t('st.translation')} hint={t('st.optional_translation')}>
              <textarea className="input min-h-[92px]" value={draft.text_ru} rows={3}
                placeholder={t('st.edit_ready')}
                onChange={(e) => setDraft({ ...draft, text_ru: e.target.value })} />
            </Field>
          </div>
          <Field label={t('st.tag_label')} hint={t('st.tag_opt')} className="mt-3">
            <input className="input" value={draft.note} placeholder={t('st.for_client')} onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
          </Field>
          <div className="mt-3">
            <button className="btn" disabled={!!busy || !draft.text_en.trim()} onClick={addMine}>
              {busy === 'add' ? t('st.adding') : t('st.add_text')}
            </button>
          </div>

          {mine.items.length === 0 ? (
            <div className="muted mt-4 text-[13px]">{t('st.texts_empty2')}</div>
          ) : (
            <ul className="divide-y hair mt-4 max-h-[320px] overflow-y-auto">
              {mine.items.map((r, i) => (
                <li key={`${i}-${r.text_en.slice(0, 12)}`} className="flex items-start gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] leading-snug">{r.text_en}</div>
                    {r.text_ru && <div className="muted mt-0.5 text-[12.5px]">{r.text_ru}</div>}
                    <div className="faint mt-1 text-[11.5px]">{[r.note, r.at ? relTime(r.at) : ''].filter(Boolean).join(' · ')}</div>
                  </div>
                  <button type="button" className="btn-ghost btn-sm shrink-0 !h-7" disabled={!!busy} onClick={() => setDel(i)}>{t('common.delete')}</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Confirm open={del != null} onClose={() => !busy && setDel(null)} title={t('st.del_text_q')}
          text={del != null ? t('st.your_text_del_q', { text: (mine.items[del]?.text_en || '').slice(0, 120) }) : ''}
          onOk={doDelete} danger />
      </Card>
    </Section>
  )
}

/* ---------- кнопка «установить» (раздел «телефон») ----------

   Промпт beforeinstallprompt перехватывается в lib/sw.js и живёт до первого
   вызова; если браузер его не прислал — честная подсказка про «На экран Домой». */
function InstallApp() {
  const { t } = useI18n()
  const [avail, setAvail] = useState(canInstall())
  const [busy, setBusy] = useState(false)
  const [, show] = useToast()
  useEffect(() => {
    const h = () => setAvail(canInstall())
    window.addEventListener('pwa:installable', h)
    return () => window.removeEventListener('pwa:installable', h)
  }, [])
  const run = async () => {
    setBusy(true)
    try {
      const ok = await installPwa()
      setAvail(canInstall())
      if (ok) show(t('st.installing2'), '', t('st.icon_soon'))
      else show(t('st.install_failed'), '', t('st.install_manual'))
    } finally { setBusy(false) }
  }
  return (
    <Card className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <Smartphone size={20} className={avail ? 'text-accent' : 'faint'} />
        <div>
          <div className="h4">{t('st.install_app2')}</div>
          <div className="muted text-[13px]">
            {avail
              ? t('st.pwa_desc')
              : t('st.install_when2')}
          </div>
        </div>
      </div>
      {avail && <button className="btn-primary" disabled={busy} onClick={run}>{busy ? t('st.installing') : t('st.install')}</button>}
    </Card>
  )
}
