import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, uploadImage } from '@/lib/api'
import { money, plainNumber } from '@/lib/format'
import type { Category, Dish, MenuSettings, MenuStats, ModifierGroup } from '@/lib/types'
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

type Tab = 'dishes' | 'categories' | 'modifiers' | 'settings' | 'stoplist'

export default function MenuPage() {
  const toasts = useToasts()
  const [tab, setTab] = useState<Tab>('dishes')
  const [dishes, setDishes] = useState<Dish[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [groups, setGroups] = useState<ModifierGroup[]>([])
  const [settings, setSettings] = useState<MenuSettings | null>(null)
  const [stats, setStats] = useState<MenuStats | null>(null)
  const [search, setSearch] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [editDish, setEditDish] = useState<Dish | null>(null)
  const [newDish, setNewDish] = useState(false)
  const [editCategory, setEditCategory] = useState<Category | null>(null)
  const [editGroup, setEditGroup] = useState<ModifierGroup | null>(null)

  const load = useCallback(async () => {
    try {
      const [d, c, g, s, st] = await Promise.all([
        api.get<Dish[]>('/admin/menu/dishes'),
        api.get<Category[]>('/admin/menu/categories'),
        api.get<ModifierGroup[]>('/admin/menu/modifier-groups'),
        api.get<MenuSettings>('/admin/menu/settings'),
        api.get<MenuStats>('/admin/menu/stats'),
      ])
      setDishes(d)
      setCategories(c)
      setGroups(g)
      setSettings(s)
      setStats(st)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки меню')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return dishes.filter((d) => {
      if (categoryId && d.category_id !== categoryId) return false
      if (needle && !d.name.toLowerCase().includes(needle)) return false
      return true
    })
  }, [dishes, search, categoryId])

  const toggleAvailability = async (dish: Dish) => {
    try {
      const updated = await api.post<Dish>(`/admin/menu/dishes/${dish.id}/availability`, {
        is_available: !dish.is_available,
      })
      setDishes((prev) => prev.map((d) => (d.id === dish.id ? updated : d)))
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const setAllAvailability = async (ids: string[], isAvailable: boolean) => {
    try {
      await api.post('/admin/menu/dishes/bulk-availability', { dish_ids: ids, is_available: isAvailable })
      toasts.ok(`${ids.length} блюд обновлено`)
      void load()
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  if (loading) return <Spinner />
  if (error && !dishes.length) return <ErrorNote>{error}</ErrorNote>

  return (
    <>
      <Toasts items={toasts.items} />
      <div className="page">
        {stats ? (
          <div className="stats">
            <Card>Блюд: {stats.dishes_total}</Card>
            <Card>Доступно: {stats.dishes_available}</Card>
            <Card>Стоп-лист: {stats.dishes_unavailable}</Card>
            <Card>Категорий: {stats.categories_total}</Card>
            <Card>Средняя цена: {money(stats.avg_price)}</Card>
          </div>
        ) : null}

        <div className="toolbar">
          {(
            [
              ['dishes', 'Блюда'],
              ['categories', 'Категории'],
              ['modifiers', 'Модификаторы'],
              ['stoplist', 'Стоп-лист'],
              ['settings', 'Настройки'],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <Button key={key} variant={tab === key ? 'primary' : 'default'} onClick={() => setTab(key)}>
              {label}
            </Button>
          ))}
        </div>

        {tab === 'dishes' ? (
          <>
            <div className="toolbar">
              <Input placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)} />
              <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                <option value="">все категории</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
              <Button variant="primary" onClick={() => setNewDish(true)}>
                + Блюдо
              </Button>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Блюдо</th>
                  <th>Категория</th>
                  <th>Цена</th>
                  <th>Порция</th>
                  <th>Кухня</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((dish) => (
                  <tr key={dish.id} className={dish.is_available ? '' : 'row-off'}>
                    <td>
                      <strong>{dish.name}</strong>
                      {dish.article ? <small className="muted"> арт. {dish.article}</small> : null}
                    </td>
                    <td>{dish.category_name}</td>
                    <td>{money(dish.price)}</td>
                    <td>{dish.weight_grams ? `${dish.weight_grams} г` : '—'}</td>
                    <td>{dish.cooking_minutes} мин</td>
                    <td>
                      <Pill tone={dish.is_available ? 'good' : 'bad'}>
                        {dish.is_available ? 'в меню' : 'стоп-лист'}
                      </Pill>
                    </td>
                    <td className="row-actions">
                      <Button small onClick={() => setEditDish(dish)}>
                        Изменить
                      </Button>
                      <Button small onClick={() => toggleAvailability(dish)}>
                        {dish.is_available ? 'Убрать' : 'Вернуть'}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}

        {tab === 'categories' ? (
          <div className="cols">
            <Card className="col-main">
              <table className="table">
                <thead>
                  <tr>
                    <th>Категория</th>
                    <th>Блюд</th>
                    <th>В QR</th>
                    <th>Активна</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {categories.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <strong>{c.name}</strong>
                        {c.description ? <small className="muted"> {c.description}</small> : null}
                      </td>
                      <td>{c.dishes_count}</td>
                      <td>{c.show_in_qr ? 'да' : 'нет'}</td>
                      <td>{c.is_active ? 'да' : 'нет'}</td>
                      <td className="row-actions">
                        <Button small onClick={() => setEditCategory(c)}>
                          Изменить
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card className="col-side">
              <div className="card-head">
                <h2>Новая категория</h2>
              </div>
              <CategoryForm
                onSubmit={async (payload) => {
                  try {
                    await api.post('/admin/menu/categories', payload)
                    toasts.ok('Категория создана')
                    void load()
                  } catch (e) {
                    toasts.error(e instanceof Error ? e.message : 'Ошибка')
                  }
                }}
              />
            </Card>
          </div>
        ) : null}

        {tab === 'modifiers' ? (
          <div className="grid-cards">
            {groups.map((group) => (
              <Card key={group.id}>
                <div className="card-head">
                  <h2>{group.name}</h2>
                  <Pill>
                    {group.min_select === 0 ? 'необязательно' : `мин. ${group.min_select}`} / макс. {group.max_select}
                  </Pill>
                </div>
                <ul className="plain-list">
                  {group.modifiers.map((m) => (
                    <li key={m.id}>
                      {m.name}
                      <span className="muted">
                        {m.price_delta > 0 ? `+${money(m.price_delta)}` : '—'}
                      </span>
                    </li>
                  ))}
                </ul>
                <Button small onClick={() => setEditGroup(group)}>
                  Изменить
                </Button>
              </Card>
            ))}
            <Card>
              <div className="card-head">
                <h2>Новая группа</h2>
              </div>
              <GroupForm
                onSubmit={async (payload) => {
                  try {
                    await api.post('/admin/menu/modifier-groups', payload)
                    toasts.ok('Группа создана')
                    void load()
                  } catch (e) {
                    toasts.error(e instanceof Error ? e.message : 'Ошибка')
                  }
                }}
              />
            </Card>
          </div>
        ) : null}

        {tab === 'stoplist' ? (
          <Card>
            <div className="card-head">
              <h2>Стоп-лист</h2>
              <div className="row-wrap">
                <Button
                  small
                  onClick={() => setAllAvailability(dishes.map((d) => d.id).filter((_, i) => i % 2 === 0), false)}
                >
                  Положить чётные
                </Button>
                <Button
                  small
                  onClick={() => setAllAvailability(dishes.map((d) => d.id).filter((_, i) => i % 2 === 0), true)}
                >
                  Вернуть чётные
                </Button>
              </div>
            </div>
            {dishes.filter((d) => !d.is_available).length === 0 ? (
              <Empty>Сейчас все блюда доступны</Empty>
            ) : (
              <ul className="plain-list">
                {dishes
                  .filter((d) => !d.is_available)
                  .map((d) => (
                    <li key={d.id}>
                      {d.name} <span className="muted">{d.category_name}</span>
                      <Button small onClick={() => toggleAvailability(d)}>
                        Вернуть
                      </Button>
                    </li>
                  ))}
              </ul>
            )}
          </Card>
        ) : null}

        {tab === 'settings' && settings ? (
          <Card>
            <SettingsForm
              settings={settings}
              onSaved={() => {
                toasts.ok('Настройки сохранены')
                void load()
              }}
              onError={toasts.error}
            />
          </Card>
        ) : null}
      </div>

      <Modal
        open={newDish || editDish !== null}
        wide
        title={editDish ? editDish.name : 'Новое блюдо'}
        onClose={() => {
          setNewDish(false)
          setEditDish(null)
        }}
      >
        <DishForm
          dish={editDish}
          categories={categories}
          groups={groups}
          onSubmit={async (payload) => {
            try {
              if (editDish) await api.patch(`/admin/menu/dishes/${editDish.id}`, payload)
              else await api.post('/admin/menu/dishes', payload)
              toasts.ok('Сохранено')
              setNewDish(false)
              setEditDish(null)
              void load()
            } catch (e) {
              toasts.error(e instanceof Error ? e.message : 'Ошибка сохранения')
            }
          }}
          onDelete={
            editDish
              ? async () => {
                  try {
                    await api.del(`/admin/menu/dishes/${editDish.id}`)
                    toasts.ok('Блюдо удалено')
                    setEditDish(null)
                    void load()
                  } catch (e) {
                    toasts.error(e instanceof Error ? e.message : 'Ошибка удаления')
                  }
                }
              : undefined
          }
        />
      </Modal>

      <Modal open={editCategory !== null} title={editCategory?.name ?? ''} onClose={() => setEditCategory(null)}>
        {editCategory ? (
          <CategoryForm
            initial={editCategory}
            onSubmit={async (payload) => {
              try {
                await api.patch(`/admin/menu/categories/${editCategory.id}`, payload)
                toasts.ok('Категория сохранена')
                setEditCategory(null)
                void load()
              } catch (e) {
                toasts.error(e instanceof Error ? e.message : 'Ошибка')
              }
            }}
            onDelete={async () => {
              try {
                await api.del(`/admin/menu/categories/${editCategory.id}`)
                toasts.ok('Категория удалена')
                setEditCategory(null)
                void load()
              } catch (e) {
                toasts.error(e instanceof Error ? e.message : 'Ошибка')
              }
            }}
          />
        ) : null}
      </Modal>

      <Modal open={editGroup !== null} title={editGroup?.name ?? ''} onClose={() => setEditGroup(null)}>
        {editGroup ? (
          <GroupForm
            initial={editGroup}
            onSubmit={async (payload) => {
              try {
                await api.post('/admin/menu/modifier-groups', payload)
                toasts.ok('Группа сохранена')
                setEditGroup(null)
                void load()
              } catch (e) {
                toasts.error(e instanceof Error ? e.message : 'Ошибка')
              }
            }}
            onDelete={async () => {
              try {
                await api.del(`/admin/menu/modifier-groups/${editGroup.id}`)
                toasts.ok('Группа удалена')
                setEditGroup(null)
                void load()
              } catch (e) {
                toasts.error(e instanceof Error ? e.message : 'Ошибка')
              }
            }}
          />
        ) : null}
      </Modal>
    </>
  )
}

function DishForm({
  dish,
  categories,
  groups,
  onSubmit,
  onDelete,
}: {
  dish: Dish | null
  categories: Category[]
  groups: ModifierGroup[]
  onSubmit: (payload: Record<string, unknown>) => void
  onDelete?: () => void
}) {
  const [name, setName] = useState(dish?.name ?? '')
  const [categoryId, setCategoryId] = useState(dish?.category_id ?? categories[0]?.id ?? '')
  const [description, setDescription] = useState(dish?.description ?? '')
  const [price, setPrice] = useState(plainNumber(dish?.price ?? 0))
  const [oldPrice, setOldPrice] = useState(plainNumber(dish?.old_price ?? 0))
  const [weight, setWeight] = useState(dish?.weight_grams ?? 0)
  const [calories, setCalories] = useState(dish?.calories ?? 0)
  const [minutes, setMinutes] = useState(dish?.cooking_minutes ?? 10)
  const [allergens, setAllergens] = useState(dish?.allergens.join(', ') ?? '')
  const [tags, setTags] = useState(dish?.tags.join(', ') ?? '')
  const [image, setImage] = useState(dish?.image_url ?? '')
  const [article, setArticle] = useState(dish?.article ?? '')
  const [integrationCode, setIntegrationCode] = useState(dish?.integration_code ?? '')
  const [active, setActive] = useState(dish?.is_active ?? true)
  const [available, setAvailable] = useState(dish?.is_available ?? true)
  const [inQr, setInQr] = useState(dish?.show_in_qr ?? true)
  const [selected, setSelected] = useState<string[]>(dish?.modifier_groups.map((g) => g.id) ?? [])
  const [busy, setBusy] = useState(false)
  const localToasts = useToasts()

  const pick = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    try {
      const res = await uploadImage(file)
      setImage(res.url)
      localToasts.ok('Фото загружено')
    } catch (e) {
      localToasts.error(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setBusy(false)
    }
  }

  const splitList = (value: string) =>
    value
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean)

  return (
    <div className="stack">
      <Toasts items={localToasts.items} />
      <div className="grid-2">
        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Категория">
          <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label="Описание">
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <div className="grid-2">
        <Field label="Цена, ₽">
          <Input type="number" min={0} step={1} value={price} onChange={(e) => setPrice(Number(e.target.value))} />
        </Field>
        <Field label="Старая цена, ₽" hint="0 — не показывать">
          <Input type="number" min={0} step={1} value={oldPrice} onChange={(e) => setOldPrice(Number(e.target.value))} />
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Вес, г">
          <Input type="number" min={0} value={weight} onChange={(e) => setWeight(Number(e.target.value))} />
        </Field>
        <Field label="Калории">
          <Input type="number" min={0} value={calories} onChange={(e) => setCalories(Number(e.target.value))} />
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Время приготовления, мин">
          <Input type="number" min={0} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
        </Field>
        <Field label="Артикул 1С">
          <Input value={article} onChange={(e) => setArticle(e.target.value)} />
        </Field>
      </div>
      <Field label="Аллергены" hint="через запятую">
        <Input value={allergens} onChange={(e) => setAllergens(e.target.value)} />
      </Field>
      <Field label="Теги" hint="через запятую">
        <Input value={tags} onChange={(e) => setTags(e.target.value)} />
      </Field>
      <Field label="Код 1С">
        <Input value={integrationCode} onChange={(e) => setIntegrationCode(e.target.value)} />
      </Field>
      <Field label="Фото">
        <div className="row-wrap">
          <input
            type="file"
            accept="image/*"
            onChange={(e) => void pick(e.target.files?.[0])}
            disabled={busy}
          />
          {image ? <img className="thumb" src={image} alt="" /> : null}
        </div>
      </Field>
      <Field label="Группы модификаторов">
        <div className="row-wrap">
          {groups.map((g) => (
            <Toggle
              key={g.id}
              label={g.name}
              checked={selected.includes(g.id)}
              onChange={(checked) =>
                setSelected((prev) => (checked ? [...prev, g.id] : prev.filter((id) => id !== g.id)))
              }
            />
          ))}
        </div>
      </Field>
      <div className="row-wrap">
        <Toggle label="Активно" checked={active} onChange={setActive} />
        <Toggle label="Доступно" checked={available} onChange={setAvailable} />
        <Toggle label="Показывать в QR" checked={inQr} onChange={setInQr} />
      </div>
      <div className="row-end">
        {onDelete ? (
          <Button variant="danger" onClick={onDelete}>
            Удалить
          </Button>
        ) : null}
        <Button
          variant="primary"
          disabled={!name.trim() || !categoryId}
          onClick={() =>
            onSubmit({
              category_id: categoryId,
              name: name.trim(),
              description: description.trim(),
              price: Math.round(price * 100),
              old_price: oldPrice > 0 ? Math.round(oldPrice * 100) : null,
              weight_grams: weight > 0 ? weight : null,
              calories: calories > 0 ? calories : null,
              cooking_minutes: minutes,
              allergens: splitList(allergens),
              tags: splitList(tags),
              image_url: image.trim() || null,
              article: article.trim() || null,
              integration_code: integrationCode.trim() || null,
              is_active: active,
              is_available: available,
              show_in_qr: inQr,
              modifier_group_ids: selected,
            })
          }
        >
          Сохранить
        </Button>
      </div>
    </div>
  )
}

function CategoryForm({
  initial,
  onSubmit,
  onDelete,
}: {
  initial?: Category
  onSubmit: (payload: Record<string, unknown>) => void
  onDelete?: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [color, setColor] = useState(initial?.color ?? '#8b1e1e')
  const [active, setActive] = useState(initial?.is_active ?? true)
  const [inQr, setInQr] = useState(initial?.show_in_qr ?? true)

  return (
    <div className="stack">
      <Field label="Название">
        <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label="Описание">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Цвет">
        <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
      </Field>
      <div className="row-wrap">
        <Toggle label="Активна" checked={active} onChange={setActive} />
        <Toggle label="В QR-меню" checked={inQr} onChange={setInQr} />
      </div>
      <div className="row-end">
        {onDelete ? (
          <Button variant="danger" onClick={onDelete}>
            Удалить
          </Button>
        ) : null}
        <Button
          variant="primary"
          disabled={!name.trim()}
          onClick={() =>
            onSubmit({
              name: name.trim(),
              description: description.trim(),
              color,
              is_active: active,
              show_in_qr: inQr,
            })
          }
        >
          Сохранить
        </Button>
      </div>
    </div>
  )
}

function GroupForm({
  initial,
  onSubmit,
  onDelete,
}: {
  initial?: ModifierGroup
  onSubmit: (payload: Record<string, unknown>) => void
  onDelete?: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [min, setMin] = useState(initial?.min_select ?? 0)
  const [max, setMax] = useState(initial?.max_select ?? 1)
  const [modifiers, setModifiers] = useState(
    initial?.modifiers.map((m) => ({ name: m.name, price_delta: m.price_delta })) ?? [{ name: '', price_delta: 0 }],
  )

  return (
    <div className="stack">
      <Field label="Название группы">
        <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <div className="grid-2">
        <Field label="Минимум">
          <Input type="number" min={0} value={min} onChange={(e) => setMin(Number(e.target.value))} />
        </Field>
        <Field label="Максимум">
          <Input type="number" min={1} value={max} onChange={(e) => setMax(Number(e.target.value))} />
        </Field>
      </div>
      <Field label="Варианты">
        <div className="stack-sm">
          {modifiers.map((m, index) => (
            <div key={index} className="row-wrap">
              <Input
                value={m.name}
                placeholder="Название"
                onChange={(e) =>
                  setModifiers((prev) =>
                    prev.map((x, i) => (i === index ? { ...x, name: e.target.value } : x)),
                  )
                }
              />
              <Input
                type="number"
                step={1}
                value={plainNumber(m.price_delta)}
                placeholder="+₽"
                onChange={(e) =>
                  setModifiers((prev) =>
                    prev.map((x, i) =>
                      i === index ? { ...x, price_delta: Math.round(Number(e.target.value) * 100) } : x,
                    ),
                  )
                }
              />
              <Button
                small
                variant="danger"
                onClick={() => setModifiers((prev) => prev.filter((_, i) => i !== index))}
              >
                ×
              </Button>
            </div>
          ))}
          <Button
            small
            onClick={() => setModifiers((prev) => [...prev, { name: '', price_delta: 0 }])}
          >
            + вариант
          </Button>
        </div>
      </Field>
      <div className="row-end">
        {onDelete ? (
          <Button variant="danger" onClick={onDelete}>
            Удалить
          </Button>
        ) : null}
        <Button
          variant="primary"
          disabled={!name.trim()}
          onClick={() =>
            onSubmit({
              name: name.trim(),
              min_select: min,
              max_select: Math.max(1, max),
              modifiers: modifiers
                .filter((m) => m.name.trim())
                .map((m) => ({ name: m.name.trim(), price_delta: m.price_delta })),
            })
          }
        >
          Сохранить
        </Button>
      </div>
    </div>
  )
}

function SettingsForm({
  settings,
  onSaved,
  onError,
}: {
  settings: MenuSettings
  onSaved: () => void
  onError: (text: string) => void
}) {
  const [draft, setDraft] = useState(settings)
  const patch = (values: Partial<MenuSettings>) => setDraft((prev) => ({ ...prev, ...values }))

  const save = async () => {
    try {
      await api.put('/admin/menu/settings', {
        title: draft.title,
        subtitle: draft.subtitle,
        currency_symbol: draft.currency_symbol,
        show_weights: draft.show_weights,
        show_calories: draft.show_calories,
        show_allergens: draft.show_allergens,
        welcome_text: draft.welcome_text,
        footer_text: draft.footer_text,
        theme_color: draft.theme_color,
      })
      onSaved()
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Ошибка сохранения')
    }
  }

  return (
    <div className="stack">
      <div className="grid-2">
        <Field label="Заголовок">
          <Input value={draft.title} onChange={(e) => patch({ title: e.target.value })} />
        </Field>
        <Field label="Подзаголовок">
          <Input value={draft.subtitle} onChange={(e) => patch({ subtitle: e.target.value })} />
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Валюта">
          <Input value={draft.currency_symbol} onChange={(e) => patch({ currency_symbol: e.target.value })} />
        </Field>
        <Field label="Цвет темы">
          <input
            type="color"
            value={draft.theme_color || '#8b1e1e'}
            onChange={(e) => patch({ theme_color: e.target.value })}
          />
        </Field>
      </div>
      <Field label="Приветствие">
        <Textarea value={draft.welcome_text} onChange={(e) => patch({ welcome_text: e.target.value })} />
      </Field>
      <Field label="Подвал">
        <Input value={draft.footer_text} onChange={(e) => patch({ footer_text: e.target.value })} />
      </Field>
      <div className="row-wrap">
        <Toggle label="Показывать вес" checked={draft.show_weights} onChange={(v) => patch({ show_weights: v })} />
        <Toggle label="Показывать калории" checked={draft.show_calories} onChange={(v) => patch({ show_calories: v })} />
        <Toggle
          label="Показывать аллергены"
          checked={draft.show_allergens}
          onChange={(v) => patch({ show_allergens: v })}
        />
      </div>
      <div className="row-end">
        <Button variant="primary" onClick={save}>
          Сохранить настройки
        </Button>
      </div>
    </div>
  )
}
