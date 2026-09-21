import { createPortal } from 'react-dom'
import { useEffect, useState } from 'react'
import { Bell, BellOff, Download, HardDriveDownload, RefreshCw, Eye, EyeOff, Smartphone, Volume2 } from 'lucide-react'
import { playChime } from '../lib/sound'
import { api, relTime, kb } from '../lib/api'
import { Card, Field, PageHead, Section, useToast, Skeleton, Seg, Switch, ListSkeleton, Confirm } from '../components/ui'
import { enableNotifications, disableNotifications, notifyEnabled, notifyState } from '../lib/notify'
import { usePrefs, prefs as PREFS, ACCENTS, TINTS, FONT_SIZES, RADII } from '../lib/prefs'
import { useTheme, NAV_GROUPS, useRefresh } from '../App'
import { RotateCcw } from 'lucide-react'

const GROUPS = [
  ['telegram', 'telegram', 'Бот отвечает только вашему ID. Токен — от @BotFather, ID — от @userinfobot.'],
  ['notifications', 'уведомления', 'Утром — дайджест, в 21:00 — вопрос про незакрытые задачи («сделал / завтра»). Ночью ассистент сам не пишет, кроме напоминаний, которые вы поставили.'],
  ['brain.cloud', 'облако', 'Для общих вопросов («объясни», «напиши», «посоветуй»). Личные данные туда не уходят. Ключ берётся за минуту, карта не нужна.'],
  ['brain', 'мозг', 'Локальная модель (Ollama) — всё личное: деньги, календарь, задачи, заметки. Никуда не уходит.'],
  ['voice', 'голос и ПК', 'Whisper распознаёт на вашем ПК (никуда не уходит), отвечает Silero. voice.bat — голос в комнате, управление программами, утренний доклад, ночной режим и авто-игровой режим. Скриншоты «что на экране» и фото чеков — через модель зрения (см. «мозг»).'],
  ['google', 'google календарь', 'События ассистента появляются в Google Календаре — на телефоне, часах, в любом приложении. Только в одну сторону: ассистент → Google. Client ID и secret — 5 минут по инструкции в README (бесплатно, карта не нужна).'],
  ['backup', 'бэкапы', 'Ежедневно в 03:00. Вторая копия — на другой диск или в папку Яндекс.Диска / Google Drive.'],
  ['owner', 'вы', ''],
  ['assistant', 'ассистент', 'Имя — так он представляется и на него откликается голосом. После смены — перезапуск.'],
  ['persona', 'характер', 'Готовые реплики и стиль ответов. Обращение — из «вы».'],
  ['finance', 'финансы', ''],
  ['server', 'сервер', ''],
]
/* Категории — только из того, что реально есть в config.yaml и статусе. Ничего нового не выдумываем. */
const CATS = [
  { id: 'general', label: 'общее', groups: ['owner', 'assistant', 'persona', 'finance', 'notifications'], extra: ['browser-notif', 'phone'] },
  { id: 'look', label: 'вид', groups: [], extra: ['look'] },
  { id: 'freelance', label: 'фриланс', groups: [], extra: ['freelance', 'pomodoro'] },
  { id: 'ai', label: 'мозг', groups: ['brain', 'brain.cloud'] },
  { id: 'voice', label: 'голос и пк', groups: ['voice'] },
  { id: 'memory', label: 'память и данные', groups: ['backup'], extra: ['data'] },
  { id: 'integrations', label: 'интеграции', groups: ['telegram', 'google'] },
  { id: 'system', label: 'система', groups: ['server'], extra: ['status'] },
]

