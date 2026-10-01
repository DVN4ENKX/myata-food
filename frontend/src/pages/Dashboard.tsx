import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { money, minutesSince, ORDER_STATUS_LABEL, TABLE_STATUS_LABEL, time } from '@/lib/format'
import type { OccupancyBoard, Order, Table } from '@/lib/types'
import { Card, Empty, ErrorNote, Pill, Spinner, Stat, Toasts, useToasts, Button } from '@/components/ui'

function statusTone(status: Table['status']): 'good' | 'warn' | 'bad' | 'default' {
  if (status === 'seated') return 'good'
  if (status === 'reserved') return 'warn'
  if (status === 'cleaning') return 'bad'
  return 'default'
}

export default function Dashboard() {
  const toasts = useToasts()
  const [board, setBoard] = useState<OccupancyBoard | null>(null)
  const [orders, setOrders] = useState<Order[]>([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [b, o] = await Promise.all([
        api.get<OccupancyBoard>('/admin/occupancy/board'),
        api.get<Order[]>('/admin/orders', { only_open: true, limit: 30 }),
      ])
      setBoard(b)
      setOrders(o)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить данные')
    }
  }, [])

  useEffect(() => {
    void load()
    const onChange = () => void load()
    window.addEventListener('myata:occupancy', onChange)
    const timer = window.setInterval(load, 30000)
    return () => {
      window.removeEventListener('myata:occupancy', onChange)
      window.clearInterval(timer)
    }
  }, [load])

  const seat = async (table: Table) => {
    try {
      await api.post(`/admin/occupancy/tables/${table.id}/seat`, { guests_count: table.seats, guest_name: '' })
      toasts.ok(`${table.name}: гости посажены`)
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка посадки')
    }
  }

  // a table needs closing while a session is still open or orders are still unpaid
  const needsClose = (table: Table) => table.current_session !== null || table.open_orders > 0

  const close = async (table: Table) => {
    try {
      await api.post(`/admin/occupancy/tables/${table.id}/close`, { clear_tables: true })
      toasts.ok(`${table.name} закрыт`)
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка закрытия')
    }
  }

  if (!board && !error) return <Spinner />
  if (error && !board) return <ErrorNote>{error}</ErrorNote>

  const s = board!.summary

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        <div className="stats">
          <Stat label="Занято" value={`${s.tables_busy}/${s.tables_total}`} hint={`${s.occupancy_percent}% загрузки`} tone={s.tables_busy > 0 ? 'good' : 'default'} />
          <Stat label="Гостей сейчас" value={s.guests_now} hint={`мест: ${s.seats_total}`} />
          <Stat label="Свободно" value={s.tables_free} hint={`уборка: ${s.tables_cleaning}`} />
          <Stat label="Брони сегодня" value={board!.reservations_today} tone={board!.reservations_today > 0 ? 'warn' : 'default'} />
          <Stat label="Выручка" value={money(s.revenue_today)} hint={`заказов: ${s.orders_today}`} tone="good" />
        </div>

        <div className="cols">
          <Card className="col-main">
            <div className="card-head">
              <h2>Столы</h2>
              <Link className="link" to="/hall">
                Схема зала →
              </Link>
            </div>
            {board!.tables.length === 0 ? (
              <Empty>Столов пока нет</Empty>
            ) : (
              <div className="table-chips">
                {board!.tables.map((table) => (
                  <div key={table.id} className={`chip chip-${table.status}`}>
                    <div className="chip-head">
                      <strong>{table.name}</strong>
                      <Pill tone={statusTone(table.status)}>{TABLE_STATUS_LABEL[table.status]}</Pill>
                    </div>
                    <div className="chip-meta">
                      {table.current_session ? (
                        <span>
                          {table.current_session.guests_count} гост. · {minutesSince(table.current_session.started_at)} мин
                        </span>
                      ) : (
                        <span className="muted">{table.seats} мест</span>
                      )}
                    </div>
                    {table.open_orders > 0 ? (
                      <div className="chip-meta">
                        заказов: {table.open_orders} · {money(table.order_total)}
                      </div>
                    ) : null}
                    {table.next_reservation_at ? (
                      <div className="chip-meta muted">бронь {time(table.next_reservation_at)}</div>
                    ) : null}
                    {table.status === 'free' ? (
                      <Button small onClick={() => seat(table)}>
                        Посадить
                      </Button>
                    ) : null}
                    {table.status === 'seated' ? (
                      <Link className="btn btn-sm" to={`/orders?table=${table.id}`}>
                        Заказы
                      </Link>
                    ) : null}
                    {needsClose(table) ? (
                      <Button small variant="danger" onClick={() => close(table)}>
                        Закрыть
                      </Button>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="col-side">
            <div className="card-head">
              <h2>Активные заказы</h2>
              <Link className="link" to="/orders">
                все →
              </Link>
            </div>
            {orders.length === 0 ? (
              <Empty>Нет открытых заказов</Empty>
            ) : (
              <ul className="order-list">
                {orders.map((order) => (
                  <li key={order.id}>
                    <div className="order-list-head">
                      <Link to={`/orders?focus=${order.id}`}>{order.order_number}</Link>
                      <Pill tone={order.status === 'ready' ? 'good' : order.status === 'new' ? 'warn' : 'info'}>
                        {ORDER_STATUS_LABEL[order.status]}
                      </Pill>
                    </div>
                    <div className="muted">
                      {order.table_name ?? 'без стола'} · {order.source} · {time(order.created_at)} ·{' '}
                      {money(order.total_amount)}
                    </div>
                    <div className="order-items">
                      {order.items.map((item) => (
                        <span key={item.id}>
                          {item.quantity}× {item.dish_name}
                        </span>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}
