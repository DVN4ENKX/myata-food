import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, downloadQrPng, downloadQrSheet } from '@/lib/api'
import { minutesSince, money, TABLE_STATUS_LABEL, time } from '@/lib/format'
import { useAuth } from '@/state/AuthContext'
import type { Hall, Table } from '@/lib/types'
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
  Toggle,
  useToasts,
} from '@/components/ui'

interface DragState {
  id: string
  offsetX: number
  offsetY: number
  moved: boolean
}

const STATUS_TONE: Record<string, 'good' | 'warn' | 'bad' | 'default'> = {
  seated: 'good',
  reserved: 'warn',
  dirty: 'bad',
  free: 'default',
}

export default function HallPage() {
  const toasts = useToasts()
  const { can } = useAuth()
  // waiters can see the floor but must not rearrange furniture
  const canEdit = can('can_manage_hall')
  const [halls, setHalls] = useState<Hall[]>([])
  const [tables, setTables] = useState<Table[]>([])
  const [hallId, setHallId] = useState<string>('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [editing, setEditing] = useState<Table | null>(null)
  const [seatTarget, setSeatTarget] = useState<Table | null>(null)
  const [newTableHall, setNewTableHall] = useState<string>('')
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const drag = useRef<DragState | null>(null)

  const load = useCallback(async () => {
    try {
      const [h, t] = await Promise.all([
        api.get<Hall[]>('/admin/hall/halls'),
        api.get<Table[]>('/admin/hall/tables'),
      ])
      setHalls(h)
      setTables(t)
      setHallId((prev) => prev || h[0]?.id || '')
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const hall = useMemo(() => halls.find((h) => h.id === hallId) ?? null, [halls, hallId])
  const visible = useMemo(
    () => tables.filter((t) => t.hall_id === hallId).sort((a, b) => a.sort_order - b.sort_order),
    [tables, hallId],
  )

  // canvas drag: keep coordinates inside the hall area
  useEffect(() => {
    const onMove = (event: MouseEvent) => {
      const state = drag.current
      const canvas = canvasRef.current
      if (!state || !canvas) return
      const rect = canvas.getBoundingClientRect()
      const x = Math.round(Math.max(0, Math.min(event.clientX - rect.left - state.offsetX, rect.width - 40)))
      const y = Math.round(Math.max(0, Math.min(event.clientY - rect.top - state.offsetY, rect.height - 40)))
      state.moved = true
      setTables((prev) =>
        prev.map((t) => (t.id === state.id ? { ...t, x, y, width: hall ? t.width : 110, height: t.height } : t)),
      )
    }
    const onUp = () => {
      if (drag.current?.moved) setDirty(true)
      drag.current = null
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
  }, [hall])

  const saveLayout = async () => {
    if (!hall) return
    try {
      await api.post('/admin/hall/tables/layout', {
        tables: visible.map((t) => ({
          id: t.id,
          x: t.x,
          y: t.y,
          width: t.width,
          height: t.height,
          rotation: t.rotation,
          shape: t.shape,
        })),
      })
      setDirty(false)
      toasts.ok('Схема сохранена')
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка сохранения схемы')
    }
  }

  const createTable = async (payload: Record<string, unknown>) => {
    try {
      await api.post('/admin/hall/tables', payload)
      toasts.ok('Стол создан')
      setNewTableHall('')
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка создания')
    }
  }

  const patchTable = async (id: string, payload: Record<string, unknown>) => {
    try {
      await api.patch(`/admin/hall/tables/${id}`, payload)
      toasts.ok('Сохранено')
      setEditing(null)
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    }
  }

  const closeTable = async (table: Table) => {
    try {
      await api.post(`/admin/occupancy/tables/${table.id}/close`, { clear_tables: true })
      toasts.ok(`${table.name} закрыт`)
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка закрытия')
    }
  }

  if (loading) return <Spinner />
  if (error && !halls.length) return <ErrorNote>{error}</ErrorNote>

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        <div className="toolbar">
          <Select value={hallId} onChange={(e) => setHallId(e.target.value)}>
            {halls.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name} · {h.tables_count} столов
              </option>
            ))}
          </Select>
          {canEdit ? (
            <>
              <Button onClick={() => setNewTableHall(hallId)}>+ Стол</Button>
              <Button onClick={saveLayout} disabled={!dirty}>
                Сохранить схему
              </Button>
              <Button onClick={() => void downloadQrSheet()}>Скачать все QR</Button>
            </>
          ) : null}
          <span className="muted">
            {canEdit ? (dirty ? 'есть несохранённые изменения' : 'схема сохранена') : 'режим просмотра'}
          </span>
        </div>

        {hall ? (
          <Card>
            <div
              className="canvas"
              ref={canvasRef}
              style={{ height: hall.layout_height, width: hall.layout_width }}
            >
              {visible.map((table) => (
                <div
                  key={table.id}
                  className={`tnode tnode-${table.status}`}
                  style={{
                    left: table.x,
                    top: table.y,
                    width: table.width,
                    height: table.height,
                    transform: `rotate(${table.rotation}deg)`,
                  }}
                  onMouseDown={(e) => {
                    if (!canEdit) return
                    const rect = canvasRef.current!.getBoundingClientRect()
                    drag.current = {
                      id: table.id,
                      offsetX: e.clientX - rect.left - table.x,
                      offsetY: e.clientY - rect.top - table.y,
                      moved: false,
                    }
                  }}
                  onDoubleClick={() => canEdit && setEditing(table)}
                  title={canEdit ? 'Перетащите, двойной клик — настройки' : table.name}
                >
                  <strong>{table.name}</strong>
                  <small>
                    {table.current_session
                      ? `${table.current_session.guests_count} гост.`
                      : `${table.seats} мест`}
                  </small>
                  {table.open_orders > 0 ? <em>{table.open_orders} зак.</em> : null}
                </div>
              ))}
            </div>
          </Card>
        ) : (
          <Empty>Создайте первый зал</Empty>
        )}

        <Card>
          <div className="card-head">
            <h2>Столы</h2>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Стол</th>
                <th>Мест</th>
                <th>Статус</th>
                <th>Сели</th>
                <th>Заказы</th>
                <th>QR</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((table) => (
                <tr key={table.id}>
                  <td>
                    <strong>{table.name}</strong>
                  </td>
                  <td>{table.seats}</td>
                  <td>
                    <Pill tone={STATUS_TONE[table.status]}>{TABLE_STATUS_LABEL[table.status]}</Pill>
                  </td>
                  <td>
                    {table.current_session
                      ? `${minutesSince(table.current_session.started_at)} мин (${time(
                          table.current_session.started_at,
                        )})`
                      : '—'}
                  </td>
                  <td>
                    {table.open_orders > 0 ? `${table.open_orders} · ${money(table.order_total)}` : '—'}
                  </td>
                  <td>
                    <a className="link" href={table.qr_url} target="_blank" rel="noreferrer">
                      ссылка
                    </a>
                  </td>
                  <td className="row-actions">
                    <Button small onClick={() => setSeatTarget(table)}>
                      {table.status === 'seated' ? 'Изменить' : 'Посадить'}
                    </Button>
                    {table.status === 'seated' ? (
                      <Button small variant="danger" onClick={() => closeTable(table)}>
                        Закрыть
                      </Button>
                    ) : null}
                    {canEdit ? (
                      <>
                        <Button small onClick={() => setEditing(table)}>
                          Настроить
                        </Button>
                        <Button small onClick={() => void downloadQrPng(table.id)}>
                          QR
                        </Button>
                      </>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Modal
        open={seatTarget !== null}
        title={seatTarget ? `Стол ${seatTarget.name}` : ''}
        onClose={() => setSeatTarget(null)}
      >
        {seatTarget ? (
          <SeatForm
            table={seatTarget}
            onClose={() => setSeatTarget(null)}
            onSaved={() => {
              setSeatTarget(null)
              void load()
            }}
            onError={toasts.error}
          />
        ) : null}
      </Modal>

      <Modal
        open={newTableHall !== ''}
        title="Новый стол"
        onClose={() => setNewTableHall('')}
      >
        <NewTableForm hallId={newTableHall} onSubmit={createTable} />
      </Modal>

      <Modal
        open={editing !== null}
        title={editing ? `Стол ${editing.name}` : ''}
        onClose={() => setEditing(null)}
      >
        {editing ? (
          <EditTableForm
            table={editing}
            onSubmit={(payload) => patchTable(editing.id, payload)}
            onDelete={async () => {
              try {
                await api.del(`/admin/hall/tables/${editing.id}`)
                toasts.ok('Стол удалён')
                setEditing(null)
                void load()
              } catch (e) {
                toasts.error(e instanceof Error ? e.message : 'Ошибка удаления')
              }
            }}
          />
        ) : null}
      </Modal>
    </>
  )
}

function SeatForm({
  table,
  onClose,
  onSaved,
  onError,
}: {
  table: Table
  onClose: () => void
  onSaved: () => void
  onError: (text: string) => void
}) {
  const seated = table.status === 'seated'
  const [guests, setGuests] = useState(table.current_session?.guests_count ?? table.seats)
  const [name, setName] = useState(table.current_session?.guest_name ?? '')
  const [comment, setComment] = useState(table.current_session?.comment ?? '')
  const [wait, setWait] = useState(table.current_session?.wait_minutes ?? 0)

  const save = async () => {
    try {
      if (seated) {
        await api.post(`/admin/occupancy/tables/${table.id}/update-session`, {
          guests_count: guests,
          guest_name: name,
          comment,
        })
      } else {
        await api.post(`/admin/occupancy/tables/${table.id}/seat`, {
          guests_count: guests,
          guest_name: name,
          comment,
          wait_minutes: wait,
        })
      }
      onSaved()
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  return (
    <div className="stack">
      <Field label="Гостей">
        <Input type="number" min={1} max={100} value={guests} onChange={(e) => setGuests(Number(e.target.value))} />
      </Field>
      <Field label="Имя гостя">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Комментарий">
        <Textarea value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      {!seated ? (
        <Field label="Ожидание, мин" hint="для стоп-листа и кухни">
          <Input type="number" min={0} max={1440} value={wait} onChange={(e) => setWait(Number(e.target.value))} />
        </Field>
      ) : null}
      <div className="row-end">
        <Button onClick={onClose}>Отмена</Button>
        <Button variant="primary" onClick={save}>
          {seated ? 'Сохранить' : 'Посадить'}
        </Button>
      </div>
    </div>
  )
}

function NewTableForm({ hallId, onSubmit }: { hallId: string; onSubmit: (p: Record<string, unknown>) => void }) {
  const [name, setName] = useState('')
  const [seats, setSeats] = useState(2)
  const [shape, setShape] = useState('rect')
  return (
    <div className="stack">
      <Field label="Название">
        <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label="Мест">
        <Input type="number" min={1} max={100} value={seats} onChange={(e) => setSeats(Number(e.target.value))} />
      </Field>
      <Field label="Форма">
        <Select value={shape} onChange={(e) => setShape(e.target.value)}>
          <option value="rect">Прямоугольный</option>
          <option value="round">Круглый</option>
          <option value="bar">Барный</option>
        </Select>
      </Field>
      <div className="row-end">
        <Button
          variant="primary"
          disabled={!name.trim()}
          onClick={() => onSubmit({ hall_id: hallId, name: name.trim(), seats, shape })}
        >
          Создать
        </Button>
      </div>
    </div>
  )
}

function EditTableForm({
  table,
  onSubmit,
  onDelete,
}: {
  table: Table
  onSubmit: (p: Record<string, unknown>) => void
  onDelete: () => void
}) {
  const [name, setName] = useState(table.name)
  const [seats, setSeats] = useState(table.seats)
  const [shape, setShape] = useState(table.shape)
  const [note, setNote] = useState(table.note)
  const [active, setActive] = useState(table.is_active)
  const [externalId, setExternalId] = useState(table.external_id ?? '')

  return (
    <div className="stack">
      <Field label="Название">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="grid-2">
        <Field label="Мест">
          <Input type="number" min={1} max={100} value={seats} onChange={(e) => setSeats(Number(e.target.value))} />
        </Field>
        <Field label="Форма">
          <Select value={shape} onChange={(e) => setShape(e.target.value as Table['shape'])}>
            <option value="rect">Прямоугольный</option>
            <option value="round">Круглый</option>
            <option value="bar">Барный</option>
          </Select>
        </Field>
      </div>
      <Field label="Внешний код 1С">
        <Input value={externalId} onChange={(e) => setExternalId(e.target.value)} />
      </Field>
      <Field label="Заметка">
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Toggle checked={active} onChange={setActive} label="Стол активен" />
      <div className="row-end">
        <Button variant="danger" onClick={onDelete}>
          Удалить
        </Button>
        <Button
          variant="primary"
          onClick={() =>
            onSubmit({
              name: name.trim(),
              seats,
              shape,
              note,
              is_active: active,
              external_id: externalId.trim() || null,
            })
          }
        >
          Сохранить
        </Button>
      </div>
    </div>
  )
}
