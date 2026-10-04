/* components/CaptureSheet.jsx — шторка быстрого ввода по центральной кнопке «+» дока.

   Макет владельца «вариант B» («быстрый ввод · шторка по кнопке „+“»):
   композер-пилюля с акцентной кнопкой отправки, чипсы типа записи
   (трата / задача / встреча / мысль) и подсказка «можно писать так» со
   строками-примерами. Строку отправляем тем же api.chat, что и композер
   главной: правила ядра понимают «задача: …» / «трата: …» офлайн, а
   свободная фраза («встреча в среду в 15», «идея: …») разбирается дальше.
   Никакой новой логики здесь нет — только форма.
*/

import { useEffect, useRef, useState } from 'react'
import { ArrowUp } from 'lucide-react'
import { useI18n, t as T } from '../lib/i18n'
import { api } from '../lib/api'
import { toast } from './ui'

/* Тип записи → каким префиксом уходит строка ядру. null — без префикса,
   ядро само разбирает фразу (встречи и мысли пишутся человеческим языком). */
const KINDS = [
  { id: 'expense', label: 'cap.expense', seed: 'qa.seed_expense' },
  { id: 'task', label: 'cap.task', seed: 'qa.seed_task' },
  { id: 'event', label: 'cap.event', seed: null },
  { id: 'note', label: 'cap.note', seed: 'cap.seed_note' },
]
const EXAMPLES = [
  { text: 'cap.ex1', hint: 'cap.ex1_h' },
  { text: 'cap.ex2', hint: 'cap.ex2_h' },
  { text: 'cap.ex3', hint: 'cap.ex3_h' },
]

export default function CaptureSheet({ open, onClose }) {
  const { t } = useI18n()
  const [kind, setKind] = useState('expense')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const inputRef = useRef(null)

  /* шторка открылась — сразу в поле, как в нативном «быстром вводе» */
  useEffect(() => {
    if (!open) return
    setText('')
    setKind('expense')
    const id = setTimeout(() => inputRef.current?.focus(), 240)
    return () => clearTimeout(id)
  }, [open])

  const send = async () => {
    const txt = text.trim()
    if (!txt || busy) return
    setBusy(true)
    const seed = KINDS.find((k) => k.id === kind)?.seed
    try {
      await api.chat(seed ? `${T(seed)}: ${txt}` : txt)
      toast(t(kind === 'expense' ? 'qa.expense_added' : 'qa.added'))
      onClose?.()
    } catch {
      toast(t('common.error'), { kind: 'err' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {/* композер-пилюля макета: точка акцента, поле, акцентная кнопка отправки */}
      <div className="cin">
        <i aria-hidden="true"></i>
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); send() } }}
          placeholder={t('cap.ph')}
          aria-label={t('cap.title')}
          maxLength={500}
          autoComplete="off"
        />
        <button type="button" className="go" onClick={send} disabled={busy || !text.trim()}
          aria-label={t('common.add')} title={t('common.add')}>
          <ArrowUp size={20} aria-hidden="true" />
        </button>
      </div>

      {/* тип записи: трата / задача / встреча / мысль */}
      <div className="chs" role="group" aria-label={t('cap.kind')}>
        {KINDS.map((k) => (
          <button key={k.id} type="button" className={kind === k.id ? 'on' : ''} aria-pressed={kind === k.id}
            onClick={() => setKind(k.id)}>
            {t(k.label)}
          </button>
        ))}
      </div>

      {/* подсказка: какими строками можно писать */}
      <div className="gh">{t('cap.howto')}</div>
      <div>
        {EXAMPLES.map((ex, i) => (
          <button key={ex.text} type="button" className="kv" style={{ width: '100%', textAlign: 'left', cursor: 'text' }}
            onClick={() => { setText(t(ex.text)); inputRef.current?.focus() }}>
            <span style={{ color: 'var(--ink)' }}>
              <b style={{ display: 'block', fontSize: 'var(--fs-base)', fontWeight: 500 }}>{t(ex.text)}</b>
              <small style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-3)' }}>{t(ex.hint)}</small>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
