import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/state/AuthContext'
import type { Permission } from '@/state/AuthContext'
import AdminLayout from '@/pages/AdminLayout'
import Dashboard from '@/pages/Dashboard'
import GuestMenu from '@/pages/GuestMenu'
import HallPage from '@/pages/HallPage'
import Login from '@/pages/Login'
import MenuPage from '@/pages/MenuPage'
import OneCPage from '@/pages/OneCPage'
import OrdersPage from '@/pages/OrdersPage'
import ReportsPage from '@/pages/ReportsPage'
import ReservationsPage from '@/pages/ReservationsPage'
import StaffPage from '@/pages/StaffPage'
import { Spinner } from '@/components/ui'

function Protected({ children, flag }: { children: JSX.Element; flag?: Permission }) {
  const { user, ready, can } = useAuth()
  if (!ready) return <Spinner />
  if (!user) return <Navigate to="/login" replace />
  if (flag && !can(flag)) {
    return <div className="page">Недостаточно прав для этого раздела</div>
  }
  return children
}

function Shell() {
  const { ready, user } = useAuth()
  if (!ready) return <Spinner />
  return (
    <Routes>
      <Route path="/t/:token" element={<GuestMenu />} />
      <Route
        path="/login"
        element={user ? <Navigate to="/" replace /> : <Login />}
      />
      <Route
        element={
          <Protected>
            <AdminLayout />
          </Protected>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route
          path="/hall"
          element={
            <Protected flag="can_manage_orders">
              <HallPage />
            </Protected>
          }
        />
        <Route
          path="/orders"
          element={
            <Protected flag="can_manage_orders">
              <OrdersPage />
            </Protected>
          }
        />
        <Route
          path="/menu"
          element={
            <Protected flag="can_manage_menu">
              <MenuPage />
            </Protected>
          }
        />
        <Route
          path="/reservations"
          element={
            <Protected flag="can_manage_orders">
              <ReservationsPage />
            </Protected>
          }
        />
        <Route
          path="/reports"
          element={
            <Protected flag="can_view_reports">
              <ReportsPage />
            </Protected>
          }
        />
        <Route
          path="/1c"
          element={
            <Protected flag="can_view_reports">
              <OneCPage />
            </Protected>
          }
        />
        <Route
          path="/staff"
          element={
            <Protected flag="can_manage_users">
              <StaffPage />
            </Protected>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}
