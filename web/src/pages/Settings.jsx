import { createPortal } from 'react-dom'
import { useEffect, useState } from 'react'
import { Bell, BellOff, Download, HardDriveDownload, RefreshCw, Eye, EyeOff, Smartphone } from 'lucide-react'
import { api, relTime } from '../lib/api'
import { Card, Field, PageHead, Section, Toast, useToast, Skeleton, Seg } from '../components/ui'
import { enableNotifications, disableNotifications, notifyEnabled, notifyState } from '../lib/notify'

const GROUPS = [
  ['telegram', 'telegram', 'Бот отвечает только вашему ID. Токен — от @BotFather, ID — от @userinfobot.'],
  ['brain.cloud', 'облако', 'Для общих вопросов («объясни», «напиши», «посоветуй»). Личные данные туда не уходят. Ключ берётся за минуту, карта не нужна.'],
  ['brain', 'мозг', 'Локальная модель (Ollama) — всё личное: деньги, календарь, задачи, заметки. Никуда не уходит.'],
  ['voice', 'голос и ПК', 'Whisper распознаёт на вашем ПК (никуда не уходит), отвечает Silero. voice.bat — голос в комнате, управление программами, утренний доклад, ночной режим и авто-игровой режим. Скриншоты «что на экране» и фото чеков — через модель зрения (см. «мозг»).'],
  ['google', 'google календарь', 'События ассистента появляются в Google Календаре — на телефоне, часах, в любом приложении. Только в одну сторону: ассистент → Google. Client ID и secret — 5 минут по инструкции в README (бесплатно, карта не нужна).'],
  ['backup', 'бэкапы', 'Ежедневно в 03:00. Вторая копия — на другой диск или в папку Яндекс.Диска / Google Drive.'],
  ['owner', 'вы', ''],
  ['finance', 'финансы', ''],
]

