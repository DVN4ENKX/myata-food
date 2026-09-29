export type Role = 'owner' | 'admin' | 'manager' | 'waiter'
export type TableShape = 'rect' | 'round' | 'bar'
export type TableStatus = 'free' | 'reserved' | 'seated' | 'dirty'
export type OrderStatus = 'new' | 'in_progress' | 'ready' | 'served' | 'closed' | 'cancelled'
export type OrderSource = 'qr' | 'hall' | 'waiter'
export type ReservationStatus = 'planned' | 'arrived' | 'cancelled' | 'no_show'

export interface User {
  id: string
  username: string
  full_name: string
  email: string | null
  phone: string | null
  role: Role
  is_active: boolean
  can_manage_menu: boolean
  can_manage_hall: boolean
  can_manage_orders: boolean
  can_manage_users: boolean
  can_view_reports: boolean
  salary_percent: number
  notes: string
  last_login_at: string | null
  created_at: string | null
}

export interface Token {
  access_token: string
  token_type: string
  user: User
}

export interface Modifier {
  id: string
  name: string
  price_delta: number
  is_default: boolean
  sort_order: number
  is_active: boolean
  external_id: string | null
}

export interface ModifierGroup {
  id: string
  name: string
  min_select: number
  max_select: number
  sort_order: number
  is_active: boolean
  modifiers: Modifier[]
}

export interface Dish {
  id: string
  category_id: string
  category_name: string
  name: string
  description: string
  price: number
  old_price: number | null
  weight_grams: number | null
  calories: number | null
  cooking_minutes: number
  allergens: string[]
  tags: string[]
  image_url: string | null
  sort_order: number
  kind: string
  is_active: boolean
  is_available: boolean
  show_in_qr: boolean
  external_id: string | null
  integration_code: string | null
  article: string | null
  modifier_groups: ModifierGroup[]
}

export interface Category {
  id: string
  name: string
  description: string
  icon: string
  image_url: string | null
  parent_id: string | null
  sort_order: number
  color: string
  is_active: boolean
  show_in_qr: boolean
  external_id: string | null
  slug: string
  dishes_count: number
  children?: Category[]
  dishes?: Dish[]
}

export interface MenuSettings {
  id: string
  title: string
  subtitle: string
  currency_symbol: string
  show_weights: boolean
  show_calories: boolean
  show_allergens: boolean
  welcome_text: string
  footer_text: string
  theme_color: string
}

export interface PublicMenu {
  venue: string
  table_name: string
  table_number: string
  hall_name: string
  settings: MenuSettings
  categories: Category[]
  dishes_count: number
}

export interface TableSession {
  id: string
  table_id: string
  guests_count: number
  status: TableStatus
  started_at: string
  ended_at: string | null
  wait_minutes: number
  comment: string
  guest_name: string
  opened_by: string | null
}

export interface Hall {
  id: string
  name: string
  description: string
  layout_width: number
  layout_height: number
  sort_order: number
  is_active: boolean
  tables_count: number
  seats_total: number
}

export interface Table {
  id: string
  hall_id: string
  name: string
  seats: number
  shape: TableShape
  x: number
  y: number
  width: number
  height: number
  rotation: number
  color: string | null
  sort_order: number
  is_active: boolean
  note: string
  external_id: string | null
  qr_token: string
  qr_url: string
  status: TableStatus
  current_session: TableSession | null
  seated_since: string | null
  open_orders: number
  order_total: number
  next_reservation_at: string | null
}

export interface OccupancySummary {
  tables_total: number
  tables_busy: number
  tables_free: number
  tables_reserved: number
  tables_cleaning: number
  seats_total: number
  guests_now: number
  occupancy_percent: number
  revenue_today: number
  orders_today: number
  active_sessions: number
}

export interface Reservation {
  id: string
  table_id: string | null
  table_name: string | null
  guest_name: string
  phone: string
  guests_count: number
  reserved_at: string
  duration_minutes: number
  status: ReservationStatus
  comment: string
  created_at: string | null
}

export interface OccupancyBoard {
  generated_at: string
  summary: OccupancySummary
  halls: Hall[]
  tables: Table[]
  reservations_today: number
}

export interface OrderItemModifier {
  id: string
  modifier_id: string | null
  name: string
  price_delta: number
}

export interface OrderItem {
  id: string
  dish_id: string | null
  dish_name: string
  price: number
  quantity: number
  comment: string
  cooking_minutes: number
  status: string
  modifiers: OrderItemModifier[]
  line_total: number
}

export interface Order {
  id: string
  order_number: string
  table_id: string | null
  table_name: string | null
  table_session_id: string | null
  status: OrderStatus
  source: OrderSource
  guests_count: number
  guest_comment: string
  client_name: string
  total_amount: number
  total_discount: number
  external_id: string | null
  exported_to_1c: boolean
  created_at: string
  closed_at: string | null
  items: OrderItem[]
}

export interface KitchenBoard {
  orders: Order[]
  max_wait_minutes: number
}

export interface GuestTableInfo {
  id: string
  name: string
  hall: string
  seats: number
  venue: string
  is_seated: boolean
  status: TableStatus
  guests_count: number
  orders: Order[]
}

export interface CartModifier {
  modifier_id: string
  name: string
  price_delta: number
}

export interface CartItem {
  dish_id: string
  dish_name: string
  price: number
  quantity: number
  comment: string
  modifiers: CartModifier[]
}

export interface DailyReport {
  business_date: string
  guests_total: number
  orders_total: number
  revenue_total: number
  avg_check: number
  tables_used: number
  by_source: Record<string, number>
  top_dishes: { name: string; qty: number; revenue: number }[]
  hourly_load: { hour: number; orders: number; revenue: number }[]
  closed: boolean
}

export interface OneCSettings {
  id: string
  enabled: boolean
  exchange_plan: string
  endpoint_url: string
  login: string
  password_masked: string
  org_ref: string
  price_type_ref: string
  auto_export_interval_minutes: number
  export_categories: boolean
  export_dishes: boolean
  export_modifiers: boolean
  export_orders: boolean
  export_day_closes: boolean
  last_export_at: string | null
  last_import_at: string | null
}

export interface ExportResult {
  log_id: string
  file_name: string
  entities_total: number
  entities_success: number
  entities_error: number
  status: string
  message: string
  download_url: string
}

export interface AuditEntry {
  id: string
  user: string
  action: string
  entity_type: string
  entity_id: string | null
  created_at: string
}

export interface StaffLoad {
  user_id: string
  username: string
  full_name: string
  orders: number
  revenue: number
}

export interface MenuStats {
  dishes_total: number
  dishes_available: number
  dishes_unavailable: number
  categories_total: number
  categories_hidden: number
  avg_price: number
}

export interface SessionListEntry {
  id: string
  guests_count: number
  status: string
  started_at: string
  ended_at: string | null
  wait_minutes: number
  comment: string
  guest_name: string
  opened_by: string | null
  orders_count: number
  revenue: number
}

export interface PermissionMatrix {
  roles: Record<string, Record<string, boolean>>
  flags: { key: string; label: string }[]
}
