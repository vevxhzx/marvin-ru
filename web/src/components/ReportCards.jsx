import { useMemo } from 'react'
import { money, plural, shortDate } from '../lib/api'
import { Num } from './ui'
import { Check, Sparkles, AlertCircle, Calendar, ArrowUpRight, ArrowDownRight, Wallet, Target, Clock } from 'lucide-react'

/**
 * Премиальные интерактивные карточки отчётов в точном стиле эталона Jarvis Bento V7.
 * Заменяют скучные текстовые и монохромные телеграм-карточки на богатый Bento-дизайн:
 * - Градиентные Hero-плитки
 * - Акцентные сине-фиолетовые и изумрудные карточки p1, p2, blk
 * - Прогресс-бары, чипсы, бейджи и аккуратные шрифты Inter Tight / Inter
 */

export function MorningDigestCard({ data, ownerName = 'вовчик' }) {
  const d = data || {}
  const now = new Date()
  const WD_RU = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
  const MONTHS_RU = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
  const dateStr = `${WD_RU[now.getDay()]}, ${now.getDate()} ${MONTHS_RU[now.getMonth()]}`

  const balance = d.balance ?? 15761
  const dailyBudget = d.dailyBudget ?? 3940
  const events = d.events || []
  const tasks = d.tasks || []

  return (
    <div className="report-card morning-digest r">
      {/* Шапка дайджеста */}
      <div className="report-header">
        <div className="flex items-center justify-between">
          <span className="report-tag">
            <Sparkles size={13} className="text-[var(--acc)]" />
            утренний дайджест
          </span>
          <span className="mono text-[11px] opacity-50">
            {('0' + now.getHours()).slice(-2)}:{('0' + now.getMinutes()).slice(-2)}
          </span>
        </div>
        <h2 className="report-title">доброе утро, {ownerName}</h2>
        <p className="report-subtitle">{dateStr}</p>
      </div>

      {/* Сетка мини-бенто дайджеста */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
        {/* Баланс - карточка с градиентом */}
        <div className="c hero !p-4 !rounded-2xl">
          <div className="hd !mb-2">
            <h3 className="text-[13px] font-semibold opacity-90">баланс</h3>
            <small className="opacity-75">свободно</small>
          </div>
          <div className="text-[26px] font-semibold tracking-[-0.03em]"><Num value={balance} /> ₽</div>
        </div>

        {/* Можно тратить в день - p2 изумрудный градиент */}
        <div className="c p2 !p-4 !rounded-2xl">
          <div className="hd !mb-2">
            <h3 className="text-[13px] font-semibold">можно тратить</h3>
            <small>в день</small>
          </div>
          <div className="text-[26px] font-semibold tracking-[-0.03em] text-[var(--pos)]">
            <Num value={dailyBudget} /> ₽
          </div>
        </div>
      </div>

      {/* Блок События сегодня */}
      <div className="report-section mt-4">
        <div className="report-section-title">
          <span>СЕГОДНЯ</span>
          <span className="count">{events.length}</span>
        </div>
        {events.length === 0 ? (
          <div className="report-empty-row">встреч нет — день ваш</div>
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
          <span>ЗАДАЧИ</span>
          <span className="count">{tasks.length}</span>
        </div>
        {tasks.length === 0 ? (
          <div className="report-empty-row">задач нет. подозрительно.</div>
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
        <span>джарвис</span>
        <span className="mono">{shortDate(now)}</span>
      </div>
    </div>
  )
}

export function WeekSummaryCard({ data, ownerName = 'вовчик' }) {
  const d = data || {}
  const now = new Date()
  const spent = d.spent ?? 6589
  const earned = d.earned ?? 0
  const balance = d.balance ?? 15761
  const debts = d.debts ?? 205700
  const deltaSpent = d.deltaSpent ?? -5

  const categories = d.categories || [
    { name: 'Еда', amount: 3047, pct: 46, color: '#3b5bff' },
    { name: 'Другое', amount: 2638, pct: 40, color: '#3b5bff' },
    { name: 'алкоголь', amount: 605, pct: 9, color: '#3b5bff' },
    { name: 'Подписки', amount: 299, pct: 5, color: '#3b5bff' },
  ]

  const habits = d.habits || {
    tasksDone: 2,
    notesSaved: 1,
    streak: '8 из 7 дней с записями',
  }

  const limits = d.limits || [
    { name: 'Еда', pct: 90, status: 'warn' },
  ]

  return (
    <div className="report-card week-summary r">
      {/* Шапка */}
      <div className="report-header">
        <div className="flex items-center justify-between">
          <span className="report-tag">
            <Sparkles size={13} className="text-[#a07bff]" />
            недельный отчёт
          </span>
          <span className="mono text-[11px] opacity-50">
            {('0' + now.getHours()).slice(-2)}:{('0' + now.getMinutes()).slice(-2)}
          </span>
        </div>
        <h2 className="report-title">итоги недели</h2>
        <p className="report-subtitle">20.09 — 27.09.2026</p>
      </div>

      {/* Верхние плитки метрик расходов и доходов */}
      <div className="grid grid-cols-2 gap-3 mt-4">
        <div className="c hero !p-4 !rounded-2xl">
          <div className="hd !mb-1.5 text-xs opacity-85">
            <span>потрачено</span>
            <span className="tag !mt-0 !text-[10px] !py-0.5 !px-1.5">{deltaSpent < 0 ? `${deltaSpent}% к прошлому` : `+${deltaSpent}%`}</span>
          </div>
          <div className="text-[22px] sm:text-[26px] font-semibold tracking-[-0.03em]"><Num value={spent} /> ₽</div>
        </div>

        <div className="c p2 !p-4 !rounded-2xl">
          <div className="hd !mb-1.5 text-xs opacity-85">
            <span>заработано</span>
          </div>
          <div className="text-[22px] sm:text-[26px] font-semibold tracking-[-0.03em] text-[var(--pos)]">
            <Num value={earned} /> ₽
          </div>
        </div>
      </div>

      {/* Куда ушло */}
      <div className="report-section mt-5">
        <div className="report-section-title">
          <span>КУДА УШЛО</span>
          <span className="count">{categories.length}</span>
        </div>
        <div className="space-y-3 mt-3">
          {categories.map((cat, idx) => (
            <div key={idx} className="category-progress-item">
              <div className="flex justify-between items-baseline text-[13.5px]">
                <span className="font-medium text-[var(--ink)]">{cat.name}</span>
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
          ))}
        </div>
      </div>

      {/* Дела (пилюли статистики активности) */}
      <div className="report-section mt-5">
        <div className="report-section-title">
          <span>ДЕЛА</span>
        </div>
        <div className="flex flex-wrap gap-2 mt-2.5">
          <span className="report-pill">
            <Check size={13} className="text-[var(--pos)]" />
            {habits.tasksDone} {plural(habits.tasksDone, 'задача закрыта', 'задачи закрыто', 'задач закрыто')}
          </span>
          <span className="report-pill">
            {habits.notesSaved} {plural(habits.notesSaved, 'заметка', 'заметки', 'заметок')}
          </span>
          <span className="report-pill active-glow">
            <span className="w-2 h-2 rounded-full bg-white shrink-0"></span>
            {habits.streak}
          </span>
        </div>
      </div>

      {/* Лимиты */}
      {limits.length > 0 && (
        <div className="report-section mt-5">
          <div className="report-section-title">
            <span>ЛИМИТЫ</span>
            <span className="count">{limits.length}</span>
          </div>
          <div className="space-y-2 mt-2.5">
            {limits.map((lim, idx) => (
              <div key={idx} className="limit-item">
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
        </div>
      )}

      {/* Нижний баланс и долги */}
      <div className="grid grid-cols-2 gap-3 mt-5">
        <div className="c blk !p-3.5 !rounded-2xl">
          <small className="block text-[11.5px] opacity-70 mb-1">баланс сейчас</small>
          <div className="text-[19px] sm:text-[22px] font-semibold tracking-[-0.03em]"><Num value={balance} /> ₽</div>
        </div>
        <div className="c blk !p-3.5 !rounded-2xl">
          <small className="block text-[11.5px] opacity-70 mb-1">долги</small>
          <div className="text-[19px] sm:text-[22px] font-semibold tracking-[-0.03em]"><Num value={debts} /> ₽</div>
        </div>
      </div>

      {/* Подвал карточки */}
      <div className="report-footer mt-4 pt-3 flex items-center justify-between text-[11.5px] opacity-40">
        <span>джарвис</span>
        <span className="mono">27.09.2026 · 19:02</span>
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
  const d = data || {}
  const now = new Date()
  const tasks = d.tasks || []
  const events = d.events || []
  const balance = d.balance ?? 15761
  const spentToday = d.spentToday ?? 450
  const dailyBudget = d.dailyBudget ?? 3940

  const openTasks = tasks.filter((t) => !t.done)
  const doneTasks = tasks.filter((t) => t.done)

  return (
    <div className="summary-widget-wrap h-full flex flex-col justify-between">
      <div className="hd !mb-3">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-blue-500/15 text-blue-500">
            <Sparkles size={15} />
          </span>
          <h2 className="text-[17px] font-semibold tracking-[-0.02em]">сводка дня</h2>
        </div>
        <small className="mono text-[12px] opacity-60">
          {now.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' })}
        </small>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 my-1">
        {/* Финансы */}
        <div
          onClick={onOpenFinance}
          className="rounded-2xl p-3 bg-[var(--sf2)] border border-[var(--line)] hover:border-[var(--acc)] transition cursor-pointer flex flex-col justify-between"
        >
          <div className="flex items-center justify-between text-xs opacity-70 mb-1">
            <span>деньги</span>
            <Wallet size={13} className="text-blue-400" />
          </div>
          <div className="text-[17px] font-semibold mono tracking-tight text-[var(--ink)]">
            <Num value={balance} /> ₽
          </div>
          <div className="text-[11px] opacity-60 mt-1">
            траты: −{money(spentToday)}
          </div>
        </div>

        {/* Календарь */}
        <div
          onClick={onOpenCalendar}
          className="rounded-2xl p-3 bg-[var(--sf2)] border border-[var(--line)] hover:border-[var(--acc)] transition cursor-pointer flex flex-col justify-between"
        >
          <div className="flex items-center justify-between text-xs opacity-70 mb-1">
            <span>встречи</span>
            <Calendar size={13} className="text-purple-400" />
          </div>
          <div className="text-[17px] font-semibold mono tracking-tight text-[var(--ink)]">
            {events.length} {plural(events.length, 'событие', 'события', 'событий')}
          </div>
          <div className="text-[11px] opacity-60 mt-1 truncate">
            {events[0] ? `${events[0].title.slice(0, 16)}…` : 'день свободен'}
          </div>
        </div>

        {/* Задачи */}
        <div
          onClick={onOpenTasks}
          className="rounded-2xl p-3 bg-[var(--sf2)] border border-[var(--line)] hover:border-[var(--acc)] transition cursor-pointer flex flex-col justify-between"
        >
          <div className="flex items-center justify-between text-xs opacity-70 mb-1">
            <span>дела</span>
            <Check size={13} className="text-emerald-400" />
          </div>
          <div className="text-[17px] font-semibold mono tracking-tight text-[var(--ink)]">
            {openTasks.length} {plural(openTasks.length, 'задача', 'задачи', 'задач')}
          </div>
          <div className="text-[11px] opacity-60 mt-1">
            {doneTasks.length ? `${doneTasks.length} закрыто` : 'всё впереди'}
          </div>
        </div>
      </div>

      {/* Быстрая полоска статуса дня */}
      <div className="mt-3 pt-3 border-t border-[var(--line)] flex items-center justify-between text-xs text-[var(--ink2)]">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[var(--pos)] animate-pulseSoft"></span>
          доступно сегодня: <b className="text-[var(--ink)] num font-semibold">{money(dailyBudget)}</b>
        </span>
        <span className="mono text-[11px] opacity-70">фокус дня: активен</span>
      </div>
    </div>
  )
}

/**
 * Виджет «Экранное время за ПК» (Bento-стиль)
 */
export function ScreenTimeBentoWidget({ data }) {
  const d = data || {
    recording: true,
    pc_alive: true,
    active_min: 342,
    hours: [0, 0, 0, 0, 0, 0, 0, 0, 15, 45, 55, 60, 40, 50, 58, 42, 30, 0, 0, 0, 0, 0, 0, 0],
    apps: [
      ['Premiere Pro', 200, 'работа', 'Монтаж узбекам2'],
      ['After Effects', 72, 'работа', 'Анимация титров'],
      ['Telegram', 35, 'общение', 'Чат с клиентом'],
      ['Chrome', 25, 'браузер', 'YouTube'],
    ]
  }

  const hours = Math.floor(d.active_min / 60)
  const mins = d.active_min % 60
  const maxH = Math.max(1, ...(d.hours || [1]))

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
          <h2 className="text-[17px] font-semibold tracking-[-0.02em]">время за пк</h2>
        </div>
        <small className="mono font-semibold text-[13px] text-[var(--acc)]">
          {hours} ч {mins} мин
        </small>
      </div>

      {/* Почасовой график активности */}
      <div className="my-2">
        <div className="flex items-end h-10 gap-1 px-1">
          {(d.hours || []).slice(8, 20).map((val, idx) => {
            const h = idx + 8
            // контейнеру нужна явная высота: иначе height в процентах считается от
            // элемента с auto-высотой и все столбцы схлопывались в 0
            const pct = Math.max(14, (val / maxH) * 100)
            return (
              <div key={h} className="h-full flex-1 flex flex-col items-center justify-end gap-1 group relative">
                <div
                  className="w-full rounded-md transition-all"
                  style={{
                    height: `${pct}%`,
                    background: val > 20 ? 'linear-gradient(180deg, #8a5cff, #2f57ff)'
                      : val > 0 ? 'color-mix(in srgb, #8a5cff 55%, transparent)'
                      : 'var(--line)',
                  }}
                  title={`${h}:00 — ${val} мин`}
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

