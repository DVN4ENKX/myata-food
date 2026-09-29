import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { dateTime, ROLE_LABEL } from '@/lib/format'
import type { AuditEntry, PermissionMatrix, Role, User } from '@/lib/types'
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
import { useAuth } from '@/state/AuthContext'

const FLAGS: { key: 'can_manage_menu' | 'can_manage_hall' | 'can_manage_orders' | 'can_manage_users' | 'can_view_reports'; label: string }[] = [
  { key: 'can_manage_menu', label: 'Меню' },
  { key: 'can_manage_hall', label: 'Зал' },
  { key: 'can_manage_orders', label: 'Заказы' },
  { key: 'can_manage_users', label: 'Сотрудники' },
  { key: 'can_view_reports', label: 'Отчёты' },
]

export default function StaffPage() {
  const toasts = useToasts()
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [matrix, setMatrix] = useState<PermissionMatrix | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<User | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    try {
      const [u, a, m] = await Promise.all([
        api.get<User[]>('/admin/users'),
        api.get<AuditEntry[]>('/admin/users/audit', { limit: 50 }),
        api.get<PermissionMatrix>('/admin/users/permissions'),
      ])
      setUsers(u)
      setAudit(a)
      setMatrix(m)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки сотрудников')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const toggleActive = async (target: User) => {
    try {
      const updated = await api.patch<User>(`/admin/users/${target.id}`, { is_active: !target.is_active })
      setUsers((prev) => prev.map((u) => (u.id === target.id ? updated : u)))
      toasts.ok(target.is_active ? 'Сотрудник отключён' : 'Сотрудник включён')
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const resetPin = async (target: User) => {
    const pin = window.prompt('Новый PIN (4–12 символов)', '')
    if (!pin) return
    try {
      await api.post(`/admin/users/${target.id}/reset-pin`, { pin })
      toasts.ok('PIN обновлён')
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка сброса PIN')
    }
  }

  if (loading) return <Spinner />
  if (error && !users.length) return <ErrorNote>{error}</ErrorNote>

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        <div className="toolbar">
          <Button variant="primary" onClick={() => setCreating(true)}>
            + Сотрудник
          </Button>
          <Button onClick={load}>Обновить</Button>
          <span className="muted">всего: {users.length}</span>
        </div>

        <Card>
          <table className="table">
            <thead>
              <tr>
                <th>Логин</th>
                <th>Имя</th>
                <th>Роль</th>
                <th>Доступы</th>
                <th>Вход</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <strong>{u.username}</strong>
                    {me?.id === u.id ? <small className="muted"> это вы</small> : null}
                  </td>
                  <td>
                    {u.full_name}
                    {u.phone ? <small className="muted"> {u.phone}</small> : null}
                  </td>
                  <td>{ROLE_LABEL[u.role] ?? u.role}</td>
                  <td className="flags">
                    {FLAGS.filter((f) => u[f.key]).map((f) => (
                      <Pill key={f.key} tone="info">
                        {f.label}
                      </Pill>
                    ))}
                    {FLAGS.every((f) => !u[f.key]) ? <span className="muted">нет</span> : null}
                  </td>
                  <td>{u.last_login_at ? dateTime(u.last_login_at) : '—'}</td>
                  <td className="row-actions">
                    <Button small onClick={() => setEditing(u)}>
                      Изменить
                    </Button>
                    <Button small onClick={() => resetPin(u)}>
                      PIN
                    </Button>
                    <Button
                      small
                      variant={u.is_active ? 'danger' : 'default'}
                      disabled={me?.id === u.id}
                      onClick={() => toggleActive(u)}
                    >
                      {u.is_active ? 'Отключить' : 'Включить'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        {matrix ? (
          <Card>
            <div className="card-head">
              <h2>Права по ролям (по умолчанию)</h2>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Роль</th>
                  {matrix.flags.map((flag) => (
                    <th key={flag.key}>{flag.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(matrix.roles).map(([role, perms]) => (
                  <tr key={role}>
                    <td>{ROLE_LABEL[role] ?? role}</td>
                    {matrix.flags.map((flag) => (
                      <td key={flag.key}>{perms[flag.key] ? '✓' : '—'}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ) : null}

        <Card>
          <div className="card-head">
            <h2>Журнал действий</h2>
          </div>
          {audit.length === 0 ? (
            <Empty>Журнал пуст</Empty>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Когда</th>
                  <th>Кто</th>
                  <th>Действие</th>
                  <th>Объект</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((entry) => (
                  <tr key={entry.id}>
                    <td>{dateTime(entry.created_at)}</td>
                    <td>{entry.user}</td>
                    <td>{entry.action}</td>
                    <td className="muted">
                      {entry.entity_type} {entry.entity_id ?? ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Modal open={creating} title="Новый сотрудник" onClose={() => setCreating(false)}>
        <UserForm
          onSubmit={async (payload) => {
            try {
              await api.post('/admin/users', payload)
              setCreating(false)
              toasts.ok('Сотрудник создан')
              void load()
            } catch (e) {
              toasts.error(e instanceof Error ? e.message : 'Ошибка создания')
            }
          }}
        />
      </Modal>

      <Modal open={editing !== null} title={editing?.username ?? ''} onClose={() => setEditing(null)}>
        {editing ? (
          <UserForm
            initial={editing}
            onSubmit={async (payload) => {
              try {
                await api.patch(`/admin/users/${editing.id}`, payload)
                setEditing(null)
                toasts.ok('Сохранено')
                void load()
              } catch (e) {
                toasts.error(e instanceof Error ? e.message : 'Ошибка сохранения')
              }
            }}
          />
        ) : null}
      </Modal>
    </>
  )
}

function UserForm({
  initial,
  onSubmit,
}: {
  initial?: User
  onSubmit: (payload: Record<string, unknown>) => void
}) {
  const [username, setUsername] = useState(initial?.username ?? '')
  const [fullName, setFullName] = useState(initial?.full_name ?? '')
  const [phone, setPhone] = useState(initial?.phone ?? '')
  const [email, setEmail] = useState(initial?.email ?? '')
  const [role, setRole] = useState<Role>(initial?.role ?? 'waiter')
  const [password, setPassword] = useState('')
  const [pin, setPin] = useState('')
  const [salary, setSalary] = useState(initial?.salary_percent ?? 0)
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [flags, setFlags] = useState<Record<string, boolean>>(
    Object.fromEntries(FLAGS.map((f) => [f.key, initial?.[f.key] ?? false])),
  )

  const submit = () => {
    const payload: Record<string, unknown> = {
      full_name: fullName.trim(),
      phone: phone.trim() || null,
      email: email.trim() || null,
      salary_percent: salary,
      notes: notes.trim(),
      ...flags,
    }
    if (!initial) {
      payload.username = username.trim()
      payload.role = role
      payload.password = password
      if (pin.trim()) payload.pin = pin.trim()
    } else {
      payload.role = role
      if (password) payload.password = password
      if (pin.trim()) payload.pin = pin.trim()
    }
    onSubmit(payload)
  }

  return (
    <div className="stack">
      {!initial ? (
        <div className="grid-2">
          <Field label="Логин" hint="латиница, цифры, . _ -">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </Field>
          <Field label="Роль">
            <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {Object.entries(ROLE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      ) : null}

      <Field label="Имя">
        <Input value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus={Boolean(initial)} />
      </Field>
      <div className="grid-2">
        <Field label="Телефон">
          <Input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label="Email">
          <Input value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
      </div>
      <div className="grid-2">
        <Field label={initial ? 'Новый пароль' : 'Пароль'} hint={initial ? 'оставьте пустым, чтобы не менять' : 'минимум 4 символа'}>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </Field>
        <Field label="PIN" hint="4–12 символов, для быстрого входа">
          <Input value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" />
        </Field>
      </div>
      {initial ? (
        <Field label="Роль">
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {Object.entries(ROLE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      <div className="grid-2">
        <Field label="Процент от выручки">
          <Input type="number" min={0} max={100} value={salary} onChange={(e) => setSalary(Number(e.target.value))} />
        </Field>
      </div>
      <Field label="Заметка">
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <Field label="Индивидуальные доступы" hint="если роль даёт права по умолчанию, оставьте всё как есть">
        <div className="row-wrap">
          {FLAGS.map((flag) => (
            <Toggle
              key={flag.key}
              label={flag.label}
              checked={flags[flag.key] ?? false}
              onChange={(checked) => setFlags((prev) => ({ ...prev, [flag.key]: checked }))}
            />
          ))}
        </div>
      </Field>
      <div className="row-end">
        <Button
          variant="primary"
          disabled={!initial && (username.trim().length < 2 || password.length < 4)}
          onClick={submit}
        >
          Сохранить
        </Button>
      </div>
    </div>
  )
}