export default function Settings({ health }) {
  const [data, setData] = useState(null)
  const [draft, setDraft] = useState({})
  const [status, setStatus] = useState(null)
  const [saving, setSaving] = useState(false)
  const [restart, setRestart] = useState(false)
  const [, show] = useToast()
  const [notif, setNotif] = useState(notifyState())
  const [gem, setGem] = useState(null)
  const [small, setSmall] = useState(null)   // результат проверки малой модели
  const [cat, setCat] = useState(() => (location.hash.replace('#', '') || localStorage.getItem('settings.cat') || 'general'))
  const pick = (id) => { setCat(id); localStorage.setItem('settings.cat', id); history.replaceState(null, '', '#' + id); window.scrollTo({ top: 0, behavior: 'smooth' }) }

  const load = () => Promise.all([api.settings().then(setData), api.status().then(setStatus)]).catch(show.err)
  useEffect(() => { load() }, [])

  const val = (it) => (it.key in draft ? draft[it.key] : it.value)
  const dirty = Object.keys(draft).length > 0
  const dirtyCats = new Set(Object.keys(draft).map((k) => CATS.find((c) => c.groups.some((g) => k.startsWith(g + '.')))?.id))

  const save = async () => {
    setSaving(true)
    try {
      const r = await api.saveSettings(draft)
      setDraft({}); await load()
      if (r.restart) setRestart(true)
      show(r.changed.length ? `Сохранено: ${r.changed.length}` : 'Нечего сохранять', '', r.restart ? 'нужен перезапуск start.bat' : undefined)
    } catch (e) { show.err(e) } finally { setSaving(false) }
  }

  const toggleNotif = async () => {
    if (notifyEnabled()) { disableNotifications(); setNotif('off'); return }
    const p = await enableNotifications(); setNotif(p === 'granted' ? 'granted' : p)
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
        </Card>
      </Section>
    )
  }

  const extras = {
    look: <Appearance key="look" />,
    freelance: <Freelance key="freelance" />,
    pomodoro: <Pomodoro key="pomodoro" />,
    status: (
      <Section key="status" title="состояние" action={<button className="btn-icon outlined" data-tip="обновить" onClick={load}><RefreshCw size={15} /></button>}>
        {!status ? <ListSkeleton n={3} /> : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <StatusCard ok={status.ollama.ok} warn={status.game_mode} title="локальный мозг" line1={status.game_mode ? 'игровой режим · спит' : status.ollama.model}
              line2={status.game_mode ? 'модель выгружена из видеопамяти, всё идёт в облако' : status.ollama.ok ? (status.ollama.gpu && !status.ollama.gpu.includes('целиком') ? status.ollama.gpu : status.ollama.embed ? `смысловой поиск: да${status.ollama.gpu ? ' · в видеокарте целиком' : ''}` : `поиск по смыслу: нет (ollama pull ${status.ollama.embed_model})`) : status.ollama.diag}
              action={<button className="btn-ghost btn-sm" data-tip="выгрузить модель из видеопамяти на время игры" onClick={() => api.post('/api/game', { on: !status.game_mode }).then(() => load()).catch(show.err)}>{status.game_mode ? 'игра окончена' : 'иду играть'}</button>} />
            <StatusCard ok={!!status.ollama.small_model && status.ollama.small_ok && small?.ok !== false} warn={!status.ollama.small_model || (status.ollama.small_model && !status.ollama.small_ok)} title="малая модель"
              line1={!status.ollama.small_model ? 'не задана' : small?.pending ? 'проверяю…' : small ? (small.ok ? `${status.ollama.small_model} · отвечает` : 'не отвечает') : status.ollama.small_ok ? status.ollama.small_model : `${status.ollama.small_model} · нет в Ollama`}
              line2={small && !small.pending ? (small.detail + (small.hint ? ` · ${small.hint}` : '')) : !status.ollama.small_model ? 'судья и подколы идут на основную модель · задайте в «мозг → малая модель» (qwen2.5:1.5b)' : !status.ollama.small_ok ? `в cmd: ollama pull ${status.ollama.small_model}` : status.ollama.small_last ? `последняя задача ${relTime(new Date(status.ollama.small_last.at * 1000).toISOString())} · ${status.ollama.small_last.seconds} с · в видеопамяти ${status.ollama.small_keep_alive} после задачи` : `ещё не вызывалась · в видеопамяти ${status.ollama.small_keep_alive} после задачи`}
              action={!!status.ollama.small_model && <button className="btn-ghost btn-sm" onClick={() => { setSmall({ pending: true }); api.post('/api/status/small').then(setSmall).catch((e) => setSmall({ ok: false, detail: e.message })) }}>{small?.pending ? 'проверяю…' : 'проверить'}</button>} />
            <StatusCard ok={status.telegram.running} warn={status.telegram.configured && !status.telegram.running} title="telegram"
              line1={!status.telegram.configured ? 'не настроен' : status.telegram.running ? 'бот на связи' : 'настроен, но не запущен (--no-tg?)'}
              line2={status.telegram.last_message ? `последнее сообщение ${relTime(status.telegram.last_message)}` : 'сообщений ещё не было'} />
            <StatusCard ok={status.backup.enabled && !!status.backup.last} warn={status.backup.enabled && !status.backup.last} title="бэкап"
              line1={!status.backup.enabled ? 'выключен' : status.backup.last ? `последний ${relTime(status.backup.last)}` : 'ещё не делался (в 03:00)'}
              line2={`${status.backup.count} копий · ${status.backup.dir}${status.backup.extra_dir ? ` + ${status.backup.extra_dir}` : ''}`} />
            <StatusCard ok={status.gemini.enabled && !status.gemini.last_error && gem?.ok !== false} warn={!status.gemini.enabled || (status.gemini.enabled && !status.gemini.last_error && !gem)} title={`облако · ${status.gemini.title || 'gemini'}`}
              line1={!status.gemini.enabled ? 'выключен' : gem ? (gem.ok ? 'отвечает' : 'ошибка') : status.gemini.last_error ? 'ошибка' : status.gemini.model}
              line2={gem && !gem.ok ? gem.detail : gem?.ok ? `модель ${gem.model}${status.gemini.proxy ? ' · через прокси' : ''}` : status.gemini.last_error || (status.gemini.enabled ? `${status.gemini.model}${status.gemini.proxy ? ' · через прокси' : ' · напрямую'}` : 'ключ не задан или режим local')}
              action={status.gemini.enabled && <button className="btn-ghost btn-sm" onClick={() => { setGem({ pending: true }); api.post('/api/status/gemini').then(setGem).catch((e) => setGem({ ok: false, detail: e.message })) }}>{gem?.pending ? 'проверяю…' : 'проверить'}</button>} />
            {status.voice && <StatusCard ok={status.voice.stt && status.voice.stt_ready && (!status.voice.tts || status.voice.tts_ready)} warn={status.voice.stt && !status.voice.stt_ready} title="голос"
              line1={!status.voice.stt ? 'не установлен' : !status.voice.stt_ready ? (status.voice.stt_error ? 'ошибка' : 'загружается…') : `whisper-${status.voice.stt_model} · ${status.voice.tts ? status.voice.tts_engine : 'без озвучки'}`}
              line2={status.voice.stt_error || status.voice.tts_error || (!status.voice.stt ? 'запустите update.bat — поставит распознавание и голос' : status.voice.stt_ready ? `голосовые в Telegram работают · ответ голосом: ${{ voice: 'на голосовые', always: 'всегда', never: 'никогда' }[status.voice.reply] || status.voice.reply}` : 'первый запуск качает модели (~600 МБ), подождите пару минут')} />}
            {status.screen && <StatusCard ok={status.screen.enabled && !!status.screen.last && (Date.now() - new Date(status.screen.last)) < 120000} warn={status.screen.enabled} title="экранное время"
              line1={!status.screen.enabled ? 'выключено' : status.screen.last && (Date.now() - new Date(status.screen.last)) < 120000 ? `пишется · сегодня ${Math.floor(status.screen.today_min / 60)} ч ${String(status.screen.today_min % 60).padStart(2, '0')}` : 'включено, но данных нет'}
              line2={!status.screen.enabled ? 'включить: голос и пк → «экранное время»; пишется только имя программы и сайт, локально' : status.screen.last && (Date.now() - new Date(status.screen.last)) < 120000 ? 'блок «время за пк» — на главной; в чате «сколько сидел за компом»' : status.pc?.alive ? 'voice.bat запущен, но старой версии или без перезапуска после включения — перезапустите voice.bat' : 'пульс идёт от voice.bat — запустите его (после включения настройки нужен перезапуск)'} />}
            <StatusCard ok={!!status.pc?.alive} warn={!status.pc?.alive} title="пк-клиент" line1={status.pc?.alive ? ({ idle: 'ждёт', listening: 'слушает', thinking: 'думает', speaking: 'говорит', off: 'микрофон выкл' }[status.pc.mode] || status.pc.mode) : 'не запущен'} line2={status.pc?.alive ? 'voice.bat на связи' : 'запустите voice.bat — голос в комнате и управление программами'} />
          </div>
        )}
        {status && (
          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-[13px] sm:grid-cols-3 lg:grid-cols-4">
            {[['ядро', `v${status.version}`], ['база', `${(status.db.size / 1024 / 1024).toFixed(1)} МБ`], ['событий', status.db.events], ['задач', status.db.tasks], ['операций', status.db.transactions], ['заметок', status.db.notes], ['ссылок', status.db.links], ['зрение', status.vision || '—']].map(([k, v]) => (
              <div key={k}><dt className="label !text-[10px]">{k}</dt><dd className="num mt-0.5 font-medium">{v}</dd></div>
            ))}
            {status.errors.length > 0 && <div className="col-span-full neg text-[12.5px]">ошибок за сессию: {status.errors.length} · {status.errors[status.errors.length - 1].text}</div>}
          </dl>
        )}
      </Section>
    ),
    phone: (
      <Section key="phone" title="телефон" hint="Сайт открывается с телефона без интернета наружу: через Tailscale из любой сети или по домашнему Wi-Fi.">
        <PhoneAccess />
      </Section>
    ),
    'browser-notif': (
      <Section key="bn" title="уведомления в браузере" hint="Напоминания и действия из Telegram — прямо в браузере. На iPhone: Поделиться → «На экран Домой», затем включить здесь.">
        <Card className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {notifyEnabled() ? <Bell size={20} className="text-accent" /> : <BellOff size={20} className="faint" />}
            <div>
              <div className="h4">{notifyEnabled() ? 'включены' : notif === 'denied' ? 'запрещены в браузере' : notif === 'unsupported' ? 'браузер не поддерживает' : 'выключены'}</div>
              <div className="muted text-[13px]">{notif === 'denied' ? 'Разрешите уведомления для этого сайта в настройках браузера.' : 'Напоминания о событиях и дедлайнах, добавления из Telegram.'}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a className="btn-ghost" href="/manifest.json" target="_blank" rel="noreferrer" data-tip="PWA-манифест"><Smartphone size={15} /> на телефон</a>
            <Switch on={notifyEnabled()} onChange={toggleNotif} label={notifyEnabled() ? 'включены' : 'включить'} />
          </div>
        </Card>
      </Section>
    ),
    data: (
      <Section key="data" title="данные" hint="Всё лежит в data/assistant.db на вашем компьютере. Экспорт — на всякий случай и для Excel.">
        <Card className="flex flex-wrap items-center gap-2">
          <button className="btn-ghost" onClick={() => api.backupNow().then((r) => show(r.ok ? `Копия: ${r.name || 'готово'}` : 'Не вышло — нет базы?')).catch(show.err)}><HardDriveDownload size={15} /> бэкап сейчас</button>
          <a className="btn-ghost" href="/api/export/transactions.csv"><Download size={15} /> операции.csv</a>
          <a className="btn-ghost" href="/api/export/events.csv"><Download size={15} /> календарь.csv</a>
          <a className="btn-ghost" href="/api/export/tasks.csv"><Download size={15} /> задачи.csv</a>
          <a className="btn-ghost" href="/api/export/notes.csv"><Download size={15} /> заметки.csv</a>
          <a className="btn-soft" href="/api/export/all.json"><Download size={15} /> всё в json</a>
          <button className="btn-soft" onClick={() => api.reindex().then((r) => show(`Проиндексировано: ${r.indexed}`)).catch(show.err)}><RefreshCw size={15} /> переиндексировать мозг</button>
        </Card>
        <BackupRestore show={show} />
      </Section>
    ),
  }

  const current = CATS.find((c) => c.id === cat) || CATS[0]
  const order = current.id === 'general' ? ['owner', 'assistant', 'persona', 'finance', 'browser-notif', 'notifications', 'phone'] : current.id === 'memory' ? ['backup', 'data'] : [...current.groups, ...(current.extra || [])]

  return (
    <div className="space-y-8">
      <PageHead kicker="только то, что есть в config.yaml — ничего лишнего" title="настройки" idx={7}
        right={dirty && <button className="btn-primary" disabled={saving} onClick={save}>{saving ? 'сохраняю…' : 'сохранить'}</button>} />

      {restart && (
        <div className="panel animate-rise flex flex-wrap items-center justify-between gap-3 p-4" style={{ borderColor: 'var(--warn)' }}>
          <div className="text-[14px]"><span className="warn font-medium">Нужен перезапуск.</span> <span className="muted">Закройте окно ассистента и снова запустите start.bat — новые настройки Telegram/мозга/бэкапа подхватятся.</span></div>
          <button className="btn-ghost btn-sm" onClick={() => setRestart(false)}>понял</button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[180px_1fr] lg:gap-12">
        {/* категории: слева на десктопе, лентой на телефоне */}
        <nav className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1 lg:sticky lg:top-[72px] lg:mx-0 lg:flex-col lg:self-start lg:overflow-visible lg:px-0" aria-label="Разделы настроек">
          {CATS.map((c) => (
            <button key={c.id} onClick={() => pick(c.id)} className={`nav-item !h-9 !w-auto shrink-0 !rounded-full !px-3.5 lg:!h-10 lg:!w-full lg:!rounded-xl lg:!px-3 ${cat === c.id ? 'active' : ''}`}>
              <span className="nav-label">{c.label}</span>
              {dirtyCats.has(c.id) && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent" />}
            </button>
          ))}
        </nav>
        <div key={cat} className="min-w-0 space-y-12 animate-rise">
          {order.map((k) => extras[k] || groupBlock(GROUPS.find((g) => g[0] === k)))}
        </div>
      </div>

      {dirty && createPortal(<div className="toast-in fixed inset-x-0 z-[70] flex justify-center md:bottom-8" style={{ bottom: 'calc(5.5rem + env(safe-area-inset-bottom, 0px))' }}><button className="btn-dark shadow-lg" disabled={saving} onClick={save}>{saving ? 'сохраняю…' : `сохранить изменения · ${Object.keys(draft).length}`}</button></div>, document.body)}
    </div>
  )
}

/* Вид: тема, акцент, размер, углы, анимации, навигация. Всё — в этом браузере. */
function Appearance() {
  const [p, set] = usePrefs()
  const [mode, setMode] = useTheme()
  const NAV = NAV_GROUPS.flatMap((g) => g.items).filter((n) => n.to !== '/' && n.to !== '/settings')
  const toggleNav = (to) => set({ hiddenNav: p.hiddenNav.includes(to) ? p.hiddenNav.filter((x) => x !== to) : [...p.hiddenNav, to] })
  const toggleTab = (to) => { const on = p.tabbar.includes(to); if (on && p.tabbar.length <= 2) return; if (!on && p.tabbar.length >= 5) return; set({ tabbar: on ? p.tabbar.filter((x) => x !== to) : [...p.tabbar, to] }) }
  const ALL = NAV_GROUPS.flatMap((g) => g.items)
  return (
    <>
      <Section title="тема и цвет" hint="Один акцентный цвет на весь интерфейс. Тема «как в системе» переключается сама.">
        <Card className="space-y-5">
          <Block label="тема">
            <Seg value={mode} onChange={setMode} options={[['auto', 'как в системе'], ['light', 'светлая'], ['dark', 'тёмная']]} />
          </Block>
          <Block label="акцент" hint={ACCENTS[p.accent]?.label}>
            <div className="flex flex-wrap gap-2">
              {Object.entries(ACCENTS).map(([id, a]) => (
                <button key={id} type="button" onClick={() => set({ accent: id })} data-tip={a.label} className={`swatch ${p.accent === id ? 'on' : ''}`} style={{ '--sw-light': a.light, '--sw-dark': a.dark }} aria-label={a.label}>
                  {p.accent === id && <span className="swatch-dot" />}
                </button>
              ))}
            </div>
          </Block>
          <Block label="оттенок поверхностей" hint="фон и карточки чуть теплее, холоднее или в тон акценту">
            <div className="flex flex-wrap gap-2">
              {Object.entries(TINTS).map(([id, t]) => <button key={id} type="button" className={`pill ${p.tint === id ? 'on' : ''}`} onClick={() => set({ tint: id })}>{t.label}</button>)}
            </div>
          </Block>
        </Card>
      </Section>
      <Section title="размер и форма">
        <Card className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <Block label="масштаб"><Seg value={p.font} onChange={(v) => set({ font: v })} options={Object.entries(FONT_SIZES).map(([k, v]) => [k, v[0]])} /></Block>
          <Block label="углы"><Seg value={p.radius} onChange={(v) => set({ radius: v })} options={Object.entries(RADII).map(([k, v]) => [k, v[0]])} /></Block>
          <div className="flex items-center justify-between gap-4 md:col-span-2"><div><div className="text-[14px] font-medium">анимации</div><div className="muted text-[12.5px]">плавные появления, переходы, «дыхание» индикаторов</div></div><Switch on={p.motion} onChange={(v) => set({ motion: v })} /></div>
        </Card>
      </Section>
      <Section title="навигация" hint={`«Сегодня» и «настройки» всегда на месте. Остальное можно убрать из панели — страницы останутся доступны через поиск (${kb('K')}).`}>
        <Card className="space-y-5">
          <Block label="боковая панель">
            <div className="rule">
              {NAV.map(({ to, label, icon: I }) => (
                <div key={to} className="row !py-2"><I size={15} className="muted" /><span className="flex-1 text-[14px]">{label}</span><Switch on={!p.hiddenNav.includes(to)} onChange={() => toggleNav(to)} /></div>
              ))}
            </div>
          </Block>
          <Block label="нижняя панель на телефоне" hint="от 2 до 5 вкладок">
            <div className="flex flex-wrap gap-1.5">
              {ALL.map(({ to, label }) => <button key={to} type="button" className={`pill ${p.tabbar.includes(to) ? 'on' : ''}`} onClick={() => toggleTab(to)}>{label}</button>)}
            </div>
            <div className="mt-3 flex items-center justify-between gap-4"><div className="text-[14px]">только иконки, без подписей</div><Switch on={p.compactNav} onChange={(v) => set({ compactNav: v })} /></div>
          </Block>
        </Card>
      </Section>
      <Section title="главная" hint="Порядок и состав блоков — кнопкой «настроить главную» на самой главной.">
        <Card className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <Block label="плотность"><Seg value={p.density} onChange={(v) => set({ density: v })} options={[['calm', 'спокойно'], ['full', 'подробно']]} /></Block>
          <Block label="как обращаться" hint="пусто — как в «общее → вы»"><input className="input" placeholder="сэр" value={p.address} onChange={(e) => set({ address: e.target.value })} /></Block>
          <div className="flex items-center justify-between gap-4"><span className="text-[14px]">приветствие</span><Switch on={p.showGreeting} onChange={(v) => set({ showGreeting: v })} /></div>
          <div className="flex items-center justify-between gap-4"><span className="text-[14px]">строка контекста</span><Switch on={p.showContext} onChange={(v) => set({ showContext: v })} /></div>
          <div className="flex items-center justify-between gap-4"><span className="text-[14px]">быстрые слова под полем</span><Switch on={p.showQuick} onChange={(v) => set({ showQuick: v })} /></div>
        </Card>
      </Section>
      <button className="btn-ghost btn-sm" onClick={() => { PREFS.reset(); setMode('auto') }}><RotateCcw size={13} /> сбросить вид</button>
    </>
  )
}

/* Помодоро: длина фокуса/перерывов, авто-перерыв, звук и голос. Хранится в базе — общее для сайта, Telegram и голоса, без перезапуска. */
const POMO_SOUNDS = [['bell', 'колокол'], ['ding', 'динь'], ['tick', 'щелчки'], ['off', 'без звука']]
/* Режим фрилансера: один выключатель на все «денежные» штуки для заказов, под ним — каждая ручка отдельно.
   Выключен — раздел «Заказы», пульс, налог и строки в дайджесте не показываются; данные не трогаются. */
function Freelance() {
  const [p, setP] = useState(null)
  const [, show] = useToast()
  const { bump } = useRefresh()
  useEffect(() => { api.freelance().then(setP).catch(show.err) }, []) // eslint-disable-line
  if (!p) return <Section title="режим фрилансера"><Skeleton h={160} /></Section>
  const save = (patch) => { const next = { ...p, ...patch }; setP(next); api.saveFreelance(patch).then((r) => { setP(r); bump(); window.dispatchEvent(new CustomEvent('freelance:changed', { detail: r })) }).catch(show.err) }
  const Row = ({ title, sub, k }) => (
    <div className="flex items-center justify-between gap-4"><div><div className="text-[14px] font-medium">{title}</div><div className="muted text-[12.5px]">{sub}</div></div><Switch on={!!p[k]} onChange={(v) => save({ [k]: v })} /></div>
  )
  return (
    <Section title="режим фрилансера" hint="Заказы, дедлайны, ожидаемые оплаты, таймер. Всё ниже можно включать по одному — что не нужно, нигде не всплывает.">
      <Card className="space-y-5">
        <div className="flex items-center justify-between gap-4"><div><div className="text-[15px] font-medium">я фрилансер</div><div className="muted text-[12.5px]">раздел «Заказы» в меню, блок на главной, дедлайны в дайджесте, оплаты в прогнозе кассы</div></div><Switch on={p.enabled} onChange={(v) => save({ enabled: v })} /></div>
        {p.enabled && (
          <div className="space-y-5 animate-rise">
            <div className="rule" />
            <Row k="late_nudge" title="следить за оплатами" sub="сдал, а денег нет — напомню в дайджесте и на главной, покажу, за сколько клиент платит обычно" />
            {p.late_nudge && (
              <Block label="задержкой считать" hint={p.late_days === 0 ? 'сразу после сдачи' : `${p.late_days} дн. после сдачи`}>
                <input type="range" min={0} max={30} step={1} value={p.late_days} onChange={(e) => setP({ ...p, late_days: Number(e.target.value) })} onMouseUp={(e) => save({ late_days: Number(e.target.value) })} onTouchEnd={(e) => save({ late_days: Number(e.target.value) })} onKeyUp={(e) => save({ late_days: Number(e.target.value) })} className="range w-full" />
              </Block>
            )}
            <Row k="rate_check" title="считать ставку по факту" sub="если гоняли таймер и была оценка часов — покажу «12 ч из 8 · 2 100 ₽/ч вместо 3 100» в карточке заказа" />
            {p.rate_check && (
              <Block label="ругаться при перерасходе от" hint={`${p.rate_tolerance} % сверх оценки`}>
                <input type="range" min={10} max={100} step={5} value={p.rate_tolerance} onChange={(e) => setP({ ...p, rate_tolerance: Number(e.target.value) })} onMouseUp={(e) => save({ rate_tolerance: Number(e.target.value) })} onTouchEnd={(e) => save({ rate_tolerance: Number(e.target.value) })} onKeyUp={(e) => save({ rate_tolerance: Number(e.target.value) })} className="range w-full" />
              </Block>
            )}
            <Block label="налог с дохода по заказам" hint={p.tax_percent ? `${p.tax_percent} % — вычитаю из ожидаемого в прогнозе, считаю за месяц` : 'не считать'}>
              <Seg value={String(p.tax_percent)} onChange={(v) => save({ tax_percent: Number(v) })} options={[['0', 'нет'], ['4', '4 % НПД'], ['6', '6 % НПД'], ['13', '13 %']]} />
            </Block>
            <Row k="weekly" title="фриланс в недельном отчёте" sub="заработано · часов · ставка · кто задерживает — три строки в конце «Недели в мыслях»" />
          </div>
        )}
      </Card>
    </Section>
  )
}

function Pomodoro() {
  const [p, setP] = useState(null)
  const [, show] = useToast()
  useEffect(() => { api.pomodoro().then(setP).catch(show.err) }, []) // eslint-disable-line
  if (!p) return <Section title="помодоро"><Skeleton h={160} /></Section>
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
    <Section title="помодоро" hint="Работает везде одинаково: сайт, Telegram («таймер», «перерыв»), голос. Менять можно на ходу — перезапуск не нужен.">
      <Card className="space-y-5">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {num('focus', 5, 90, 'фокус')}
          {num('short', 1, 30, 'короткий перерыв')}
          {num('long', 5, 60, 'длинный перерыв')}
          <Block label="длинный перерыв каждый…" hint={p.long_every ? `${p.long_every}-й помидор` : 'никогда'}>
            <Seg value={String(p.long_every)} onChange={(v) => save({ long_every: Number(v) })} options={[['0', 'никогда'], ['2', '2'], ['3', '3'], ['4', '4'], ['6', '6']]} />
          </Block>
        </div>
        <div className="flex items-center justify-between gap-4"><div><div className="text-[14px] font-medium">перерыв сам по себе</div><div className="muted text-[12.5px]">после фокуса перерыв стартует автоматически, после перерыва — жду вас</div></div><Switch on={p.auto_break} onChange={(v) => save({ auto_break: v })} /></div>
        <Block label="звук по завершении" hint="здесь и на колонках ПК (voice.bat)">
          <div className="flex flex-wrap items-center gap-3">
            <Seg value={p.sound} onChange={(v) => { save({ sound: v }); if (v !== 'off') playChime(v, p.volume) }} options={POMO_SOUNDS} />
            {p.sound !== 'off' && <button type="button" className="btn-ghost btn-sm" onClick={() => playChime(p.sound, p.volume)}><Volume2 size={13} /> послушать</button>}
          </div>
        </Block>
        {p.sound !== 'off' && (
          <Block label="громкость" hint={`${Math.round(p.volume * 100)}%`}>
            <input type="range" min={0.1} max={1} step={0.05} value={p.volume} onChange={(e) => setP({ ...p, volume: Number(e.target.value) })} onMouseUp={(e) => { save({ volume: Number(e.target.value) }); playChime(p.sound, Number(e.target.value)) }} onTouchEnd={(e) => save({ volume: Number(e.target.value) })} className="range w-full" />
          </Block>
        )}
        <div className="flex items-center justify-between gap-4"><div><div className="text-[14px] font-medium">сказать голосом</div><div className="muted text-[12.5px]">«Помидор готов» — на ПК через voice.bat; выключено — только звук</div></div><Switch on={p.voice} onChange={(v) => save({ voice: v })} /></div>
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
    audio.onerror = () => { setPlaying(null); show.err(new Error(v.engine === 'edge' ? 'Голоса Microsoft недоступны (нужен интернет)' : 'Не удалось озвучить — смотрите состояние → голос')) }
    try { await audio.play() } catch (e) { setPlaying(null) }
  }
  const pick = (v) => api.post('/api/voice/pick', { engine: v.engine, voice: v.id }).then(() => { show(`Голос: ${v.name}`); load() }).catch(show.err)
  return (
    <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {data.voices.map((v) => {
        const cur = isCur(v)
        return (
          <Card key={v.engine + v.id} className={`!p-3 flex items-center gap-3 ${cur ? 'ring-1 ring-[var(--accent)]' : ''}`}>
            <button className={`grid h-10 w-10 shrink-0 place-items-center rounded-full ${playing === v.id ? 'bg-accent text-accent-ink' : 'btn-ghost !p-0'}`} onClick={() => play(v)} title="Послушать">
              {playing === v.id ? '■' : '▶'}
            </button>
            <div className="min-w-0 flex-1">
              <div className="h4 truncate">{v.name}{cur && <span className="ml-2 text-[11px] font-normal text-accent">выбран</span>}</div>
              <div className="muted truncate text-[12px]">{v.kind}{v.engine === 'silero' ? ' · офлайн' : ''}</div>
            </div>
            {!cur && <button className="btn-ghost !py-1 !text-[12px]" onClick={() => pick(v)}>выбрать</button>}
          </Card>
        )
      })}
      <div className="faint text-[12px] sm:col-span-2 lg:col-span-3">Первое прослушивание голоса генерирует пример (несколько секунд). Silero — на вашем ПК, Microsoft — через интернет (используется и как запасной, если Silero не справился).</div>
    </div>
  )
}


function GoogleConnect({ show, dirty }) {
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState(false)
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
  const sync = () => { setBusy(true); api.post('/api/google/sync').then((r) => { show(`Выгружено ${r.pushed} из ${r.total}${r.error ? ' · ошибка: ' + r.error : ''}`); load() }).catch(show.err).finally(() => setBusy(false)) }
  const off = () => { if (!confirm('Отключить Google Календарь? События в Google останутся, новые перестанут туда попадать.')) return; api.post('/api/google/disconnect').then(() => { show('Отключено'); load() }).catch(show.err) }
  const ok = st.connected && st.enabled && !st.last_error
  return (
    <Card className="mb-4 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? 'bg-emerald-500' : st.connected ? 'bg-amber-500' : 'bg-neutral-400'}`} />
        <div>
          <div className="h4">{!st.configured ? 'нужны Client ID и secret' : !st.connected ? 'не подключён' : ok ? `подключён${st.email ? ' · ' + st.email : ''}` : st.last_error ? 'ошибка синхронизации' : 'подключён, но выключен'}</div>
          <div className="muted text-[13px]">
            {!st.configured ? <>Вставьте ключи ниже и нажмите «сохранить» — появится кнопка «подключить». Инструкция: README → «Google Календарь». Redirect URI для Google: <code>{st.redirect_uri}</code></>
              : !st.connected ? <>Нажмите «подключить» <b>на этом компьютере</b> (Google вернёт вас на <code>localhost</code>). Затем все события уйдут в Google автоматически.</>
              : st.last_error ? st.last_error
              : <>{st.synced} из {st.total} событий в Google{st.queued ? ` · в очереди ${st.queued}` : ''}{st.last_sync ? ` · синхронизация ${relTime(st.last_sync)}` : ''}{st.proxy ? ' · через прокси' : ''}</>}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {st.configured && !st.connected && <button className="btn-primary" disabled={busy || dirty} title={dirty ? 'Сначала сохраните настройки' : ''} onClick={connect}>{busy ? 'открываю Google…' : 'подключить'}</button>}
        {st.connected && <button className="btn-ghost" disabled={busy} onClick={sync}><RefreshCw size={15} /> выгрузить всё</button>}
        {st.connected && <button className="btn-ghost" onClick={off}>отключить</button>}
      </div>
    </Card>
  )
}

function PhoneAccess() {
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api.get('/api/phone').then(setInfo).catch((e) => setErr(e.message)) }, [])
  const [rotating, setRotating] = useState(false)
  const rotate = async () => {
    if (!confirm('Выпустить новый ключ доступа? Все телефоны, где сайт открыт по старой ссылке, потеряют доступ — нужно будет отсканировать новый QR.')) return
    setRotating(true)
    try { await api.post('/api/phone/rotate'); setInfo(await api.get('/api/phone')) } catch (e) { setErr(e.message) } finally { setRotating(false) }
  }
  if (err) return <Card><div className="neg text-[13px]">{/403/.test(err) ? 'Ссылки и QR для телефона выдаются только при открытии сайта с самого компьютера.' : err}</div></Card>
  if (!info) return <Skeleton h={120} />
  const remote = info.opened_from && !/^(localhost|127\.0\.0\.1)/.test(info.opened_from)
  return (
    <div className="space-y-3">
      {!info.tailscale && (
        <Card className="text-[14px]">
          <div className="h4">Tailscale не установлен</div>
          <div className="muted mt-1 leading-relaxed">
            1. На ПК: <a className="text-accent underline" href="https://tailscale.com/download/windows" target="_blank" rel="noreferrer">tailscale.com/download</a> → установить → войти через Google или Apple.<br />
            2. На телефоне: приложение «Tailscale» из App Store / Google Play → войти тем же аккаунтом → включить.<br />
            3. Один раз запустить <code>phone.bat</code> (откроет порт в брандмауэре Windows) — и обновить эту страницу: тут появятся адрес и QR-код.
          </div>
        </Card>
      )}
      {info.items.length > 0 && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {info.items.map((it) => (
            <Card key={it.kind} className="flex items-center gap-4">
              {it.qr ? <img src={it.qr} alt="QR" width={112} height={112} className="shrink-0 rounded-lg bg-white p-1" /> : null}
              <div className="min-w-0">
                <div className="label">{it.title}</div>
                <a className="h4 mt-1 block truncate text-accent" href={it.url} target="_blank" rel="noreferrer">{it.url.replace(/\?t=.*$/, '')}</a>
                <div className="faint mt-2 text-[12px]">Наведи камеру телефона на QR → открыть → «Добавить на экран Домой». В QR зашит ключ доступа: после первого захода телефон запомнит его на год.</div>
              </div>
            </Card>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-ghost" onClick={rotate} disabled={rotating}><RefreshCw size={14} className={rotating ? 'animate-spin' : ''} /> новый ключ доступа</button>
        <span className="faint text-[12px]">Потеряли телефон или показали QR не тому — выпустите новый ключ, старые ссылки перестанут работать.</span>
      </div>
      <div className="faint text-[12px]">
        {remote ? <span className="pos">Эта страница уже открыта не с самого ПК ({info.opened_from}) — значит, доступ работает.</span>
          : <>Не открывается? Скорее всего, порт закрыт брандмауэром Windows — запустите <code>phone.bat</code> (один раз, попросит права администратора). Ассистент при этом должен быть запущен.</>}
      </div>
    </div>
  )
}


function MiniApp({ current, onUse }) {
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
          <div className="h4">приложение внутри Telegram {ok ? '· подключено' : current ? '· адрес задан, туннель не виден' : '· не подключено'}</div>
          <div className="muted mt-0.5 text-[13px]">
            {!st.local ? 'Состояние туннеля видно только с самого компьютера.'
              : f.installed === false ? <>Tailscale не установлен — сначала раздел «телефон» (общее), затем <code>funnel.bat</code>.</>
              : f.on && url ? <>Туннель работает: <span className="num">{url}</span>{matches ? ' — и он же в боте.' : ' — нажмите «использовать», сохраните и перезапустите start.bat.'}</>
              : <>Туннель не запущен. Запустите <code>funnel.bat</code> — он покажет адрес https://…ts.net и включит его. Подробно: <code>docs/telegram-miniapp.md</code></>}
          </div>
        </div>
      </div>
      {st.local && f.on && url && !matches && <button className="btn-ghost" onClick={() => onUse(url)}>использовать этот адрес</button>}
    </Card>
  )
}


/* Список backup-*.db + «восстановить» (ROADMAP P1). После restore — перезапуск start.bat. */
function BackupRestore({ show }) {
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
      show(`База из «${r.restored}». Закройте start.bat и запустите снова.` + (r.safety ? ` Страховка: ${r.safety}` : ''))
      load()
    } catch (e) { show.err(e) } finally { setBusy(false) }
  }
  const fmtSize = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} МБ` : `${Math.max(1, Math.round(n / 1024))} КБ`)
  return (
    <Card className="mt-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="h4">восстановить из бэкапа</div>
          <div className="muted text-[12.5px]">Текущая база сохранится как backup-pre-restore-…. Картинки в data/media не откатываются. После — перезапуск start.bat.</div>
        </div>
        <button className="btn-icon outlined" data-tip="обновить список" onClick={load} aria-label="Обновить"><RefreshCw size={14} /></button>
      </div>
      {list === null ? <Skeleton h={72} /> : list.length === 0 ? (
        <div className="muted text-[13px]">Копий пока нет. «Бэкап сейчас» выше или дождитесь 03:00 (если бэкапы включены).</div>
      ) : (
        <ul className="divide-y hair max-h-[280px] overflow-y-auto">
          {list.map((b) => (
            <li key={b.name} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13.5px] font-medium">{b.pre_restore ? 'страховка перед прошлым restore' : relTime(b.at)} <span className="faint mono text-[11px]">· {b.name.replace(/^backup-(?:pre-restore-)?/, '').replace(/\.db$/, '')}</span></div>
                <div className="faint text-[12px]">{fmtSize(b.size)}{b.pre_restore ? ' · pre-restore' : ''}</div>
              </div>
              <button className="btn-soft btn-sm !h-7" onClick={() => setPick(b)}>восстановить</button>
            </li>
          ))}
        </ul>
      )}
      <Confirm open={!!pick} onClose={() => !busy && setPick(null)} title="Восстановить базу?"
        text={pick ? `Файл «${pick.name}» (${relTime(pick.at)}) заменит data/assistant.db. Текущая копия уйдёт в backup-pre-restore. После — закройте окно start.bat и запустите снова.` : ''}
        onOk={doRestore} danger />
      {busy && <div className="muted text-[12.5px]">копирую…</div>}
    </Card>
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

const PROV_LABELS = { openrouter: 'OpenRouter', groq: 'Groq', nvidia: 'NVIDIA', deepseek: 'DeepSeek', gemini: 'Gemini', custom: 'свой' }
const PROV_HINT = {
  openrouter: ['Бесплатно, из России без VPN. Один ключ — десятки моделей; ассистент сам выбирает лучшую бесплатную (DeepSeek / GLM / Qwen). Лимит ~50–200 запросов в день.', 'https://openrouter.ai/keys', 'openrouter.ai → Sign in (через Google или GitHub) → Keys → Create key → скопировать «sk-or-…»'],
  groq: ['Бесплатно, из России без VPN, очень быстрые ответы (GPT-OSS, Llama, Qwen). Лимит ~1000 запросов в день. Рекомендую.', 'https://console.groq.com/keys', 'console.groq.com → войти через Google → API Keys → Create → скопировать «gsk_…»'],
  nvidia: ['Бесплатно, 120+ открытых моделей (DeepSeek, Qwen, Kimi). Нужна регистрация по e-mail.', 'https://build.nvidia.com/', 'build.nvidia.com → Login → любая модель → Get API Key → «nvapi-…»'],
  deepseek: ['Официальный DeepSeek. Не бесплатно, но очень дёшево (≈1 ₽ за длинный разговор), пополнение от $2 — нужна зарубежная карта или посредник.', 'https://platform.deepseek.com/api_keys', 'platform.deepseek.com → API keys → Create → «sk-…»'],
  gemini: ['Google Gemini. Из России работает только через прокси/VPN, модели регулярно отключают. Не рекомендую.', 'https://aistudio.google.com/apikey', 'aistudio.google.com → Get API key'],
  custom: ['Любой OpenAI-совместимый сервер: LM Studio, vLLM, ProxyAPI и т.п. Укажите адрес с /v1 и ключ (если нужен).', '', ''],
}

function CloudHint({ prov, providers }) {
  const [text, url, steps] = PROV_HINT[prov] || PROV_HINT.custom
  return (
    <div className="md:col-span-2 rounded-2xl fill px-4 py-3 text-[13px] leading-relaxed">
      <div>{text}</div>
      {steps && <div className="muted mt-1">Как получить ключ: {steps}</div>}
      {url && <a className="text-accent mt-1 inline-block" href={url} target="_blank" rel="noreferrer">открыть страницу ключей ↗</a>}
      <div className="faint mt-1">Как это работает: «привет», «что такое …», «напиши …» → облако. Деньги, календарь, задачи, заметки → локальная модель, в облако не уходят. Принудительно: «облако, …» или «локально, …». После сохранения — перезапустить start.bat.</div>
    </div>
  )
}

function SettingField({ it, value, onChange, providers }) {
  const [reveal, setReveal] = useState(false)
  if (it.key === 'brain.cloud.provider') {
    return <Field label="Провайдер облака"><Seg value={value || 'gemini'} onChange={onChange} options={['openrouter', 'groq', 'nvidia', 'deepseek', 'gemini', 'custom'].map((p) => [p, PROV_LABELS[p]])} /></Field>
  }
  if (it.type === 'bool') {
    return (
      <Field label={it.label}>
        <Seg value={value ? 'on' : 'off'} onChange={(v) => onChange(v === 'on')} options={[['on', 'да'], ['off', 'нет']]} />
      </Field>
    )
  }
  if (it.key === 'brain.mode') {
    return <Field label={it.label}><Seg value={value} onChange={onChange} options={[['local', 'только локально'], ['hybrid', 'гибрид'], ['cloud', 'облако']]} /></Field>
  }
  if (it.key === 'brain.sorter.where') {
    return <Field label="Сообщения-списки разбирает" hint="одно сообщение → задачи, встречи, люди, заказы, долги…"><Seg value={value || 'cloud'} onChange={onChange} options={[['cloud', 'облако'], ['auto', 'ПК, при сбое облако'], ['local', 'только ПК']]} /></Field>
  }
  if (it.key === 'brain.ollama.small_model') {
    const presets = [['', 'выкл (основная)'], ['qwen2.5:1.5b', 'qwen2.5:1.5b · 1 ГБ'], ['qwen2.5:3b', 'qwen2.5:3b · 2 ГБ'], ['gemma3:1b', 'gemma3:1b · 0.8 ГБ']]
    return (
      <Field label="Малая модель для мини-задач" hint="судья «трата или заказ?», подколы, уборка памяти — не грузят основную. После выбора: в cmd «ollama pull <имя>», статус — в «система → состояние»">
        <Seg value={presets.some(([v]) => v === (value || '')) ? (value || '') : '__custom'} onChange={(v) => v !== '__custom' && onChange(v)} options={[...presets, ['__custom', 'своя']]} />
        <input className="input mt-2" value={value ?? ''} onChange={(e) => onChange(e.target.value)} placeholder="имя модели в Ollama" />
      </Field>
    )
  }
  if (it.key === 'brain.vision.where') {
    return <Field label="Картинки смотрит"><Seg value={value || 'auto'} onChange={onChange} options={[['auto', 'ПК, при сбое облако'], ['cloud', 'облако'], ['local', 'только ПК']]} /></Field>
  }
  return (
    <Field label={it.label} hint={it.secret ? (it.set ? 'сохранён · введите новый, чтобы заменить' : 'не задан') : undefined}>
      <div className="relative">
        <input className="input pr-10" type={it.secret && !reveal ? 'password' : 'text'} inputMode={it.type === 'int' ? 'numeric' : undefined}
          value={it.secret && value === it.value ? '' : (value ?? '')} onChange={(e) => onChange(e.target.value)} placeholder={it.secret && it.set ? it.value : ''} autoComplete="off" />
        {it.secret && <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 faint" onClick={() => setReveal((v) => !v)}>{reveal ? <EyeOff size={15} /> : <Eye size={15} />}</button>}
      </div>
    </Field>
  )
}
