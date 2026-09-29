import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { money } from '@/lib/format'
import type { DailyReport, StaffLoad } from '@/lib/types'
import { Button, Card, Empty, ErrorNote, Field, Input, Spinner, Stat, Toasts, useToasts } from '@/components/ui'

const today = () => new Date().toISOString().slice(0, 10)

export default function ReportsPage() {
  const toasts = useToasts()
  const [day, setDay] = useState(today())
  const [report, setReport] = useState<DailyReport | null>(null)
  const [staff, setStaff] = useState<StaffLoad[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [closing, setClosing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r, s] = await Promise.all([
        api.get<DailyReport>('/admin/occupancy/report/daily', { business_date: day }),
        api.get<StaffLoad[]>('/admin/occupancy/report/staff', { business_date: day }),
      ])
      setReport(r)
      setStaff(s)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки отчёта')
    } finally {
      setLoading(false)
    }
  }, [day])

  useEffect(() => {
    void load()
  }, [load])

  const closeDay = async () => {
    setClosing(true)
    try {
      await api.post('/admin/occupancy/report/close-day', undefined, { business_date: day })
      toasts.ok('Смена закрыта')
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка закрытия смены')
    } finally {
      setClosing(false)
    }
  }

  if (loading && !report) return <Spinner />
  if (error && !report) return <ErrorNote>{error}</ErrorNote>

  const maxRevenue = report ? Math.max(1, ...report.hourly_load.map((h) => h.revenue)) : 1

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        <div className="toolbar">
          <Field label="Дата">
            <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </Field>
          <Button onClick={load}>Обновить</Button>
          <Button variant="primary" disabled={closing || report?.closed} onClick={closeDay}>
            {report?.closed ? 'Смена закрыта' : 'Закрыть смену'}
          </Button>
        </div>

        {report ? (
          <>
            <div className="stats">
              <Stat label="Выручка" value={money(report.revenue_total)} tone="good" />
              <Stat label="Заказов" value={report.orders_total} />
              <Stat label="Средний чек" value={money(report.avg_check)} />
              <Stat label="Гостей" value={report.guests_total} />
              <Stat label="Столов использовано" value={report.tables_used} />
            </div>

            <div className="cols">
              <Card className="col-main">
                <div className="card-head">
                  <h2>Нагрузка по часам</h2>
                </div>
                {report.hourly_load.length === 0 ? (
                  <Empty>Нет заказов за день</Empty>
                ) : (
                  <div className="chart">
                    {report.hourly_load.map((h) => (
                      <div key={h.hour} className="chart-col" title={`${money(h.revenue)}, заказов: ${h.orders}`}>
                        <div className="chart-bar" style={{ height: `${(h.revenue / maxRevenue) * 100}%` }} />
                        <small>{h.hour}</small>
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card className="col-side">
                <div className="card-head">
                  <h2>Источники заказов</h2>
                </div>
                <ul className="plain-list">
                  {Object.entries(report.by_source).map(([source, revenue]) => (
                    <li key={source}>
                      {source} <span className="muted">{money(revenue)}</span>
                    </li>
                  ))}
                  {Object.keys(report.by_source).length === 0 ? <li className="muted">нет данных</li> : null}
                </ul>
              </Card>
            </div>

            <Card>
              <div className="card-head">
                <h2>Топ блюд</h2>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Блюдо</th>
                    <th>Продано</th>
                    <th>Выручка</th>
                  </tr>
                </thead>
                <tbody>
                  {report.top_dishes.map((d) => (
                    <tr key={d.name}>
                      <td>{d.name}</td>
                      <td>{d.qty}</td>
                      <td>{money(d.revenue)}</td>
                    </tr>
                  ))}
                  {report.top_dishes.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="muted">
                        нет данных
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </Card>

            <Card>
              <div className="card-head">
                <h2>Сотрудники за смену</h2>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Сотрудник</th>
                    <th>Заказов</th>
                    <th>Выручка</th>
                  </tr>
                </thead>
                <tbody>
                  {staff.map((s) => (
                    <tr key={s.user_id}>
                      <td>{s.full_name || s.username}</td>
                      <td>{s.orders}</td>
                      <td>{money(s.revenue)}</td>
                    </tr>
                  ))}
                  {staff.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="muted">
                        нет данных
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </Card>
          </>
        ) : null}
      </div>
    </>
  )
}
