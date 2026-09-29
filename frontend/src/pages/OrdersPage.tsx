import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { useLiveChannel } from '@/lib/useLive'
import { minutesSince, money, ORDER_STATUS_LABEL, time } from '@/lib/format'
import type { KitchenBoard, Order, OrderStatus, Table } from '@/lib/types'
import { Button, Card, Empty, ErrorNote, Modal, Pill, Spinner, Toasts, useToasts } from '@/components/ui'

const FLOW: OrderStatus[] = ['new', 'in_progress', 'ready', 'served', 'closed']

const FILTERS: { key: string; label: string; value: string }[] = [
  { key: 'kitchen', label: 'Кухня', value: 'kitchen' },
  { key: 'open', label: 'Открытые', value: 'open' },
  { key: 'all', label: 'Все', value: 'all' },
]

export default function OrdersPage() {
  const toasts = useToasts()
  const [params, setParams] = useSearchParams()
  const [orders, setOrders] = useState<Order[]>([])
  const [tables, setTables] = useState<Table[]>([])
  const [maxWait, setMaxWait] = useState(0)
  const [filter, setFilter] = useState('kitchen')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<Order | null>(null)

  const load = useCallback(async () => {
    try {
      if (filter === 'kitchen') {
        const board = await api.get<KitchenBoard>('/admin/orders/kitchen')
        setOrders(board.orders)
        setMaxWait(board.max_wait_minutes)
      } else {
        const query = filter === 'open' ? { only_open: true, limit: 100 } : { limit: 100 }
        setOrders(await api.get<Order[]>('/admin/orders', query))
      }
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки заказов')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void api.get<Table[]>('/admin/hall/tables').then(setTables).catch(() => setTables([]))
  }, [])

  useLiveChannel('kitchen', (event) => {
    if (event === 'order.updated' || event === 'order.created') void load()
  })

  const setStatus = async (order: Order, status: OrderStatus) => {
    try {
      const updated = await api.post<Order>(`/admin/orders/${order.id}/status`, { status, note: '' })
      setOrders((prev) =>
        filter === 'kitchen' && (status === 'closed' || status === 'cancelled')
          ? prev.filter((o) => o.id !== order.id)
          : prev.map((o) => (o.id === order.id ? updated : o)),
      )
      if (detail?.id === order.id) setDetail(updated)
      toasts.ok(`${order.order_number} → ${ORDER_STATUS_LABEL[status]}`)
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка смены статуса')
    }
  }

  const nextStatus = (order: Order): OrderStatus | null => {
    const index = FLOW.indexOf(order.status)
    if (index < 0 || index === FLOW.length - 1) return null
    return FLOW[index + 1]
  }

  const cancel = async (order: Order) => {
    try {
      await api.post(`/admin/orders/${order.id}/cancel`)
      setOrders((prev) => prev.filter((o) => o.id !== order.id))
      setDetail(null)
      toasts.ok(`${order.order_number} отменён`)
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка отмены')
    }
  }

  const addItem = async (order: Order, dishId: string, qty: number) => {
    try {
      const updated = await api.post<Order>(`/admin/orders/${order.id}/items`, { dish_id: dishId, quantity: qty })
      setOrders((prev) => prev.map((o) => (o.id === order.id ? updated : o)))
      setDetail(updated)
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка добавления')
    }
  }

  const removeItem = async (order: Order, itemId: string) => {
    try {
      const updated = await api.del<Order>(`/admin/orders/${order.id}/items/${itemId}`)
      setOrders((prev) => prev.map((o) => (o.id === order.id ? updated : o)))
      setDetail(updated)
      toasts.ok('Позиция удалена')
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка удаления')
    }
  }

  const focus = params.get('focus')
  useEffect(() => {
    if (!focus) return
    const found = orders.find((o) => o.id === focus)
    if (found) setDetail(found)
  }, [focus, orders])

  const tableFilter = params.get('table')
  const shown = useMemo(
    () => (tableFilter ? orders.filter((o) => o.table_id === tableFilter) : orders),
    [orders, tableFilter],
  )

  if (loading) return <Spinner />
  if (error && !orders.length) return <ErrorNote>{error}</ErrorNote>

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        <div className="toolbar">
          {FILTERS.map((f) => (
            <Button key={f.key} variant={filter === f.key ? 'primary' : 'default'} onClick={() => setFilter(f.value)}>
              {f.label}
            </Button>
          ))}
          {maxWait > 0 ? <Pill tone="bad">самый долгий: {maxWait} мин</Pill> : null}
          {tableFilter ? (
            <Button
              onClick={() => {
                params.delete('table')
                setParams(params)
              }}
            >
              сбросить фильтр стола
            </Button>
          ) : null}
          <Button onClick={load}>Обновить</Button>
        </div>

        {shown.length === 0 ? (
          <Empty>Нет заказов</Empty>
        ) : (
          <div className="kitchen">
            {shown.map((order) => {
              const wait = minutesSince(order.created_at)
              const next = nextStatus(order)
              const late = wait > maxWait && maxWait > 0
              return (
                <Card key={order.id} className={late ? 'order-late' : ''}>
                  <div className="card-head">
                    <div>
                      <strong>{order.order_number}</strong>
                      <div className="muted">
                        {order.table_name ?? 'без стола'} · {order.source} · {time(order.created_at)}
                      </div>
                    </div>
                    <div className="row-actions">
                      <Pill tone={late ? 'bad' : wait > 10 ? 'warn' : 'default'}>{wait} мин</Pill>
                      <Pill tone="info">{ORDER_STATUS_LABEL[order.status]}</Pill>
                    </div>
                  </div>
                  <ul className="kitchen-items">
                    {order.items.map((item) => (
                      <li key={item.id}>
                        <span className="qty-badge">{item.quantity}</span>
                        <span>
                          <strong>{item.dish_name}</strong>
                          {item.modifiers.length > 0 ? (
                            <small className="muted"> {item.modifiers.map((m) => m.name).join(', ')}</small>
                          ) : null}
                          {item.comment ? <small className="comment"> «{item.comment}»</small> : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {order.guest_comment ? <div className="comment">Заказ: {order.guest_comment}</div> : null}
                  <div className="row-end">
                    <span className="muted">{money(order.total_amount)}</span>
                    <Button small onClick={() => setDetail(order)}>
                      Подробно
                    </Button>
                    {next ? (
                      <Button small variant="primary" onClick={() => setStatus(order, next)}>
                        → {ORDER_STATUS_LABEL[next]}
                      </Button>
                    ) : null}
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </div>

      <Modal open={detail !== null} title={detail?.order_number ?? ''} onClose={() => setDetail(null)} wide>
        {detail ? (
          <OrderDetail
            order={detail}
            tables={tables}
            onStatus={(status) => setStatus(detail, status)}
            onCancel={() => cancel(detail)}
            onAddItem={(dishId, qty) => addItem(detail, dishId, qty)}
            onRemoveItem={(itemId) => removeItem(detail, itemId)}
          />
        ) : null}
      </Modal>
    </>
  )
}

function OrderDetail({
  order,
  tables,
  onStatus,
  onCancel,
  onAddItem,
  onRemoveItem,
}: {
  order: Order
  tables: Table[]
  onStatus: (status: OrderStatus) => void
  onCancel: () => void
  onAddItem: (dishId: string, qty: number) => void
  onRemoveItem: (itemId: string) => void
}) {
  const [dishes, setDishes] = useState<{ id: string; name: string; price: number }[]>([])
  const [dishId, setDishId] = useState('')
  const [qty, setQty] = useState(1)

  useEffect(() => {
    void api
      .get<{ id: string; name: string; price: number }[]>('/admin/menu/dishes', { include_inactive: false })
      .then((list) => {
        setDishes(list)
        setDishId(list[0]?.id ?? '')
      })
      .catch(() => setDishes([]))
  }, [])

  return (
    <div className="stack">
      <div className="row-wrap">
        <Pill tone="info">{ORDER_STATUS_LABEL[order.status]}</Pill>
        <span className="muted">
          {order.table_name ?? 'без стола'} · гостей: {order.guests_count} · {order.source}
        </span>
      </div>
      {order.client_name ? <div>Клиент: {order.client_name}</div> : null}
      {order.guest_comment ? <div className="comment">Комментарий: {order.guest_comment}</div> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Блюдо</th>
            <th>Цена</th>
            <th>Кол-во</th>
            <th>Сумма</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {order.items.map((item) => (
            <tr key={item.id}>
              <td>
                {item.dish_name}
                {item.modifiers.length > 0 ? (
                  <small className="muted"> · {item.modifiers.map((m) => m.name).join(', ')}</small>
                ) : null}
                {item.comment ? <small className="comment"> «{item.comment}»</small> : null}
              </td>
              <td>{money(item.price)}</td>
              <td>{item.quantity}</td>
              <td>{money(item.line_total)}</td>
              <td>
                <Button small variant="danger" onClick={() => onRemoveItem(item.id)}>
                  ×
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3}>Итого</td>
            <td>
              <strong>{money(order.total_amount)}</strong>
            </td>
            <td />
          </tr>
        </tfoot>
      </table>

      <div className="row-wrap add-item">
        <select className="input" value={dishId} onChange={(e) => setDishId(e.target.value)}>
          {dishes.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} · {money(d.price)}
            </option>
          ))}
        </select>
        <input
          className="input qty-input"
          type="number"
          min={1}
          max={99}
          value={qty}
          onChange={(e) => setQty(Math.max(1, Number(e.target.value)))}
        />
        <Button disabled={!dishId} onClick={() => onAddItem(dishId, qty)}>
          Добавить позицию
        </Button>
      </div>

      <div className="row-wrap">
        {FLOW.filter((s) => s !== order.status).map((s) => (
          <Button key={s} small onClick={() => onStatus(s)}>
            {ORDER_STATUS_LABEL[s]}
          </Button>
        ))}
        {order.status !== 'closed' && order.status !== 'cancelled' ? (
          <Button small variant="danger" onClick={onCancel}>
            Отменить заказ
          </Button>
        ) : null}
      </div>
      <div className="muted">
        Заказ создан {dateTimeRu(order.created_at)}
        {order.table_id ? ` · стол: ${tables.find((t) => t.id === order.table_id)?.name ?? order.table_id}` : ''}
      </div>
    </div>
  )
}

function dateTimeRu(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
