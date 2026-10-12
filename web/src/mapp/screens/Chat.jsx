/* mapp/screens/Chat.jsx — мобильный чат (порт референса screens/Chat.tsx).
 *
 * История — GET /api/chat/history, отправка — потоковый chatStream: та же схема,
 * что у десктопного components/Chat.jsx (стриминг по кускам, карточка/actions
 * в финале, retry при обрыве). Чипсы-подсказки — русские фразы ядру (i18n-raw,
 * как suggestions() десктопа). Мок-карточек референса нет — только живые данные.
 */
import { useEffect, useRef, useState } from 'react'
import { ArrowUp, ChevronLeft, Ellipsis, Mic } from 'lucide-react'
import { api, chatStream } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { MarvinOrb } from '../ui.jsx'

const fromServer = (h) => (h || []).map((m, i) => ({
  id: m.id ?? `h${i}`,
  from: m.role === 'user' ? 'me' : 'marvin',
  text: m.text || '',
  at: m.at,
}))

// i18n-raw: подсказки уходят в ядро — ядро понимает русские фразы (как десктопные suggestions)
const SUGGEST = ['что сегодня главное?', 'кто мне должен?', 'план на неделю', 'перенеси спортзал']

export default function MChat({ seed, go, toast }) {
  const { t } = useI18n()
  const [msgs, setMsgs] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const listRef = useRef(null)
  const idRef = useRef(1000)

  useEffect(() => {
    api.chatHistory(60).then((h) => setMsgs(fromServer(h))).catch(() => setMsgs([]))
  }, [])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: (msgs || []).length > 4 ? 'smooth' : 'auto' })
  }, [msgs, busy])

  useEffect(() => {
    if (!seed) return
    if (seed.send) send(seed.text)
    else setText(seed.text || '')
  }, [seed?.n]) // eslint-disable-line

  const send = async (q) => {
    const v = String(q ?? text).trim()
    if (!v || busy) return
    setText('')
    setMsgs((m) => [...(m || []), { id: ++idRef.current, from: 'me', text: v }])
    setBusy(true)
    let streamed = false
    try {
      const r = await chatStream(v, (piece) => {
        setMsgs((m) => {
          const last = m[m.length - 1]
          if (streamed && last?.streaming) return [...m.slice(0, -1), { ...last, text: last.text + piece }]
          streamed = true
          return [...m, { id: ++idRef.current, from: 'marvin', text: piece, streaming: true }]
        })
      })
      setMsgs((m) => (streamed && m[m.length - 1]?.streaming ? m.slice(0, -1) : m)
        .concat({ id: ++idRef.current, from: 'marvin', text: r.text }))
    } catch {
      setMsgs((m) => (streamed && m[m.length - 1]?.streaming ? m.slice(0, -1) : m)
        .concat({ id: ++idRef.current, from: 'marvin', text: t('chat.core_down'), retry: v }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-testid="m-chat" className="anim-screen absolute inset-0 flex flex-col">
      <div className="relative z-30 flex items-center gap-3 px-4 pb-3 pt-[56px]">
        <button
          onClick={() => go('home')}
          aria-label={t('common.back')}
          data-testid="m-chat-back"
          className="m-glass grid h-10 w-10 shrink-0 place-items-center rounded-full transition active:scale-90"
        >
          <ChevronLeft size={20} />
        </button>
        <MarvinOrb size={40} />
        <div className="min-w-0 flex-1">
          <div className="text-[17px] font-semibold leading-tight">{t('m.tab_home')}</div>
          <div className="flex items-center gap-1.5 text-[12.5px] text-white/60">
            <span className="h-1.5 w-1.5 rounded-full bg-[#3ddc97] shadow-[0_0_6px_#3ddc97]" />
            {busy ? t('m.chat_typing') : t('m.chat_online')}
          </div>
        </div>
        <button
          aria-label={t('common.more_actions')}
          data-testid="m-chat-more"
          onClick={() => toast(t('m.soon_sub'))}
          className="m-glass grid h-10 w-10 shrink-0 place-items-center rounded-full"
        >
          <Ellipsis size={18} />
        </button>
      </div>

      <div
        ref={listRef}
        className="no-scrollbar flex-1 space-y-3 overflow-y-auto px-4 pb-3 pt-3"
        style={{
          maskImage: 'linear-gradient(to bottom, transparent 0, #000 22px, #000 calc(100% - 14px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, transparent 0, #000 22px, #000 calc(100% - 14px), transparent 100%)',
        }}
      >
        {msgs === null && (
          <div className="space-y-3 pt-2">
            {[70, 45, 60].map((w, i) => (
              <div key={i} className="anim-fade h-9 rounded-2xl bg-white/[0.07]" style={{ width: `${w}%` }} />
            ))}
          </div>
        )}
        {msgs !== null && msgs.length === 0 && (
          <div className="flex h-full flex-col items-start justify-end pb-4">
            <div className="text-[19px] font-semibold">{t('chat.hello')}</div>
            <div className="mt-1 text-[13.5px] leading-relaxed text-white/60">{t('chat.hello_hint')}</div>
          </div>
        )}
        {(msgs || []).map((m) => (
          m.from === 'me' ? (
            <div key={m.id} className="anim-rise flex justify-end">
              <div className="m-active max-w-[80%] rounded-[22px] rounded-br-[8px] px-4 py-2.5 text-[15px] leading-[1.4]">
                {m.text}
              </div>
            </div>
          ) : (
            <div key={m.id} className="anim-rise flex items-end gap-2">
              <MarvinOrb size={26} className="mb-1" />
              <div className="m-card max-w-[84%] rounded-[22px] rounded-bl-[8px] px-4 py-3 text-[15px] leading-[1.42]">
                {m.text}
                {m.retry && (
                  <div className="mt-2">
                    <button
                      onClick={() => send(m.retry)}
                      className="rounded-full bg-white/10 px-3.5 py-1.5 text-[13px] font-medium"
                    >
                      {t('chat.retry')}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )
        ))}
        {busy && !msgs?.at(-1)?.streaming && (
          <div className="anim-rise flex items-end gap-2">
            <MarvinOrb size={26} className="mb-1" />
            <div className="m-card flex gap-1.5 rounded-[22px] rounded-bl-[8px] px-4 py-4">
              {[0, 1, 2].map((i) => (
                <span key={i} className="typing-dot h-2 w-2 rounded-full bg-white/75" style={{ animationDelay: `${i * 0.15}s` }} />
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="relative z-30 px-4 pb-[34px] pt-1">
        <div className="no-scrollbar -mx-4 mb-2.5 flex gap-2 overflow-x-auto px-4">
          {SUGGEST.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="m-glass shrink-0 rounded-full px-3.5 py-2 text-[13px] font-medium text-white/85 transition active:scale-95"
            >
              {s}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => { e.preventDefault(); send() }}
          className="m-glass-strong flex h-[56px] items-center gap-2 rounded-full pl-5 pr-1.5"
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t('m.chat_ph')}
            aria-label={t('m.chat_ph')}
            data-testid="m-chat-input"
            className="min-w-0 flex-1 bg-transparent text-[15.5px] outline-none placeholder:text-white/45"
          />
          {text.trim() ? (
            <button type="submit" aria-label={t('chat.send')} data-testid="m-chat-send" className="m-fab anim-pop grid h-11 w-11 place-items-center rounded-full">
              <ArrowUp size={20} strokeWidth={2.5} />
            </button>
          ) : (
            <button type="button" aria-label={t('m.qa_voice')} data-testid="m-chat-mic" onClick={() => toast(t('m.soon_sub'))} className="grid h-11 w-11 place-items-center rounded-full bg-white/10">
              <Mic size={19} />
            </button>
          )}
        </form>
      </div>
    </div>
  )
}
