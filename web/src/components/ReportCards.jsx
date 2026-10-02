import { useEffect, useMemo, useState } from 'react'
import { api, money, shortDate, hhmm } from '../lib/api'
import { useI18n, localeOf, t as T } from '../lib/i18n'
import { Num } from './ui'
import { useTip } from './ChartTip'
import { Check, Sparkles, AlertCircle, Calendar, ArrowUpRight, ArrowDownRight, Wallet, Target, Clock } from 'lucide-react'

/**
 * Премиальные интерактивные карточки отчётов в точном стиле эталона Jarvis Bento V7.
 * Заменяют скучные текстовые и монохромные телеграм-карточки на богатый Bento-дизайн:
 * - Градиентные Hero-плитки
 * - Акцентные сине-фиолетовые и изумрудные карточки p1, p2, blk
 * - Прогресс-бары, чипсы, бейджи и аккуратные шрифты Inter Tight / Inter
 */

export function MorningDigestCard({ data, ownerName }) {
  const { t } = useI18n()
  // Настоящие цифры дня из /api/dashboard: раньше карточка рисовала захардкоженные 15 761 / 3 940,
  // поэтому на сайте и в Telegram (там дайджест из базы) были разные числа. Теперь источник один.
  const [live, setLive] = useState(null)
  useEffect(() => {
    if (data) return
    let on = true
    api.dashboard().then((r) => {
      if (!on) return
      setLive({
        balance: r?.finance?.total_balance,
        dailyBudget: r?.finance?.safe?.per_day,
        events: (r?.today || []).map((e) => ({ time: hhmm(e.start), title: e.title })),
        tasks: (r?.tasks || []).map((t) => ({ title: t.title })),
      })
    }).catch(() => {})
    return () => { on = false }
  }, [data])
  const d = data || live || {}
  const now = new Date()
  const dateStr = now.toLocaleDateString(localeOf(), { weekday: 'long', day: 'numeric', month: 'long' })

  const who = String(ownerName || '').trim()
  const balance = d.balance ?? 0
  const dailyBudget = d.dailyBudget ?? null
  const events = d.events || []
  const tasks = d.tasks || []

  return (
    <div className="report-card morning-digest r">
      {/* Шапка дайджеста */}
      <div className="report-header">
        <div className="flex items-center justify-between">
          <span className="report-tag">
            <Sparkles size={13} className="text-[var(--acc)]" />
            {t('rc.morning_digest')}
          </span>
          <span className="mono text-[11px] opacity-50">
            {('0' + now.getHours()).slice(-2)}:{('0' + now.getMinutes()).slice(-2)}
          </span>
        </div>
        <h2 className="report-title">{t('rc.good_morning')}{who ? `, ${who}` : ''}</h2>
        <p className="report-subtitle">{dateStr}</p>
      </div>

      {/* Сетка мини-бенто дайджеста */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
        {/* Баланс - карточка с градиентом */}
        <div className="c hero !p-4 !rounded-2xl">
          <div className="hd !mb-2">
            <h3 className="text-[13px] font-semibold opacity-90">{t('rc.balance')}</h3>
            <small className="opacity-75">{t('rc.free')}</small>
          </div>
          <div className="text-[26px] font-semibold tracking-[-0.03em]"><Num value={balance} /> ₽</div>
        </div>

        {/* Можно тратить в день - p2 изумрудный градиент */}
        <div className="c p2 !p-4 !rounded-2xl">
          <div className="hd !mb-2">
            <h3 className="text-[13px] font-semibold">{t('rc.can_spend')}</h3>
            <small>{t('rc.per_day')}</small>
          </div>
          <div className="text-[26px] font-semibold tracking-[-0.03em] text-[var(--pos)]">
            <Num value={dailyBudget ?? 0} /> ₽
          </div>
        </div>
      </div>

      {/* Блок События сегодня */}
      <div className="report-section mt-4">
        <div className="report-section-title">
          <span>{t('rc.today')}</span>
          <span className="count">{events.length}</span>
        </div>
        {events.length === 0 ? (
          <div className="report-empty-row">{t('rc.no_events')}</div>
        ) : (
          <div className="space-y-1.5 mt-2">
            {events.map((ev, i) => (
              <div key={i} className="report-item-row">
                <span className="mono text-[12px] opacity-75">{ev.time || '15:00'}</span>
                <span className="font-medium text-[13.5px] truncate">{ev.title}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Блок Задачи */}
      <div className="report-section mt-4">
        <div className="report-section-title">
          <span>{t('rc.tasks')}</span>
          <span className="count">{tasks.length}</span>
        </div>
        {tasks.length === 0 ? (
          <div className="report-empty-row">{t('rc.no_tasks')}</div>
        ) : (
          <div className="space-y-1.5 mt-2">
            {tasks.map((t, i) => (
              <div key={i} className="report-item-row">
                <span className="w-2 h-2 rounded-full bg-[var(--acc)] shrink-0"></span>
                <span className="font-medium text-[13.5px] truncate">{t.title}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Подвал карточки с брендингом */}
      <div className="report-footer mt-4 pt-3 flex items-center justify-between text-[11.5px] opacity-40">
        <span>{t('rc.jarvis')}</span>
        <span className="mono">{shortDate(now)}</span>
      </div>
    </div>
  )
}

export function WeekSummaryCard({ data, ownerName }) {
  const { t } = useI18n()
  const catTip = useTip()        // «куда ушло»: категория, сумма и доля — по наведению на строку
  const limTip = useTip()        // «лимиты»: сколько съедено от лимита
  // Реальные цифры недели: раньше карточка рисовала выдуманные 6 589 ₽ / 205 700 ₽ и категории «алкоголь 605 ₽».
  const [live, setLive] = useState(null)
  useEffect(() => {
    if (data) return
    let on = true
    const weekAgo = new Date(Date.now() - 7 * 864e5)
    Promise.all([
      api.finSummary(7).catch(() => null),
      api.finSummary(14).catch(() => null),
      api.debts().catch(() => []),
      api.dashboard().catch(() => null),
      api.tasks(true).catch(() => []),
      api.notes().catch(() => []),
    ]).then(([w7, w14, debts, dash, tasks, notes]) => {
      if (!on) return
      const spent = w7?.spent || 0
      const earned = w7?.earned || 0
      const prev = Math.max(0, (w14?.spent || 0) - spent)
      const cats = Object.entries(w7?.by_category || {}).slice(0, 5).map(([name, amount]) => ({
        name, amount, pct: spent ? Math.round((amount / spent) * 100) : 0, color: '#3b5bff',
      }))
      const budgets = w7?.budgets || []
      setLive({
        spent, earned,
        balance: w7?.total_balance ?? w7?.balance ?? 0,
        debts: (debts || []).reduce((s, x) => s + (x.amount || x.left || 0), 0),
        deltaSpent: prev > 0 ? Math.round(((spent - prev) / prev) * 100) : 0,
        categories: cats,
        limits: budgets.filter((b) => (b.pct || 0) >= 80)
          .map((b) => ({ name: b.name, pct: Math.min(100, Math.round(b.pct)), status: b.pct >= 100 ? 'over' : 'warn', budget: b.budget, spent: b.spent, left: b.left })),
        habits: {
          tasksDone: (tasks || []).filter((t) => t.done && t.done_at && new Date(t.done_at) >= weekAgo).length,
          notesSaved: (notes || []).filter((n) => n.created_at && new Date(n.created_at) >= weekAgo).length,
          streakDays: dash?.streak?.current ?? null,
        },
      })
    }).catch(() => {})
    return () => { on = false }
  }, [data])
  const d = data || live || {}
  const now = new Date()
  const spent = d.spent ?? 0
  const earned = d.earned ?? 0
  const balance = d.balance ?? 0
  const debts = d.debts ?? 0
  const deltaSpent = d.deltaSpent ?? 0

  const categories = d.categories || []
  const habits = d.habits || { tasksDone: 0, notesSaved: 0, streakDays: null }
  const limits = d.limits || []
  const from = new Date(Date.now() - 6 * 864e5)
  // строки, на которые сейчас наведён курсор — для подсказок
  const catLive = catTip.active?.i != null ? categories[catTip.active.i] : null
  const limLive = limTip.active?.i != null ? limits[limTip.active.i] : null

  return (
    <div className="report-card week-summary r">
      {/* Шапка */}
      <div className="report-header">
        <div className="flex items-center justify-between">
          <span className="report-tag">
            <Sparkles size={13} className="text-[#a07bff]" />
            {t('rc.weekly_report')}
          </span>
          <span className="mono text-[11px] opacity-50">
            {('0' + now.getHours()).slice(-2)}:{('0' + now.getMinutes()).slice(-2)}
          </span>
        </div>
        <h2 className="report-title">{t('rc.week_summary')}</h2>
        <p className="report-subtitle">{`${from.getDate()}.${('0' + (from.getMonth() + 1)).slice(-2)} — ${now.getDate()}.${('0' + (now.getMonth() + 1)).slice(-2)}.${now.getFullYear()}`}</p>
      </div>

      {/* Верхние плитки метрик расходов и доходов */}
      <div className="grid grid-cols-2 gap-3 mt-4">
        <div className="c hero !p-4 !rounded-2xl">
          <div className="hd !mb-1.5 text-xs opacity-85">
            <span>{t('rc.spent')}</span>
            <span className="tag !mt-0 !text-[10px] !py-0.5 !px-1.5">{t(deltaSpent < 0 ? 'rc.vs_last' : 'rc.up', { n: Math.abs(deltaSpent) })}</span>
          </div>
          <div className="text-[22px] sm:text-[26px] font-semibold tracking-[-0.03em]"><Num value={spent} /> ₽</div>
        </div>

        <div className="c p2 !p-4 !rounded-2xl">
          <div className="hd !mb-1.5 text-xs opacity-85">
            <span>{t('rc.earned')}</span>
          </div>
          <div className="text-[22px] sm:text-[26px] font-semibold tracking-[-0.03em] text-[var(--pos)]">
            <Num value={earned} /> ₽
          </div>
        </div>
      </div>

      {/* Куда ушло */}
      <div className="report-section mt-5">
        <div className="report-section-title">
          <span>{t('rc.where_it_went')}</span>
          <span className="count">{categories.length}</span>
        </div>
        <div className="relative space-y-3 mt-3" ref={catTip.hostRef}>
          {categories.map((cat, idx) => {
            const name = t.sv(cat.name) || cat.name
            const aria = `${name}: ${money(cat.amount)}, ${t('tip.share', { p: cat.pct })}`
            return (
              <div key={idx} className="category-progress-item chart-pt rounded-lg" {...catTip.bind(idx, aria, 'group')}>
                <div className="flex justify-between items-baseline text-[13.5px]">
                  <span className="font-medium text-[var(--ink)]">{name}</span>
                  <span className="mono font-semibold text-[13.5px]">{money(cat.amount)}</span>
                </div>
                <div className="progress-bar-track mt-1.5">
                  <div
                    className="progress-bar-fill"
                    style={{
                      width: `${cat.pct}%`,
                      background: 'linear-gradient(90deg, #2f57ff, #8a5cff)',
                    }}
                  />
                </div>
              </div>
            )
          })}
        </div>
        {catTip.panel({
          title: catLive ? (t.sv(catLive.name) || catLive.name) : null,
          rows: catLive ? [money(catLive.amount), t('tip.share', { p: catLive.pct })] : [],
        })}
      </div>

      {/* Дела (пилюли статистики активности) */}
      <div className="report-section mt-5">
        <div className="report-section-title">
          <span>{t('rc.things')}</span>
        </div>
        <div className="flex flex-wrap gap-2 mt-2.5">
          <span className="report-pill">
            <Check size={13} className="text-[var(--pos)]" />
            {t('rc.tasks_done', { count: habits.tasksDone })}
          </span>
          <span className="report-pill">
            {t('rc.notes_saved', { count: habits.notesSaved })}
          </span>
          <span className="report-pill active-glow">
            <span className="w-2 h-2 rounded-full bg-white shrink-0"></span>
            {habits.streakDays ? t('rc.streak', { count: habits.streakDays }) : t('rc.no_streak')}
          </span>
        </div>
      </div>

      {/* Лимиты */}
      {limits.length > 0 && (
        <div className="report-section mt-5">
          <div className="report-section-title">
            <span>{t('rc.limits')}</span>
            <span className="count">{limits.length}</span>
          </div>
          <div className="relative space-y-2 mt-2.5" ref={limTip.hostRef}>
            {limits.map((lim, idx) => (
              <div key={idx} className="limit-item chart-pt rounded-lg"
                {...limTip.bind(idx, `${lim.name}: ${t('tip.of_limit', { p: lim.pct })}`, 'group')}>
                <div className="flex justify-between items-center text-[13.5px]">
                  <span className="font-medium">{lim.name}</span>
                  <span className="mono font-semibold text-[var(--warn)]">{lim.pct}%</span>
                </div>
                <div className="progress-bar-track mt-1.5">
                  <div
                    className="progress-bar-fill"
                    style={{
                      width: `${lim.pct}%`,
                      background: 'linear-gradient(90deg, #ff9500, #ff5b7a)',
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
          {limTip.panel({
            title: limLive?.name || null,
            rows: limLive ? [
              t('tip.of_limit', { p: limLive.pct }),
              // суммы приходят с тем же ответом сводки — без новых запросов
              ...(limLive.budget != null
                ? [t('tip.spent_left', { m: money(limLive.spent), limit: money(limLive.budget), left: money(limLive.left) })]
                : []),
            ] : [],
          })}
        </div>
      )}

      {/* Нижний баланс и долги */}
      <div className="grid grid-cols-2 gap-3 mt-5">
        <div className="c blk !p-3.5 !rounded-2xl">
          <small className="block text-[11.5px] opacity-70 mb-1">{t('rc.balance_now')}</small>
          <div className="text-[19px] sm:text-[22px] font-semibold tracking-[-0.03em]"><Num value={balance} /> ₽</div>
        </div>
        <div className="c blk !p-3.5 !rounded-2xl">
          <small className="block text-[11.5px] opacity-70 mb-1">{t('rc.debts')}</small>
          <div className="text-[19px] sm:text-[22px] font-semibold tracking-[-0.03em]"><Num value={debts} /> ₽</div>
        </div>
      </div>

      {/* Подвал карточки */}
      <div className="report-footer mt-4 pt-3 flex items-center justify-between text-[11.5px] opacity-40">
        <span>{t('rc.jarvis')}</span>
        <span className="mono">{shortDate(now)}</span>
      </div>
    </div>
  )
}

/**
 * Виджет «Сводка дня» (Today's Summary Widget):
 * Агрегирует ключевые данные: задачи на сегодня, встречи в календаре,
 * финансовый баланс и дневной лимит в единую информативную Bento-карточку.
 */
export function TodaySummaryWidget({ data, onOpenTasks, onOpenCalendar, onOpenFinance }) {
  const { t } = useI18n()
  const d = data || {}
  const now = new Date()
  const tasks = d.tasks || []
  const events = d.events || []
  // Никаких захардкоженных чисел: если данные ещё не пришли — честный ноль, а не «красивая» выдумка
  const balance = d.balance ?? 0
  const spentToday = d.spentToday ?? 0
  const dailyBudget = d.dailyBudget ?? 0

  const openTasks = tasks.filter((t) => !t.done)
  const doneTasks = tasks.filter((t) => t.done)

  return (
    <div className="summary-widget-wrap h-full flex flex-col justify-between">
      <div className="hd !mb-3">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-blue-500/15 text-blue-500">
            <Sparkles size={15} />
          </span>
          <h2 className="text-[17px] font-semibold tracking-[-0.02em]">{t('rc.day_summary')}</h2>
        </div>
        <small className="mono text-[12px] opacity-60">
          {now.toLocaleDateString(localeOf(), { weekday: 'short', day: 'numeric', month: 'short' }).replace(/\.?\s*г\.$/u, '')}
        </small>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 my-1">
        {/* Финансы */}
        <div
          onClick={onOpenFinance}
          className="rounded-2xl p-3 bg-[var(--sf2)] border border-[var(--line)] hover:border-[var(--acc)] transition cursor-pointer flex flex-col justify-between"
        >
          <div className="flex items-center justify-between text-xs opacity-70 mb-1">
            <span>{t('rc.money')}</span>
            <Wallet size={13} className="text-blue-400" />
          </div>
          <div className="text-[17px] font-semibold mono tracking-tight text-[var(--ink)]">
            <Num value={balance} /> ₽
          </div>
          <div className="text-[11px] opacity-60 mt-1">
            {t('rc.spent_short', { m: money(spentToday) })}
          </div>
        </div>

        {/* Календарь */}
        <div
          onClick={onOpenCalendar}
          className="rounded-2xl p-3 bg-[var(--sf2)] border border-[var(--line)] hover:border-[var(--acc)] transition cursor-pointer flex flex-col justify-between"
        >
          <div className="flex items-center justify-between text-xs opacity-70 mb-1">
            <span>{t('rc.meetings')}</span>
            <Calendar size={13} className="text-purple-400" />
          </div>
          <div className="text-[17px] font-semibold mono tracking-tight text-[var(--ink)]">
            {t('rc.events_n', { count: events.length })}
          </div>
          <div className="text-[11px] opacity-60 mt-1 truncate">
            {events[0] ? `${events[0].title.slice(0, 16)}…` : t('nextup.day_free')}
          </div>
        </div>

        {/* Задачи */}
        <div
          onClick={onOpenTasks}
          className="rounded-2xl p-3 bg-[var(--sf2)] border border-[var(--line)] hover:border-[var(--acc)] transition cursor-pointer flex flex-col justify-between"
        >
          <div className="flex items-center justify-between text-xs opacity-70 mb-1">
            <span>{t('rc.things')}</span>
            <Check size={13} className="text-emerald-400" />
          </div>
          <div className="text-[17px] font-semibold mono tracking-tight text-[var(--ink)]">
            {t('rc.tasks_n', { count: openTasks.length })}
          </div>
          <div className="text-[11px] opacity-60 mt-1">
            {doneTasks.length ? t('rc.closed_n', { count: doneTasks.length }) : t('rc.all_ahead')}
          </div>
        </div>
      </div>

      {/* Быстрая полоска статуса дня */}
      <div className="mt-3 pt-3 border-t border-[var(--line)] flex items-center justify-between text-xs text-[var(--ink2)]">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[var(--pos)] animate-pulseSoft"></span>
          {t('rc.available_today')}: <b className="text-[var(--ink)] num font-semibold">{money(dailyBudget)}</b>
        </span>
        <span className="mono text-[11px] opacity-70">{t('rc.focus_active')}</span>
      </div>
    </div>
  )
}

/**
 * Виджет «Экранное время за ПК» (Bento-стиль)
 */
export function ScreenTimeBentoWidget({ data }) {
  const { t } = useI18n()
  const tip = useTip()
  const d = data
  // Пустой виджет: раньше здесь были захардкоженные демо-данные. Теперь честно и компактно.
  if (!d || !(d.active_min > 0) || !(d.hours || []).some((v) => v > 0)) {
    return (
      <div className="screen-time-widget flex flex-col justify-between h-full">
        <div className="hd !mb-2">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-xl" style={{ background: 'color-mix(in srgb, var(--ai) 14%, transparent)', color: 'var(--ai)' }}>
              <Clock size={15} />
            </span>
            <h2 className="text-[17px] font-semibold tracking-[-0.02em]">{t('screen.title')}</h2>
          </div>
        </div>
        <div className="muted py-6 text-center text-[13px]">{t(d?.pc_alive === false ? 'screen.empty_dead' : 'screen.off_hint')}</div>
      </div>
    )
  }

  const hours = Math.floor(d.active_min / 60)
  const mins = d.active_min % 60
  const slice = (d.hours || []).slice(8, 20)
  const maxH = Math.max(1, ...(d.hours || [1]))
  const sumH = Math.max(1, slice.reduce((s, v) => s + (v || 0), 0))
  const hourLabel = (h, v) => t('rc.hour_min', { h, m: v })
  const curH = tip.active?.i != null ? slice[tip.active.i] : null

  const CAT_COLORS = {
    работа: '#2f57ff',
    общение: '#a07bff',
    браузер: '#5b8bd6',
    медиа: '#ff9500',
    прочее: 'var(--ink3)',
  }

  return (
    <div className="screen-time-widget flex flex-col justify-between h-full">
      <div className="hd !mb-2">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-purple-500/15 text-purple-400">
            <Clock size={15} />
          </span>
          <h2 className="text-[17px] font-semibold tracking-[-0.02em]">{t('screen.title')}</h2>
        </div>
        <small className="mono font-semibold text-[13px] text-[var(--acc)]">
          {hours} {t('unit.hour')} {mins} {t('unit.min')}
        </small>
      </div>

      {/* Почасовой график активности: подсказка по наведению и по тапу (раньше был только title) */}
      <div className="my-2">
        <div className="relative flex items-end h-10 gap-1 px-1" ref={tip.hostRef}>
          {slice.map((val, idx) => {
            const h = idx + 8
            // контейнеру нужна явная высота: иначе height в процентах считается от
            // элемента с auto-высотой и все столбцы схлопывались в 0
            const pct = Math.max(14, (val / maxH) * 100)
            return (
              <div key={h} className="h-full flex-1 flex flex-col items-center justify-end gap-1 group relative">
                <div
                  className="chart-pt w-full rounded-md transition-all"
                  style={{
                    height: `${pct}%`,
                    background: val > 20 ? 'linear-gradient(180deg, #8a5cff, #2f57ff)'
                      : val > 0 ? 'color-mix(in srgb, #8a5cff 55%, transparent)'
                      : 'var(--line)',
                  }}
                  {...tip.bind(idx, `${hourLabel(h, val)}, ${t('tip.share_active', { p: Math.round((val / sumH) * 100) })}`)}
                />
              </div>
            )
          })}
        </div>
        <div className="flex justify-between text-[10px] mono text-[var(--ink3)] mt-1 px-1">
          <span>08:00</span>
          <span>14:00</span>
          <span>20:00</span>
        </div>
      </div>
      {tip.panel({
        title: curH != null ? hourLabel(tip.active.i + 8, curH) : null,
        rows: curH != null ? [t('tip.share_active', { p: Math.round((curH / sumH) * 100) })] : [],
      })}

      {/* Топ приложений */}
      <div className="space-y-1.5 mt-2">
        {(d.apps || []).slice(0, 3).map(([name, m, cat], i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 truncate">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: CAT_COLORS[cat] || '#8a5cff' }}></span>
              <span className="truncate font-medium">{name}</span>
            </span>
            <span className="mono opacity-70 shrink-0">{m} мин</span>
          </div>
        ))}
      </div>
    </div>
  )
}

