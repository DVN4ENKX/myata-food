import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { dateTime } from '@/lib/format'
import type { ExportResult, OneCSettings } from '@/lib/types'
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Input,
  Pill,
  Spinner,
  Toggle,
  Toasts,
  useToasts,
} from '@/components/ui'

interface LogRow {
  id: string
  direction: string
  status: string
  file_name: string | null
  entities_total: number
  entities_success: number
  entities_error: number
  message: string
  started_at: string
  finished_at: string | null
}

interface SyncMapRow {
  entity_type: string
  local_id: string
  external_id: string
  last_synced_at: string | null
}

export default function OneCPage() {
  const toasts = useToasts()
  const [settings, setSettings] = useState<OneCSettings | null>(null)
  const [logs, setLogs] = useState<LogRow[]>([])
  const [maps, setMaps] = useState<SyncMapRow[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)

  const load = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        api.get<OneCSettings>('/admin/integration/1c/settings'),
        api.get<LogRow[]>('/admin/integration/1c/logs', { limit: 30 }),
      ])
      setSettings(s)
      setLogs(l)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки настроек 1С')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const save = async (payload: Partial<OneCSettings> & { password?: string }) => {
    try {
      const updated = await api.put<OneCSettings>('/admin/integration/1c/settings', payload)
      setSettings(updated)
      toasts.ok('Настройки 1С сохранены')
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    }
  }

  const runExport = async () => {
    setExporting(true)
    try {
      const res = await api.post<ExportResult>('/admin/integration/1c/export', {
        categories: true,
        dishes: true,
        modifiers: true,
        orders: true,
        day_closes: false,
        order_status: ['new', 'in_progress', 'ready', 'served', 'closed'],
        deliver: false,
      })
      toasts.ok(`Экспорт готов: ${res.file_name}`)
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка экспорта')
    } finally {
      setExporting(false)
    }
  }

  const downloadXml = async (logId: string) => {
    try {
      const text = await api.text(`/admin/integration/1c/exports/${logId}/xml`)
      const blob = new Blob([text], { type: 'application/xml' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `1c-${logId.slice(0, 8)}.xml`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Не удалось скачать XML')
    }
  }

  if (loading) return <Spinner />
  if (error && !settings) return <ErrorNote>{error}</ErrorNote>

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        {settings ? (
          <Card>
            <div className="card-head">
              <h2>Обмен с 1С</h2>
              <div className="row-wrap">
                <Pill tone={settings.enabled ? 'good' : 'bad'}>
                  {settings.enabled ? 'включено' : 'выключено'}
                </Pill>
                <Button variant="primary" disabled={exporting} onClick={runExport}>
                  {exporting ? 'Экспортуем…' : 'Экспортировать в XML'}
                </Button>
              </div>
            </div>
            <SettingsForm settings={settings} onSave={save} />
          </Card>
        ) : null}

        <Card>
          <div className="card-head">
            <h2>История обмена</h2>
            <Button small onClick={load}>
              Обновить
            </Button>
          </div>
          {logs.length === 0 ? (
            <Empty>Обменов ещё не было</Empty>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Начало</th>
                  <th>Направление</th>
                  <th>Статус</th>
                  <th>Объекты</th>
                  <th>Сообщение</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {logs.map((row) => (
                  <tr key={row.id}>
                    <td>{dateTime(row.started_at)}</td>
                    <td>{row.direction}</td>
                    <td>
                      <Pill tone={row.status === 'success' ? 'good' : row.status === 'error' ? 'bad' : 'warn'}>
                        {row.status}
                      </Pill>
                    </td>
                    <td>
                      {row.entities_success}/{row.entities_total}
                      {row.entities_error > 0 ? ` · ошибок: ${row.entities_error}` : ''}
                    </td>
                    <td className="muted">{row.message}</td>
                    <td>
                      <Button small onClick={() => downloadXml(row.id)}>
                        XML
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card>
          <div className="card-head">
            <h2>Сопоставления с 1С</h2>
            <Button small
              onClick={() => {
                void api
                  .get<SyncMapRow[]>('/admin/integration/1c/maps', { limit: 200 })
                  .then((rows) => {
                    setMaps(rows)
                    toasts.ok(`Загружено ${rows.length} записей`)
                  })
                  .catch((e: Error) => toasts.error(e.message))
              }}
            >
              Загрузить
            </Button>
          </div>
          {maps.length === 0 ? (
            <Empty>Нажмите «Загрузить», чтобы увидеть сопоставления</Empty>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Тип</th>
                  <th>В системе</th>
                  <th>В 1С</th>
                </tr>
              </thead>
              <tbody>
                {maps.map((m) => (
                  <tr key={`${m.entity_type}-${m.local_id}`}>
                    <td>{m.entity_type}</td>
                    <td className="muted">{m.local_id}</td>
                    <td>{m.external_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  )
}

function SettingsForm({
  settings,
  onSave,
}: {
  settings: OneCSettings
  onSave: (payload: Partial<OneCSettings> & { password?: string }) => void
}) {
  const [draft, setDraft] = useState(settings)
  const [password, setPassword] = useState('')
  const patch = (values: Partial<OneCSettings>) => setDraft((prev) => ({ ...prev, ...values }))

  return (
    <div className="stack">
      <div className="grid-2">
        <Field label="План обмена">
          <Input value={draft.exchange_plan} onChange={(e) => patch({ exchange_plan: e.target.value })} />
        </Field>
        <Field label="Адрес веб-сервиса">
          <Input value={draft.endpoint_url} onChange={(e) => patch({ endpoint_url: e.target.value })} />
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Логин">
          <Input value={draft.login} onChange={(e) => patch({ login: e.target.value })} />
        </Field>
        <Field label="Пароль" hint={settings.password_masked || 'не задан'}>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Организация (ref)">
          <Input value={draft.org_ref} onChange={(e) => patch({ org_ref: e.target.value })} />
        </Field>
        <Field label="Тип цены (ref)">
          <Input value={draft.price_type_ref} onChange={(e) => patch({ price_type_ref: e.target.value })} />
        </Field>
      </div>
      <Field label="Интервал автовыгрузки, мин" hint="0 — только вручную">
        <Input
          type="number"
          min={0}
          max={1440}
          value={draft.auto_export_interval_minutes}
          onChange={(e) => patch({ auto_export_interval_minutes: Number(e.target.value) })}
        />
      </Field>
      <Field label="Что выгружать">
        <div className="row-wrap">
          <Toggle label="Категории" checked={draft.export_categories} onChange={(v) => patch({ export_categories: v })} />
          <Toggle label="Блюда" checked={draft.export_dishes} onChange={(v) => patch({ export_dishes: v })} />
          <Toggle label="Модификаторы" checked={draft.export_modifiers} onChange={(v) => patch({ export_modifiers: v })} />
          <Toggle label="Заказы" checked={draft.export_orders} onChange={(v) => patch({ export_orders: v })} />
          <Toggle label="Закрытия смен" checked={draft.export_day_closes} onChange={(v) => patch({ export_day_closes: v })} />
        </div>
      </Field>
      <div className="row-wrap">
        <Toggle label="Обмен включён" checked={draft.enabled} onChange={(v) => patch({ enabled: v })} />
        <span className="muted">
          последняя выгрузка: {draft.last_export_at ? dateTime(draft.last_export_at) : '—'}
        </span>
      </div>
      <div className="row-end">
        <Button
          variant="primary"
          onClick={() => onSave({ ...draft, ...(password ? { password } : {}) })}
        >
          Сохранить
        </Button>
      </div>
    </div>
  )
}
