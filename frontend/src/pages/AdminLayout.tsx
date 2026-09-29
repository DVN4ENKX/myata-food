import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '@/state/AuthContext'
import type { Permission } from '@/state/AuthContext'
import { useLiveChannel } from '@/lib/useLive'
import { ROLE_LABEL, time } from '@/lib/format'

interface NavItem {
  to: string
  label: string
  icon: string
  flag?: Permission
  adminOnly?: boolean
}

const NAV: NavItem[] = [
  { to: '/', label: 'Сейчас', icon: '◉' },
  // waiters work the floor too, so the hall is visible to anyone who seats
  // guests; the editing controls inside stay behind can_manage_hall
  { to: '/hall', label: 'Зал', icon: '▦', flag: 'can_manage_orders' },
  { to: '/orders', label: 'Заказы', icon: '☰', flag: 'can_manage_orders' },
  { to: '/menu', label: 'Меню', icon: '☕', flag: 'can_manage_menu' },
  { to: '/reservations', label: 'Брони', icon: '❑', flag: 'can_manage_orders' },
  { to: '/reports', label: 'Отчёты', icon: '▤', flag: 'can_view_reports' },
  { to: '/1c', label: '1С', icon: '⇄', flag: 'can_view_reports' },
  { to: '/staff', label: 'Сотрудники', icon: '☺', flag: 'can_manage_users' },
]

export default function AdminLayout() {
  const { user, logout, can } = useAuth()
  const navigate = useNavigate()
  const online = useLiveChannel('occupancy', () => window.dispatchEvent(new CustomEvent('myata:occupancy')))

  const items = NAV.filter((item) => {
    if (item.adminOnly && !can('can_manage_users')) return false
    if (item.flag) return can(item.flag)
    return true
  })

  return (
    <div className="admin">
      <aside className="admin-side">
        <div className="admin-brand">
          Myata Food
          <small>{user ? ROLE_LABEL[user.role] ?? user.role : ''}</small>
        </div>
        <nav>
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}>
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="admin-side-foot">
          <div className={`ws-flag ${online ? 'on' : 'off'}`}>{online ? 'realtime' : 'offline'}</div>
          <div className="admin-user">
            <strong>{user?.full_name || user?.username}</strong>
            <small>{user?.username}</small>
          </div>
          <button
            className="link"
            onClick={() => {
              logout()
              navigate('/login', { replace: true })
            }}
          >
            Выйти
          </button>
        </div>
      </aside>

      <div className="admin-main">
        <header className="admin-top">
          <span className="muted">
            {new Date().toLocaleDateString('ru-RU', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </span>
          <span className="muted">{time(new Date().toISOString())}</span>
        </header>
        <div className="admin-content">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
