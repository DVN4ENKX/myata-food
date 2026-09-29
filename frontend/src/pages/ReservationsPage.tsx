import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api'
import { dateTime, RESERVATION_STATUS_LABEL, time } from '@/lib/format'
import type { Reservation, ReservationStatus, Table } from '@/lib/types'
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Input,
  Modal,
  Pill,
  Select,
  Spinner,
  Textarea,
  Toasts,
  useToasts,
} from '@/components/ui'

const TONE: Record<string, 'good' | 'warn' | 'bad' | 'default' | 'info'> = {
  planned: 'info',
  arrived: 'good',
  cancelled: 'bad',
  no_show: 'warn',
}

function localDateTime(offsetMinutes = 60): string {
  const d = new Date(Date.now() + offsetMinutes * 60000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function ReservationsPage() {
  const toasts = useToasts()
  const [items, setItems] = useState<Reservation[]>([])
  const [tables, setTables] = useState<Table[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems(await api.get<Reservation[]>('/admin/occupancy/reservations'))
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки броней')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    void api.get<Table[]>('/admin/hall/tables').then(setTables).catch(() => setTables([]))
  }, [load])

  const grouped = useMemo(() => {
    const map = new Map<string, Reservation[]>()
    for (const item of items) {
      const day = item.reserved_at.slice(0, 10)
      const list = map.get(day) ?? []
      list.push(item)
      map.set(day, list)
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [items])

  const setStatus = async (item: Reservation, status: ReservationStatus) => {
    try {
      const updated = await api.patch<Reservation>(`/admin/occupancy/reservations/${item.id}`, { status })
      setItems((prev) => prev.map((r) => (r.id === item.id ? updated : r)))
      toasts.ok(`${item.guest_name}: ${RESERVATION_STATUS_LABEL[status]}`)
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const seat = async (item: Reservation) => {
    try {
      await api.post(`/admin/occupancy/reservations/${item.id}/seat`)
      await load()
      toasts.ok(`${item.guest_name} посажены`)
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка посадки')
    }
  }

  const remove = async (item: Reservation) => {
    try {
      await api.del(`/admin/occupancy/reservations/${item.id}`)
      await load()
      toasts.ok('Бронь удалена')
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка удаления')
    }
  }

  if (loading) return <Spinner />
  if (error && !items.length) return <ErrorNote>{error}</ErrorNote>

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        <div className="toolbar">
          <Button variant="primary" onClick={() => setCreating(true)}>
            + Бронь
          </Button>
          <Button onClick={load}>Обновить</Button>
          <span className="muted">всего: {items.length}</span>
        </div>

        {grouped.length === 0 ? (
          <Empty>Броней пока нет</Empty>
        ) : (
          grouped.map(([day, list]) => (
            <Card key={day}>
              <div className="card-head">
                <h2>
                  {new Date(`${day}T00:00:00`).toLocaleDateString('ru-RU', {
                    weekday: 'short',
                    day: 'numeric',
                    month: 'long',
                  })}
                </h2>
                <span className="muted">{list.length}</span>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Гость</th>
                    <th>Телефон</th>
                    <th>Гостей</th>
                    <th>Стол</th>
                    <th>Статус</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {list.map((item) => (
                    <tr key={item.id}>
                      <td>{time(item.reserved_at)}</td>
                      <td>
                        <strong>{item.guest_name}</strong>
                        {item.comment ? <small className="muted"> {item.comment}</small> : null}
                      </td>
                      <td>{item.phone || '—'}</td>
                      <td>{item.guests_count}</td>
                      <td>{item.table_name ?? '—'}</td>
                      <td>
                        <Pill tone={TONE[item.status]}>{RESERVATION_STATUS_LABEL[item.status]}</Pill>
                      </td>
                      <td className="row-actions">
                        {item.status === 'planned' ? (
                          <>
                            <Button small variant="primary" onClick={() => seat(item)}>
                              Посадить
                            </Button>
                            <Button small onClick={() => setStatus(item, 'arrived')}>
                              Пришли
                            </Button>
                          </>
                        ) : null}
                        {item.status === 'arrived' ? (
                          <Button small onClick={() => seat(item)}>
                            Найти стол
                          </Button>
                        ) : null}
                        {item.status === 'planned' ? (
                          <>
                            <Button small onClick={() => setStatus(item, 'no_show')}>
                              Не пришли
                            </Button>
                            <Button small variant="danger" onClick={() => remove(item)}>
                              ×
                            </Button>
                          </>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ))
        )}
      </div>

      <Modal open={creating} title="Новая бронь" onClose={() => setCreating(false)}>
        <ReservationForm
          tables={tables}
          onSubmit={async (payload) => {
            try {
              await api.post('/admin/occupancy/reservations', payload)
              setCreating(false)
              await load()
              toasts.ok('Бронь создана')
            } catch (e) {
              toasts.error(e instanceof Error ? e.message : 'Ошибка создания')
            }
          }}
        />
      </Modal>
    </>
  )
}

function ReservationForm({
  tables,
  onSubmit,
}: {
  tables: Table[]
  onSubmit: (payload: Record<string, unknown>) => void
}) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [guests, setGuests] = useState(2)
  const [tableId, setTableId] = useState('')
  const [when, setWhen] = useState(localDateTime())
  const [duration, setDuration] = useState(120)
  const [comment, setComment] = useState('')

  return (
    <div className="stack">
      <Field label="Имя гостя">
        <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label="Телефон">
        <Input value={phone} onChange={(e) => setPhone(e.target.value)} />
      </Field>
      <div className="grid-2">
        <Field label="Гостей">
          <Input type="number" min={1} max={100} value={guests} onChange={(e) => setGuests(Number(e.target.value))} />
        </Field>
        <Field label="Стол" hint="пусто — подберём при посадке">
          <Select value={tableId} onChange={(e) => setTableId(e.target.value)}>
            <option value="">любой свободный</option>
            {tables
              .filter((t) => t.is_active)
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} · {t.seats} мест
                </option>
              ))}
          </Select>
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Дата и время">
          <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </Field>
        <Field label="Длительность, мин">
          <Input
            type="number"
            min={15}
            max={1440}
            step={15}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
          />
        </Field>
      </div>
      <Field label="Комментарий">
        <Textarea value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      <div className="muted">{dateTime(new Date(when).toISOString())}</div>
      <div className="row-end">
        <Button
          variant="primary"
          disabled={!name.trim()}
          onClick={() =>
            onSubmit({
              guest_name: name.trim(),
              phone: phone.trim(),
              guests_count: guests,
              table_id: tableId || null,
              reserved_at: new Date(when).toISOString(),
              duration_minutes: duration,
              comment: comment.trim(),
            })
          }
        >
          Создать
        </Button>
      </div>
    </div>
  )
}
