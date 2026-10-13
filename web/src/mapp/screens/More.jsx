/* mapp/screens/More.jsx — мобильный раздел «ещё» (порт референса screens/More.tsx).
 *
 * Плитки — живые счётчики из /api/dashboard (заметки/заказы/люди), мозг/заказы/
 * люди без мобильной вёрстки уходят десктопным маршрутом через go(), настройки
 * и чат — внутренние экраны MApp. Hero зовёт спросить марвина.
 */
import { useEffect, useState } from 'react'
import { ArrowUpRight, Brain, Clapperboard, Settings, Sparkles, Users } from 'lucide-react'
import { api } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { IconTile, MError, MSkeleton, ScreenTitle } from '../ui.jsx'

/* Экран-меню: своих списков тут нет, состояния касаются только счётчиков на
   плитках (они приезжают из /api/dashboard). Пока грузятся — скелетон, при сбое —
   честная плашка с повтором, а не тихие нули. */
export default function MMore({ go }) {
  const { t } = useI18n()
  const [dash, setDash] = useState(null)
  const [err, setErr] = useState(false)

  const load = () => {
    setErr(false)
    api.dashboard().then((d) => setDash(d)).catch(() => setErr(true))
  }
  useEffect(() => { load() }, [])

  const memCount = (dash?.memory || []).length
  const ordersOpen = (dash?.orders?.open || []).length
  const tiles = [
    { id: 'brain', label: t('m.brain'), value: dash ? t('m.notes_n', { count: memCount }) : null, icon: Brain, color: '#ff8da1' },
    { id: 'orders', label: t('m.orders'), value: dash ? t('m.in_work', { count: ordersOpen }) : null, icon: Clapperboard, color: '#ffc24d' },
    { id: 'people', label: t('m.people'), value: dash ? t('m.entries_n', { count: (dash?.birthdays || []).length }) : null, icon: Users, color: '#3ddc97' },
    { id: 'settings', label: t('nav.settings'), value: t('m.more_set_sub'), icon: Settings, color: '#a9b3e0' },
  ]

  return (
    <div data-testid="m-more">
      <ScreenTitle title={t('common.more')} subtitle={t('m.more_sub')} />

      <div className="mt-5 px-4">
        <div className="m-hero holo-border relative overflow-hidden rounded-[28px] p-5">
          <div className="pointer-events-none absolute -right-10 -top-16 h-48 w-48 rounded-full bg-white/25 blur-2xl" />
          <div className="relative flex items-center gap-2 text-[12.5px] font-medium text-white/85">
            <Sparkles size={14} />
            {t('m.marvin_brief')}
          </div>
          <div className="relative mt-2 text-[23px] font-bold leading-[1.15] tracking-[-0.02em]">
            {t('m.more_ask')}
          </div>
          <div className="relative mt-1 text-[13px] text-white/75">{t('m.more_ask_sub')}</div>
          <button
            type="button"
            onClick={() => go('chat')}
            data-testid="m-more-ask"
            className="relative mt-4 inline-flex h-10 items-center gap-1.5 rounded-full bg-white px-4 text-[14px] font-semibold text-[#2b3a9a] transition active:scale-95"
          >
            {t('m.open')}
            <ArrowUpRight size={16} />
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 px-4">
        {tiles.map((x) => (
          <button
            type="button"
            key={x.id}
            onClick={() => go(x.id)}
            data-testid={`m-more-${x.id}`}
            className="m-card flex h-[164px] flex-col rounded-[26px] p-4 text-left transition active:scale-[0.97]"
          >
            <IconTile icon={x.icon} color={x.color} size={44} radius={14} />
            <div className="mt-auto text-[18px] font-semibold">{x.label}</div>
            {x.value
              ? <div className="mt-0.5 text-[12.5px] leading-snug text-white/55">{x.value}</div>
              : <MSkeleton h={12} w="62%" radius="var(--r-sm)" className="mt-2" />}
          </button>
        ))}
      </div>

      {err && (
        <MError
          className="mt-4 px-4"
          compact
          onRetry={load}
          title={t('m.load_err')}
          sub={t('m.load_err_sub')}
        />
      )}
    </div>
  )
}
