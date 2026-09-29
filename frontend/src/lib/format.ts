export function money(kopecks: number | null | undefined, symbol = '₽'): string {
  const value = (kopecks ?? 0) / 100
  return `${value.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ${symbol}`
}

export function plainNumber(kopecks: number | null | undefined): number {
  return (kopecks ?? 0) / 100
}

export function time(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function minutesSince(iso: string | null | undefined): number {
  if (!iso) return 0
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
}

export function grams(value: number | null | undefined): string | null {
  if (!value) return null
  return `${value} г`
}

export const ORDER_STATUS_LABEL: Record<string, string> = {
  new: 'Новый',
  in_progress: 'Готовится',
  ready: 'Готов',
  served: 'Подан',
  closed: 'Закрыт',
  cancelled: 'Отменён',
}

export const TABLE_STATUS_LABEL: Record<string, string> = {
  free: 'Свободен',
  reserved: 'Забронирован',
  seated: 'Гости',
  dirty: 'Уборка',
}

export const RESERVATION_STATUS_LABEL: Record<string, string> = {
  planned: 'Запланирована',
  arrived: 'Пришли',
  cancelled: 'Отменена',
  no_show: 'Не пришли',
}

export const ROLE_LABEL: Record<string, string> = {
  owner: 'Владелец',
  admin: 'Администратор',
  manager: 'Менеджер',
  waiter: 'Официант',
}

export const SHAPE_LABEL: Record<string, string> = {
  rect: 'Прямоугольный',
  round: 'Круглый',
  bar: 'Барный',
}
