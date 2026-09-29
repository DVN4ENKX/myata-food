import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { grams, money, ORDER_STATUS_LABEL } from '@/lib/format'
import type { CartItem, Category, Dish, GuestTableInfo, Order, PublicMenu } from '@/lib/types'
import { Button, Empty, ErrorNote, Modal, Pill, Spinner, useToasts, Toasts } from '@/components/ui'

interface Draft {
  dish: Dish
  quantity: number
  comment: string
  modifiers: Record<string, string[]>
}

const CART_PREFIX = 'myata.cart.'

function loadCart(token: string): CartItem[] {
  try {
    const raw = localStorage.getItem(CART_PREFIX + token)
    return raw ? (JSON.parse(raw) as CartItem[]) : []
  } catch {
    return []
  }
}

export default function GuestMenu() {
  const { token = '' } = useParams()
  // keyed so that scanning a different table's QR remounts the page with that
  // table's own cart instead of carrying the previous table's items over
  return <TableMenu token={token} />
}

function TableMenu({ token }: { token: string }) {
  const toasts = useToasts()

  const [menu, setMenu] = useState<PublicMenu | null>(null)
  const [table, setTable] = useState<GuestTableInfo | null>(null)
  const [orders, setOrders] = useState<Order[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [activeCategory, setActiveCategory] = useState<string>('')
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [cart, setCart] = useState<CartItem[]>(() => loadCart(token))
  const [cartOpen, setCartOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [guestComment, setGuestComment] = useState('')
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({})

  const loadMenu = useCallback(async () => {
    try {
      const data = await api.get<PublicMenu>(`/public/menu/${token}`)
      setMenu(data)
      setError('')
      if (!activeCategory && data.categories.length > 0) {
        setActiveCategory(data.categories[0].id)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Меню недоступно')
    } finally {
      setLoading(false)
    }
    // activeCategory is only used for the initial pick
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const loadTable = useCallback(async () => {
    try {
      const info = await api.get<GuestTableInfo>(`/public/table/${token}`)
      setTable(info)
      setOrders(info.orders)
    } catch {
      setTable(null)
    }
  }, [token])

  useEffect(() => {
    void loadMenu()
    void loadTable()
  }, [loadMenu, loadTable])

  useEffect(() => {
    localStorage.setItem(CART_PREFIX + token, JSON.stringify(cart))
  }, [cart, token])

  // the kitchen may stop a dish while the guest is reading: refresh on focus
  useEffect(() => {
    const onFocus = () => {
      void loadMenu()
      void loadTable()
    }
    window.addEventListener('focus', onFocus)
    const timer = window.setInterval(onFocus, 60000)
    return () => {
      window.removeEventListener('focus', onFocus)
      window.clearInterval(timer)
    }
  }, [loadMenu, loadTable])

  const dishes = useMemo(() => {
    if (!menu) return [] as { category: Category; dish: Dish }[]
    const needle = query.trim().toLowerCase()
    const out: { category: Category; dish: Dish }[] = []
    for (const category of menu.categories) {
      for (const dish of category.dishes ?? []) {
        if (!dish.is_available) continue
        if (needle && !`${dish.name} ${dish.description}`.toLowerCase().includes(needle)) continue
        out.push({ category, dish })
      }
    }
    return out
  }, [menu, query])

  const cartCount = cart.reduce((sum, item) => sum + item.quantity, 0)
  const cartTotal = cart.reduce(
    (sum, item) => sum + (item.price + item.modifiers.reduce((s, m) => s + m.price_delta, 0)) * item.quantity,
    0,
  )

  const openDish = (dish: Dish) => {
    const defaults: Record<string, string[]> = {}
    for (const group of dish.modifier_groups) {
      // pre-select exactly min_select options so a required group starts valid
      const take = Math.min(group.min_select, group.modifiers.length)
      defaults[group.id] = group.modifiers.slice(0, take).map((m) => m.id)
    }
    setDraft({ dish, quantity: 1, comment: '', modifiers: defaults })
  }

  const toggleModifier = (groupId: string, modifierId: string, max: number) => {
    setDraft((prev) => {
      if (!prev) return prev
      const current = prev.modifiers[groupId] ?? []
      let rejected = false
      let next: string[]
      if (current.includes(modifierId)) {
        next = current.filter((id) => id !== modifierId)
      } else if (current.length >= max) {
        // do not silently drop an earlier choice to make room
        rejected = true
        next = current
      } else {
        next = [...current, modifierId]
      }
      if (rejected) queueMicrotask(() => toasts.push(`Можно выбрать не больше ${max}`, 'error'))
      return { ...prev, modifiers: { ...prev.modifiers, [groupId]: next } }
    })
  }

  const addDraftToCart = () => {
    if (!draft) return
    const missing = draft.dish.modifier_groups.filter(
      (group) => group.min_select > 0 && (draft.modifiers[group.id] ?? []).length < group.min_select,
    )
    if (missing.length > 0) {
      toasts.error(`Выберите вариант: ${missing.map((g) => g.name).join(', ')}`)
      return
    }
    const modifiers = draft.dish.modifier_groups.flatMap((group) =>
      (draft.modifiers[group.id] ?? []).map((id) => {
        const found = group.modifiers.find((m) => m.id === id)!
        return { modifier_id: id, name: found.name, price_delta: found.price_delta }
      }),
    )
    setCart((prev) => [
      ...prev,
      {
        dish_id: draft.dish.id,
        dish_name: draft.dish.name,
        price: draft.dish.price,
        quantity: draft.quantity,
        comment: draft.comment,
        modifiers,
      },
    ])
    setDraft(null)
    toasts.ok(`${draft.dish.name} — в корзине`)
  }

  const changeQuantity = (index: number, delta: number) => {
    setCart((prev) =>
      prev
        .map((item, i) => (i === index ? { ...item, quantity: item.quantity + delta } : item))
        .filter((item) => item.quantity > 0),
    )
  }

  const submitOrder = async () => {
    if (cart.length === 0) return
    setSending(true)
    try {
      const order = await api.post<Order>(`/public/table/${token}/order`, {
        items: cart.map((item) => ({
          dish_id: item.dish_id,
          quantity: item.quantity,
          comment: item.comment,
          modifiers: item.modifiers.map((m) => ({ modifier_id: m.modifier_id })),
        })),
        guest_comment: guestComment,
        guests_count: table?.guests_count ?? 1,
      })
      setCart([])
      setGuestComment('')
      setCartOpen(false)
      toasts.ok(`Заказ ${order.order_number} принят`)
      await loadTable()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Не удалось отправить заказ')
    } finally {
      setSending(false)
    }
  }

  const scrollToCategory = (id: string) => {
    setActiveCategory(id)
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (loading) return <Spinner label="Загружаем меню…" />
  if (error || !menu) {
    return (
      <div className="guest-error">
        <h1>Меню недоступно</h1>
        <p>{error || 'Ссылка не найдена'}</p>
        <p className="muted">Отсканируйте QR-код на столе или попросите официанта.</p>
      </div>
    )
  }

  const accent = menu.settings.theme_color || '#8b1e1e'

  return (
    <div className="guest" style={{ ['--accent' as string]: accent }}>
      <Toasts items={toasts.items} />
      <header className="guest-head">
        <div className="guest-head-top">
          <div>
            <div className="guest-venue">{menu.venue}</div>
            <h1>{menu.settings.title}</h1>
            <div className="guest-sub">
              {menu.settings.subtitle}
            </div>
          </div>
          <div className="guest-table">
            <span>Стол</span>
            <strong>{menu.table_name}</strong>
            {menu.hall_name ? <small>{menu.hall_name}</small> : null}
          </div>
        </div>
        <div className="guest-status">
          {table?.is_seated ? (
            <Pill tone="good">
              За столом {table.guests_count} гост. · можно заказывать
            </Pill>
          ) : (
            <Pill tone="warn">Подойдите к официанту, чтобы начать заказ</Pill>
          )}
        </div>
        {menu.settings.welcome_text ? <p className="guest-welcome">{menu.settings.welcome_text}</p> : null}
        <input
          className="guest-search"
          placeholder="Поиск по меню"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </header>

      {orders.length > 0 ? (
        <section className="guest-orders">
          <h2>Ваши заказы</h2>
          <div className="guest-order-list">
            {orders.map((order) => (
              <div key={order.id} className="guest-order">
                <div className="guest-order-head">
                  <strong>{order.order_number}</strong>
                  <Pill tone="info">{ORDER_STATUS_LABEL[order.status] ?? order.status}</Pill>
                  <span className="muted">{money(order.total_amount, menu.settings.currency_symbol)}</span>
                </div>
                <ul>
                  {order.items.map((item) => (
                    <li key={item.id}>
                      <span>
                        {item.quantity} × {item.dish_name}
                        {item.comment ? <em> — {item.comment}</em> : null}
                      </span>
                      <span>{money(item.line_total, menu.settings.currency_symbol)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <nav className="guest-tabs">
        {menu.categories.map((category) => (
          <button
            key={category.id}
            className={category.id === activeCategory ? 'active' : ''}
            onClick={() => scrollToCategory(category.id)}
          >
            {category.name}
          </button>
        ))}
      </nav>

      <main className="guest-body">
        {dishes.length === 0 ? <Empty>Ничего не найдено</Empty> : null}
        {menu.categories.map((category) => {
          const items = dishes.filter((d) => d.category.id === category.id)
          if (items.length === 0) return null
          return (
            <section
              key={category.id}
              className="guest-section"
              ref={(el) => {
                sectionRefs.current[category.id] = el
              }}
            >
              <h2>
                {category.name}
                <small>{category.dishes?.length ?? 0}</small>
              </h2>
              <div className="guest-grid">
                {items.map(({ dish }) => (
                  <article key={dish.id} className="dish-card" onClick={() => openDish(dish)}>
                    {dish.image_url ? (
                      <img src={dish.image_url} alt={dish.name} loading="lazy" />
                    ) : (
                      <div className="dish-photo" aria-hidden="true">
                        {dish.name.slice(0, 1)}
                      </div>
                    )}
                    <div className="dish-info">
                      <h3>{dish.name}</h3>
                      {dish.description ? <p>{dish.description}</p> : null}
                      <div className="dish-meta">
                        {grams(dish.weight_grams) ? <span>{grams(dish.weight_grams)}</span> : null}
                        {dish.calories ? <span>{dish.calories} ккал</span> : null}
                        {dish.cooking_minutes ? <span>{dish.cooking_minutes} мин</span> : null}
                      </div>
                      {menu.settings.show_allergens && dish.allergens.length > 0 ? (
                        <div className="dish-allergens">Аллергены: {dish.allergens.join(', ')}</div>
                      ) : null}
                    </div>
                    <div className="dish-price">{money(dish.price, menu.settings.currency_symbol)}</div>
                  </article>
                ))}
              </div>
            </section>
          )
        })}
      </main>

      <footer className="guest-foot">
        {menu.settings.footer_text ? <span>{menu.settings.footer_text}</span> : null}
        <span className="muted">Цены и состав уточняйте у официанта</span>
      </footer>

      {cartCount > 0 ? (
        <button className="cart-bar" onClick={() => setCartOpen(true)}>
          <span>{cartCount} {cartCount === 1 ? 'позиция' : 'позиций'}</span>
          <strong>{money(cartTotal, menu.settings.currency_symbol)}</strong>
          <span>Оформить →</span>
        </button>
      ) : null}

      <Modal
        open={draft !== null}
        title={draft?.dish.name ?? ''}
        onClose={() => setDraft(null)}
        footer={
          <>
            <Button onClick={() => setDraft(null)}>Отмена</Button>
            <Button variant="primary" onClick={addDraftToCart}>
              В корзину ·{' '}
              {money(
                draft
                  ? (draft.dish.price +
                      draft.dish.modifier_groups.reduce(
                        (sum, group) =>
                          sum +
                          (draft.modifiers[group.id] ?? []).reduce(
                            (s, id) => s + (group.modifiers.find((m) => m.id === id)?.price_delta ?? 0),
                            0,
                          ),
                        0,
                      )) *
                    draft.quantity
                  : 0,
                menu.settings.currency_symbol,
              )}
            </Button>
          </>
        }
      >
        {draft ? (
          <div className="draft">
            {draft.dish.description ? <p className="muted">{draft.dish.description}</p> : null}
            {draft.dish.modifier_groups.map((group) => (
              <div key={group.id} className="draft-group">
                <div className="draft-group-head">
                  <strong>{group.name}</strong>
                  <small className="muted">
                    {group.min_select > 0 ? 'обязательно' : 'по желанию'} · до {group.max_select}
                  </small>
                </div>
                <div className="draft-options">
                  {group.modifiers.map((modifier) => {
                    const selected = (draft.modifiers[group.id] ?? []).includes(modifier.id)
                    return (
                      <button
                        key={modifier.id}
                        className={`draft-option ${selected ? 'selected' : ''}`}
                        onClick={() => toggleModifier(group.id, modifier.id, group.max_select)}
                      >
                        <span>{modifier.name}</span>
                        <span>
                          {modifier.price_delta > 0
                            ? `+${money(modifier.price_delta, menu.settings.currency_symbol)}`
                            : '—'}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
            <label className="field">
              <span className="field-label">Комментарий к блюду</span>
              <input
                className="input"
                value={draft.comment}
                placeholder="без лука, острее…"
                onChange={(e) => setDraft({ ...draft, comment: e.target.value })}
              />
            </label>
            <div className="qty">
              <button onClick={() => setDraft({ ...draft, quantity: Math.max(1, draft.quantity - 1) })}>−</button>
              <span>{draft.quantity}</span>
              <button onClick={() => setDraft({ ...draft, quantity: Math.min(99, draft.quantity + 1) })}>+</button>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={cartOpen}
        title="Ваш заказ"
        onClose={() => setCartOpen(false)}
        wide
        footer={
          <>
            <Button onClick={() => setCart([])}>Очистить</Button>
            <Button variant="primary" disabled={sending || !table?.is_seated} onClick={submitOrder}>
              {sending ? 'Отправляем…' : `Отправить · ${money(cartTotal, menu.settings.currency_symbol)}`}
            </Button>
          </>
        }
      >
        {cart.length === 0 ? (
          <Empty>Корзина пуста</Empty>
        ) : (
          <div className="cart">
            {cart.map((item, index) => (
              <div key={`${item.dish_id}-${index}`} className="cart-item">
                <div className="cart-item-main">
                  <strong>{item.dish_name}</strong>
                  {item.modifiers.length > 0 ? (
                    <small className="muted">{item.modifiers.map((m) => m.name).join(', ')}</small>
                  ) : null}
                  {item.comment ? <small className="muted">«{item.comment}»</small> : null}
                </div>
                <div className="qty">
                  <button onClick={() => changeQuantity(index, -1)}>−</button>
                  <span>{item.quantity}</span>
                  <button onClick={() => changeQuantity(index, 1)}>+</button>
                </div>
                <div className="cart-item-price">
                  {money(
                    (item.price + item.modifiers.reduce((s, m) => s + m.price_delta, 0)) * item.quantity,
                    menu.settings.currency_symbol,
                  )}
                </div>
              </div>
            ))}
            <label className="field">
              <span className="field-label">Комментарий к заказу</span>
              <input
                className="input"
                value={guestComment}
                placeholder="например, без лука во всех блюдах"
                onChange={(e) => setGuestComment(e.target.value)}
              />
            </label>
            {!table?.is_seated ? (
              <ErrorNote>Чтобы заказать, сначала подойдите к официанту.</ErrorNote>
            ) : null}
          </div>
        )}
      </Modal>
    </div>
  )
}
