from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.base import OrderStatus
from app.models.hall import Table, TableSession
from app.models.menu import Dish, Modifier
from app.models.order import Order, OrderItem, OrderItemModifier
from app.schemas.order import CartItem, OrderItemRead, OrderRead

ACTIVE_STATUSES = (
    OrderStatus.new,
    OrderStatus.in_progress,
    OrderStatus.ready,
    OrderStatus.served,
)

KITCHEN_FLOW = {
    OrderStatus.new: OrderStatus.in_progress,
    OrderStatus.in_progress: OrderStatus.ready,
    OrderStatus.ready: OrderStatus.served,
}


def next_order_number(db: Session) -> str:
    today = datetime.now(UTC).strftime("%y%m%d")
    prefix = f"{today}-"
    last = db.execute(
        select(Order.order_number).where(Order.order_number.like(f"{prefix}%")).order_by(
            Order.order_number.desc()
        ).limit(1)
    ).scalar_one_or_none()
    if not last:
        return f"{prefix}001"
    try:
        n = int(last.rsplit("-", 1)[1]) + 1
    except (IndexError, ValueError):
        n = 1
    return f"{prefix}{n:03d}"


def _resolve_modifiers(db: Session, item: CartItem) -> list[tuple[Modifier, str, int]]:
    """Map client-sent modifier ids onto real rows; drop anything unknown.

    Names and price deltas sent by the client are ignored on purpose: a guest
    must not be able to invent a modifier with a negative price.
    """
    ids = [m.modifier_id for m in item.modifiers]
    rows: dict[uuid.UUID, Modifier] = {}
    if ids:
        for mod in db.execute(select(Modifier).where(Modifier.id.in_(ids))).scalars():
            rows[mod.id] = mod

    out: list[tuple[Modifier, str, int]] = []
    seen: set[uuid.UUID] = set()
    for entry in item.modifiers:
        mod = rows.get(entry.modifier_id)
        if mod is None or mod.id in seen:
            continue
        seen.add(mod.id)
        out.append((mod, mod.name, mod.price_delta))
    return out


def build_items(db: Session, cart_items: list[CartItem]) -> list[tuple[Dish, int, str, list, int]]:
    """(dish, qty, comment, modifiers, line_total_kopecks) with server-side prices."""
    dish_ids = {ci.dish_id for ci in cart_items}
    dishes: dict[uuid.UUID, Dish] = {}
    if dish_ids:
        for d in db.execute(
            select(Dish).where(Dish.id.in_(dish_ids), Dish.is_active.is_(True))
        ).scalars():
            dishes[d.id] = d

    result = []
    for ci in cart_items:
        dish = dishes.get(ci.dish_id)
        if dish is None:
            continue
        if not dish.is_available:
            continue
        mods = _resolve_modifiers(db, ci)
        unit = dish.price + sum(price for _, _, price in mods)
        result.append((dish, ci.quantity, ci.comment, mods, unit * ci.quantity))
    return result


def recalc_total(db: Session, order: Order) -> Decimal:
    items = db.execute(
        select(OrderItem).options(selectinload(OrderItem.modifiers)).where(
            OrderItem.order_id == order.id
        )
    ).scalars().unique()
    total = Decimal(0)
    for item in items:
        extra = sum((m.price_delta for m in item.modifiers), Decimal(0))
        total += (item.price + extra) * item.quantity
    order.total_amount = total
    return total


def create_order(
    db: Session,
    cart_items: list[CartItem],
    *,
    table: Table | None = None,
    table_session: TableSession | None = None,
    source: str = "qr",
    created_by_user_id: uuid.UUID | None = None,
    guest_comment: str = "",
    guests_count: int = 1,
    client_name: str = "",
) -> Order | None:
    built = build_items(db, cart_items)
    if not built:
        return None

    order = Order(
        order_number=next_order_number(db),
        table_id=table.id if table else None,
        table_session_id=table_session.id if table_session else None,
        created_by_user_id=created_by_user_id,
        status=OrderStatus.new,
        source=source,
        guest_comment=guest_comment,
        guests_count=guests_count,
        client_name=client_name,
    )
    db.add(order)
    db.flush()

    for dish, qty, comment, mods, _line in built:
        item = OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_name=dish.name,
            price=Decimal(dish.price) / 100,
            quantity=qty,
            comment=comment,
            cooking_minutes=dish.cooking_minutes,
            status="new",
        )
        for mod, name, price_delta in mods:
            item.modifiers.append(
                OrderItemModifier(
                    modifier_id=mod.id,
                    name=name,
                    price_delta=Decimal(price_delta) / 100,
                )
            )
        db.add(item)

    # The total comes from the freshly built rows: recalc_total() would query
    # the DB, and pending items are not visible there before the flush.
    # dish.price / price_delta are kopecks, so convert here exactly like the
    # item rows above - otherwise total_amount ends up 100x too large and every
    # report that reads it is inflated to match.
    order.total_amount = sum(
        ((Decimal(dish.price) + sum(Decimal(p) for _, _, p in mods)) * qty) / 100
        for dish, qty, _, mods, _ in built
    )
    db.commit()
    db.refresh(order)
    return order


def load_order(db: Session, order_id: uuid.UUID) -> Order | None:
    return db.execute(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.modifiers),
            selectinload(Order.table),
        )
        .where(Order.id == order_id)
    ).scalar_one_or_none()


def order_read(order: Order) -> OrderRead:
    obj = OrderRead.model_validate(order)
    obj.table_name = order.table.name if order.table else None
    items: list[OrderItemRead] = []
    for it in order.items:
        item = OrderItemRead.model_validate(it)
        extra = sum((m.price_delta for m in item.modifiers), Decimal(0))
        item.line_total = (item.price + extra) * item.quantity
        items.append(item)
    obj.items = items
    return obj


def open_orders_for_table(db: Session, table_id: uuid.UUID) -> list[Order]:
    return list(
        db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.table_id == table_id, Order.status.in_(ACTIVE_STATUSES))
            .order_by(Order.created_at)
        ).scalars().unique()
    )


def close_table_orders(db: Session, table_id: uuid.UUID) -> int:
    orders = open_orders_for_table(db, table_id)
    now = datetime.now(UTC)
    for order in orders:
        order.status = OrderStatus.closed
        order.closed_at = now
    return len(orders)


def is_open(status: str) -> bool:
    return status in tuple(s.value for s in ACTIVE_STATUSES)


def max_wait_minutes(orders: list[Order], now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    if not orders:
        return 0
    oldest = min(o.created_at for o in orders)
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    return int((now - oldest).total_seconds() // 60)