export default function Settings({ health }) {
  const [data, setData] = useState(null)
  const [draft, setDraft] = useState({})
  const [status, setStatus] = useState(null)
  const [saving, setSaving] = useState(false)
  const [restart, setRestart] = useState(false)
  const [toast, show] = useToast()
  const [notif, setNotif] = useState(notifyState())
  const [gem, setGem] = useState(null)   // результат проверки облака

  const load = () => Promise.all([api.settings().then(setData), api.status().then(setStatus)]).catch(show.err)
  useEffect(() => { load() }, [])

  const val = (it) => (it.key in draft ? draft[it.key] : it.value)
  const dirty = Object.keys(draft).length > 0

  const save = async () => {
    setSaving(true)
    try {
      const r = await api.saveSettings(draft)
      setDraft({}); await load()
      if (r.restart) setRestart(true)
      show(r.changed.length ? `Сохранено: ${r.changed.length}` : 'Нечего сохранять')
    } catch (e) { show.err(e) } finally { setSaving(false) }
  }

  const toggleNotif = async () => {
    if (notifyEnabled()) { disableNotifications(); setNotif('off'); return }
    const p = await enableNotifications(); setNotif(p === 'granted' ? 'granted' : p)
  }

  return (
    <div className="space-y-12 sm:space-y-16">
      <PageHead kicker="настройки и состояние" title="настройки" idx={7}
        right={dirty && <button className="btn-primary" disabled={saving} onClick={save}>{saving ? 'сохраняю…' : 'сохранить'}</button>} />

      {restart && (
        <div className="panel animate-rise flex flex-wrap items-center justify-between gap-3 p-4" style={{ borderColor: 'var(--warn)' }}>
          <div className="text-[14px]"><span className="warn font-medium">Нужен перезапуск.</span> <span className="muted">Закройте окно ассистента и снова запустите start.bat — новые настройки Telegram/мозга/бэкапа подхватятся.</span></div>
          <button className="btn-ghost !py-1.5" onClick={() => setRestart(false)}>понял</button>
        </div>
      )}

      {/* статус — внутри настроек, отдельной страницы нет */}
      <Section title="состояние" idx={1} action={<button className="btn-icon" title="Обновить" onClick={load}><RefreshCw size={15} /></button>}>
        {!status ? <Skeleton h={140} /> : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <StatusCard ok={status.ollama.ok} warn={status.game_mode} title="локальный мозг" line1={status.game_mode ? 'игровой режим · спит' : status.ollama.model}
              line2={status.game_mode ? 'модель выгружена из видеопамяти, всё идёт в облако' : status.ollama.ok ? (status.ollama.gpu && !status.ollama.gpu.includes('целиком') ? status.ollama.gpu : status.ollama.embed ? `смысловой поиск: да${status.ollama.gpu ? ' · в видеокарте целиком' : ''}` : `поиск по смыслу: нет (ollama pull ${status.ollama.embed_model})`) : status.ollama.diag}
              action={<button className="btn-ghost !py-1 !text-[12px]" title="Выгрузить модель из видеопамяти на время игры" onClick={() => api.post('/api/game', { on: !status.game_mode }).then(() => load()).catch(show.err)}>{status.game_mode ? 'игра окончена' : '🎮 иду играть'}</button>} />
            <StatusCard ok={status.telegram.running} warn={status.telegram.configured && !status.telegram.running} title="telegram"
              line1={!status.telegram.configured ? 'не настроен' : status.telegram.running ? 'бот на связи' : 'настроен, но не запущен (--no-tg?)'}
              line2={status.telegram.last_message ? `последнее сообщение ${relTime(status.telegram.last_message)}` : 'сообщений ещё не было'} />
            <StatusCard ok={status.backup.enabled && !!status.backup.last} warn={status.backup.enabled && !status.backup.last} title="бэкап"
              line1={!status.backup.enabled ? 'выключен' : status.backup.last ? `последний ${relTime(status.backup.last)}` : 'ещё не делался (в 03:00)'}
              line2={`${status.backup.count} копий · ${status.backup.dir}${status.backup.extra_dir ? ` + ${status.backup.extra_dir}` : ''}`} />
            <StatusCard ok={status.gemini.enabled && !status.gemini.last_error && gem?.ok !== false} warn={!status.gemini.enabled || (status.gemini.enabled && !status.gemini.last_error && !gem)} title={`облако · ${status.gemini.title || 'gemini'}`}
              line1={!status.gemini.enabled ? 'выключен' : gem ? (gem.ok ? 'отвечает' : 'ошибка') : status.gemini.last_error ? 'ошибка' : status.gemini.model}
              line2={gem && !gem.ok ? gem.detail : gem?.ok ? `модель ${gem.model}${status.gemini.proxy ? ' · через прокси' : ''}` : status.gemini.last_error || (status.gemini.enabled ? `${status.gemini.model}${status.gemini.proxy ? ' · через прокси' : ' · напрямую'}` : 'ключ не задан или режим local')}
              action={status.gemini.enabled && <button className="btn-ghost !py-1 !text-[12px]" onClick={() => { setGem({ pending: true }); api.post('/api/status/gemini').then(setGem).catch((e) => setGem({ ok: false, detail: e.message })) }}>{gem?.pending ? 'проверяю…' : 'проверить'}</button>} />
            {status.voice && <StatusCard ok={status.voice.stt && status.voice.stt_ready && (!status.voice.tts || status.voice.tts_ready)} warn={status.voice.stt && !status.voice.stt_ready} title="голос"
              line1={!status.voice.stt ? 'не установлен' : !status.voice.stt_ready ? (status.voice.stt_error ? 'ошибка' : 'загружается…') : `whisper-${status.voice.stt_model} · ${status.voice.tts ? status.voice.tts_engine : 'без озвучки'}`}
              line2={status.voice.stt_error || status.voice.tts_error || (!status.voice.stt ? 'запустите update.bat — поставит распознавание и голос' : status.voice.stt_ready ? `голосовые в Telegram работают · ответ голосом: ${{ voice: 'на голосовые', always: 'всегда', never: 'никогда' }[status.voice.reply] || status.voice.reply}` : 'первый запуск качает модели (~600 МБ), подождите пару минут')} />}
          </div>
        )}
        {status && (
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] faint">
            <span>ядро v{status.version}</span>
            <span>база {(status.db.size / 1024 / 1024).toFixed(1)} МБ</span>
            <span>{status.db.events} событий</span><span>{status.db.tasks} задач</span><span>{status.db.transactions} операций</span>
            <span>{status.db.notes} заметок</span><span>{status.db.links} ссылок</span>
            <span>ПК-клиент: {status.pc?.alive ? `на связи · ${{ idle: 'ждёт', listening: 'слушает', thinking: 'думает', speaking: 'говорит', off: 'микрофон выкл' }[status.pc.mode] || status.pc.mode}` : 'не запущен (voice.bat)'}</span>
            <span>зрение: {status.vision || '—'}</span>
            {status.errors.length > 0 && <span className="neg">ошибок за сессию: {status.errors.length} · {status.errors[status.errors.length - 1].text}</span>}
          </div>
        )}
      </Section>

      {/* доступ с телефона */}
      <Section title="телефон" idx={2} hint="Сайт открывается с телефона без интернета наружу: через Tailscale из любой сети или по домашнему Wi-Fi.">
        <PhoneAccess />
      </Section>

      {/* уведомления и PWA */}
      <Section title="уведомления" idx={3} hint="Напоминания и действия из Telegram — прямо в браузере. На iPhone: Поделиться → «На экран Домой», затем включить здесь.">
        <Card className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {notifyEnabled() ? <Bell size={20} className="text-accent" /> : <BellOff size={20} className="faint" />}
            <div>
              <div className="h4">{notifyEnabled() ? 'включены' : notif === 'denied' ? 'запрещены в браузере' : notif === 'unsupported' ? 'браузер не поддерживает' : 'выключены'}</div>
              <div className="muted text-[13px]">{notif === 'denied' ? 'Разрешите уведомления для этого сайта в настройках браузера.' : 'Напоминания о событиях и дедлайнах, добавления из Telegram.'}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a className="btn-ghost" href="/manifest.json" target="_blank" rel="noreferrer" title="PWA-манифест"><Smartphone size={15} /> на телефон</a>
            <button className="btn-primary" disabled={notif === 'denied' || notif === 'unsupported'} onClick={toggleNotif}>{notifyEnabled() ? 'выключить' : 'включить'}</button>
          </div>
        </Card>
      </Section>

      {/* настройки config.yaml */}
      {!data ? <Skeleton h={300} /> : GROUPS.map(([prefix, title, hint], gi) => {
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
          <Section key={prefix} title={title} idx={gi + 4} hint={hint}>
            {prefix === 'voice' && <VoicePicker show={show} />}
            {prefix === 'google' && <GoogleConnect show={show} dirty={dirty} />}
            <Card className="grid grid-cols-1 gap-5 md:grid-cols-2">
              {items.map((it) => <SettingField key={it.key} it={it} value={val(it)} onChange={(v) => setDraft((d) => ({ ...d, [it.key]: v }))} providers={status?.gemini?.providers} />)}
              {prefix === 'brain.cloud' && <CloudHint prov={val(items.find((it) => it.key === 'brain.cloud.provider')) || 'gemini'} providers={status?.gemini?.providers} />}
            </Card>
          </Section>
        )
      })}

      {/* данные */}
      <Section title="данные" idx={9} hint="Всё лежит в data/assistant.db на вашем компьютере. Экспорт — на всякий случай и для Excel.">
        <Card className="flex flex-wrap items-center gap-2">
          <button className="btn-ghost" onClick={() => api.backupNow().then((r) => show(r.ok ? 'Копия сделана' : 'Бэкап выключен')).catch(show.err)}><HardDriveDownload size={15} /> бэкап сейчас</button>
          <a className="btn-ghost" href="/api/export/transactions.csv"><Download size={15} /> операции.csv</a>
          <a className="btn-ghost" href="/api/export/events.csv"><Download size={15} /> календарь.csv</a>
          <a className="btn-ghost" href="/api/export/tasks.csv"><Download size={15} /> задачи.csv</a>
          <a className="btn-ghost" href="/api/export/notes.csv"><Download size={15} /> заметки.csv</a>
          <a className="btn-soft" href="/api/export/all.json"><Download size={15} /> всё в json</a>
          <button className="btn-soft" onClick={() => api.reindex().then((r) => show(`Проиндексировано: ${r.indexed}`)).catch(show.err)}><RefreshCw size={15} /> переиндексировать мозг</button>
        </Card>
      </Section>

      {dirty && createPortal(<div className="toast-in fixed inset-x-0 z-[70] flex justify-center md:bottom-8" style={{ bottom: 'calc(5.5rem + env(safe-area-inset-bottom, 0px))' }}><button className="btn-dark shadow-lg" disabled={saving} onClick={save}>{saving ? 'сохраняю…' : 'сохранить изменения'}</button></div>, document.body)}
      <Toast {...toast} />
    </div>
  )
}

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
            <button className={`grid h-10 w-10 shrink-0 place-items-center rounded-full ${playing === v.id ? 'bg-accent text-white' : 'btn-ghost !p-0'}`} onClick={() => play(v)} title="Послушать">
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
  if (err) return <Card><div className="neg text-[13px]">{err}</div></Card>
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
                <a className="h4 mt-1 block truncate text-accent" href={it.url} target="_blank" rel="noreferrer">{it.url}</a>
                {it.alt && <div className="muted mt-0.5 truncate text-[12px]">или {it.alt}</div>}
                <div className="faint mt-2 text-[12px]">Наведи камеру телефона на QR → открыть → «Добавить на экран Домой».</div>
              </div>
            </Card>
          ))}
        </div>
      )}
      <div className="faint text-[12px]">
        {remote ? <span className="pos">Эта страница уже открыта не с самого ПК ({info.opened_from}) — значит, доступ работает.</span>
          : <>Не открывается? Скорее всего, порт закрыт брандмауэром Windows — запустите <code>phone.bat</code> (один раз, попросит права администратора). Ассистент при этом должен быть запущен.</>}
      </div>
    </div>
  )
}


function StatusCard({ ok, warn, title, line1, line2, action }) {
  const color = ok ? 'var(--pos)' : warn ? 'var(--warn)' : 'var(--neg)'
  return (
    <Card className="!p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2"><span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} /><span className="label">{title}</span></div>
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
