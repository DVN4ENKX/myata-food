"""1C:Enterprise (UNF) exchange.

Two directions:

* Export  - the web app produces an XML message shaped like a 1C exchange
            plan package and either saves it to disk (so the exchange service
            can pick it up over FTP/shared folder) or POSTs it to a 1C
            HTTP web service.
* Import  - 1C pushes reference data (dish prices, availability, stock flags)
            into the app, optionally creating new items.

Local objects keep a UUID; the 1C reference key lives in ``sync_map`` so the
two systems can identify each other's records without guessing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.hall import DayClose, Table
from app.models.integration import IntegrationLog, IntegrationSetting, SyncMap
from app.models.menu import Category, Dish, Modifier, ModifierGroup
from app.models.order import Order, OrderItem
from app.models.user import User

ENTITY_CATEGORY = "Справочник.НоменклатураГруппы"
ENTITY_DISH = "Справочник.Номенклатура"
ENTITY_MODIFIER = "Справочник.Номенклатура"
ENTITY_ORDER = "Документ.ЗаказКлиенту"
ENTITY_DAY_CLOSE = "Отчет.ЗакрытиеДня"
ENTITY_TABLE = "Справочник.Столы"

ENTITY_TYPES = [
    ENTITY_CATEGORY,
    ENTITY_MODIFIER,
    ENTITY_DISH,
    ENTITY_ORDER,
    ENTITY_DAY_CLOSE,
    ENTITY_TABLE,
]


def content_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_settings(db: Session) -> IntegrationSetting:
    row = db.execute(select(IntegrationSetting).limit(1)).scalar_one_or_none()
    if row is None:
        row = IntegrationSetting()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _ref(db: Session, entity_type: str, local_id: Any) -> str:
    """Stable 1C reference for a local object, created on first export.

    The session runs with autoflush=False, so the new row is flushed by hand:
    otherwise the same object exported twice in one run would get two refs.
    """
    local_key = str(local_id)
    row = db.execute(
        select(SyncMap).where(
            SyncMap.entity_type == entity_type, SyncMap.local_id == local_key
        )
    ).scalars().first()
    if row is not None:
        return row.external_id

    ref = uuid.uuid4().hex
    db.add(
        SyncMap(
            entity_type=entity_type,
            local_id=local_key,
            external_id=ref,
            last_synced_at=datetime.now(UTC),
        )
    )
    db.flush()
    return ref


def _money(kopecks: int | Decimal | None) -> str:
    if kopecks is None:
        return "0.00"
    value = Decimal(kopecks) / 100
    return f"{value:.2f}"


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _json_field(value: str | None) -> str:
    try:
        parsed = json.loads(value or "[]")
    except (ValueError, TypeError):
        parsed = []
    return ",".join(str(v) for v in parsed) if isinstance(parsed, list) else ""


# --------------------------------------------------------------------------
# node builders
# --------------------------------------------------------------------------
def category_node(db: Session, cat: Category) -> str:
    return "".join(
        [
            f"<НоменклатураГруппа {quoteattr('Ссылка')}= {_ref(db, ENTITY_CATEGORY, cat.id)} "
            f"Код={quoteattr(str(cat.external_id or ''))} "
            f"Наименование={quoteattr(cat.name)} "
            f"Родитель={quoteattr(_ref(db, ENTITY_CATEGORY, cat.parent_id) if cat.parent_id else '')} "
            f"ЭтоГруппа>true Порядок={cat.sort_order} "
            f"ВМенюQR={str(cat.show_in_qr).lower()}>",
            escape(cat.description or ""),
            "</НоменклатураГруппа>",
        ]
    )


def modifier_node(db: Session, mod: Modifier) -> str:
    return (
        f"<Номенклатура {quoteattr('Ссылка')}= {_ref(db, ENTITY_MODIFIER, mod.id)} "
        f"Код={quoteattr(mod.external_id or '')} "
        f"Наименование={quoteattr(mod.name)} "
        f"ЦенаНДС={_money(mod.price_delta)} "
        f"ВидНДС='НДС20' Услуга=true "
        f"Активен={str(mod.is_active).lower()}/>"
    )


def dish_node(db: Session, dish: Dish) -> str:
    return "".join(
        [
            f"<Номенклатура {quoteattr('Ссылка')}= {_ref(db, ENTITY_DISH, dish.id)} "
            f"Код={quoteattr(dish.article or dish.integration_code or '')} "
            f"Наименование={quoteattr(dish.name)} "
            f"Родитель={quoteattr(_ref(db, ENTITY_CATEGORY, dish.category_id))} "
            f"Артикул={quoteattr(dish.article or '')} "
            f"ЦенаНДС={_money(dish.price)} "
            f"СтараяЦенаНДС={_money(dish.old_price)} "
            f"ВидНДС='НДС20' "
            f"Вес={dish.weight_grams or 0} "
            f"Калории={dish.calories or 0} "
            f"ВремяПриготовления={dish.cooking_minutes} "
            f"Аллергены={quoteattr(_json_field(dish.allergens))} "
            f"Теги={quoteattr(_json_field(dish.tags))} "
            f"Картинка={quoteattr(dish.image_url or '')} "
            f"ВМеню={str(dish.is_active).lower()} "
            f"Доступно={str(dish.is_available).lower()} "
            f"ПоказыватьВQR={str(dish.show_in_qr).lower()}>",
            escape(dish.description or ""),
            "</Номенклатура>",
        ]
    )


def order_node(db: Session, order: Order) -> str:
    rows = []
    for item in order.items:
        modifiers = "".join(
            f"<Модификатор Наименование={quoteattr(m.name)} Цена={_money(m.price_delta)}/>"
            for m in item.modifiers
        )
        rows.append(
            f"<Товар Наименование={quoteattr(item.dish_name)} "
            f"Количество={item.quantity} "
            f"Цена={_money(int(item.price * 100))} "
            f"Комментарий={quoteattr(item.comment or '')}>{modifiers}</Товар>"
        )
    return "".join(
        [
            f"<ЗаказКлиенту {quoteattr('Ссылка')}= {_ref(db, ENTITY_ORDER, order.id)} "
            f"Номер={quoteattr(order.order_number)} "
            f"Дата={_dt(order.created_at)} "
            f"Статус={quoteattr(order.status)} "
            f"Источник={quoteattr(order.source)} "
            f"Стол={quoteattr(_ref(db, ENTITY_TABLE, order.table_id) if order.table_id else '')} "
            f"Гостей={order.guests_count} "
            f"Клиент={quoteattr(order.client_name or '')} "
            f"Итого={_money(int((order.total_amount or 0) * 100))} "
            f"Комментарий={quoteattr(order.guest_comment or '')}>",
            "".join(rows),
            "</ЗаказКлиенту>",
        ]
    )


def day_close_node(db: Session, close: DayClose) -> str:
    return (
        f"<ЗакрытиеДня {quoteattr('Ссылка')}= {_ref(db, ENTITY_DAY_CLOSE, close.id)} "
        f"Дата={quoteattr(close.business_date)} "
        f"Гостей={close.guests_total} "
        f"Заказов={close.orders_total} "
        f"Выручка={_money(int((close.revenue_total or 0) * 100))} "
        f"Время={_dt(close.closed_at)} "
        f"Комментарий={quoteattr(close.notes or '')}/>"
    )


def table_node(db: Session, table: Table) -> str:
    return (
        f"<Стол {quoteattr('Ссылка')}= {_ref(db, ENTITY_TABLE, table.id)} "
        f"Код={quoteattr(table.external_id or table.name)} "
        f"Наименование={quoteattr(table.name)} "
        f"Мест={table.seats} "
        f"Активен={str(table.is_active).lower()}/>"
    )


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------
def build_package(
    db: Session,
    *,
    categories: bool = True,
    dishes: bool = True,
    modifiers: bool = True,
    orders: bool = True,
    day_closes: bool = True,
    order_statuses: list[str] | None = None,
    since: datetime | None = None,
    include_inactive: bool = True,
) -> dict[str, list[str]]:
    nodes: dict[str, list[str]] = {key: [] for key in ENTITY_TYPES}

    if categories:
        for cat in db.execute(select(Category).order_by(Category.sort_order)).scalars().unique():
            nodes[ENTITY_CATEGORY].append(category_node(db, cat))

    if modifiers:
        for group in db.execute(select(ModifierGroup)).scalars().unique():
            for mod in group.modifiers:
                if mod.is_active or include_inactive:
                    nodes[ENTITY_MODIFIER].append(modifier_node(db, mod))

    if dishes:
        stmt = select(Dish)
        if not include_inactive:
            stmt = stmt.where(Dish.is_active.is_(True))
        for dish in db.execute(stmt).scalars().unique():
            nodes[ENTITY_DISH].append(dish_node(db, dish))

    for table in db.execute(select(Table)).scalars().unique():
        nodes[ENTITY_TABLE].append(table_node(db, table))

    if orders:
        stmt = select(Order).options(selectinload(Order.items).selectinload(OrderItem.modifiers))
        if order_statuses:
            stmt = stmt.where(Order.status.in_(order_statuses))
        if since:
            stmt = stmt.where(Order.created_at >= since)
        for order in db.execute(stmt).scalars().unique():
            nodes[ENTITY_ORDER].append(order_node(db, order))

    if day_closes:
        for close in db.execute(select(DayClose)).scalars().unique():
            nodes[ENTITY_DAY_CLOSE].append(day_close_node(db, close))

    return nodes


def to_xml(
    nodes: dict[str, list[str]],
    cfg: IntegrationSetting,
    *,
    exchange_name: str,
) -> str:
    body = []
    for entity, items in nodes.items():
        if not items:
            continue
        body.append(f'<Группа Имя={quoteattr(entity)} Количество={len(items)}>')
        body.extend(items)
        body.append("</Группа>")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<СообщениеОбмена Версия="1.0" '
        f'ПланОбмена={quoteattr(cfg.exchange_plan or exchange_name)} '
        f'ОтправкаПриложения="0" '
        f'Ид={quoteattr(uuid.uuid4().hex)} '
        f'ДатаОтправки={_dt(datetime.now(UTC))}>'
        f"<Отправитель>1C</Отправитель>"
        f'<Параметры Имя="Организация" Значение={quoteattr(cfg.org_ref or "")}/>'
        f'<Параметры Имя="ВидЦены" Значение={quoteattr(cfg.price_type_ref or "")}/>'
        + "".join(body)
        + "</СообщениеОбмена>"
    )


def run_export(
    db: Session,
    *,
    categories: bool = True,
    dishes: bool = True,
    modifiers: bool = True,
    orders: bool = True,
    day_closes: bool = True,
    order_statuses: list[str] | None = None,
    since: datetime | None = None,
    user: User | None = None,
    deliver: bool = False,
) -> dict:
    cfg = get_settings(db)
    started = datetime.now(UTC)
    exchange_name = f"Обмен_{started.strftime('%Y%m%d_%H%M%S')}"

    log = IntegrationLog(
        direction="export",
        status="pending",
        file_name=f"{exchange_name}.xml",
        started_at=started,
        user_id=user.id if user else None,
    )
    db.add(log)
    db.flush()

    try:
        nodes = build_package(
            db,
            categories=categories,
            dishes=dishes,
            modifiers=modifiers,
            orders=orders,
            day_closes=day_closes,
            order_statuses=order_statuses,
            since=since,
        )
        xml = to_xml(nodes, cfg, exchange_name=exchange_name)

        for item in nodes.values():
            log.entities_total += len(item)
            log.entities_success += len(item)

        log.payload_preview = xml[:8000]

        if deliver:
            log.message = "Отправлено в веб-сервис 1С"
        else:
            path = _exports_dir() / log.file_name
            path.write_text(xml, encoding="utf-8")
            log.message = f"Файл сохранён: {path.name}"

        log.status = "success"
        log.finished_at = datetime.now(UTC)
        cfg.last_export_at = log.finished_at
        db.commit()
        return {
            "log": log,
            "xml": xml,
            "file_name": log.file_name,
        }
    except Exception as exc:  # noqa: BLE001 - surfaced in the log table
        log.status = "error"
        log.message = str(exc)[:2000]
        log.finished_at = datetime.now(UTC)
        db.commit()
        return {"log": log, "xml": "", "file_name": None, "error": str(exc)}


def _exports_dir():
    from app.core.config import settings

    path = settings.exports_path
    path.mkdir(parents=True, exist_ok=True)
    return path


async def deliver_to_1c(db: Session, url: str, login: str, password: str, xml: str) -> str:
    """POST the package to a 1C HTTP web service."""
    import httpx

    auth = (login, password) if login else None
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            content=xml.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
            auth=auth,
        )
        response.raise_for_status()
        return response.text


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------
def apply_incoming(
    db: Session,
    items: list[dict],
    *,
    create_missing: bool = True,
) -> dict:
    """Apply a 1C push. Each item: {entity, external_id, name, price, is_available}."""
    stats = {"accepted": 0, "updated": 0, "created": 0, "errors": []}
    now = datetime.now(UTC)

    for raw in items:
        try:
            entity = str(raw.get("entity") or ENTITY_DISH)
            external_id = str(raw.get("external_id") or "").strip()
            if not external_id:
                stats["errors"].append("пустой external_id")
                continue

            stats["accepted"] += 1

            if entity == ENTITY_DISH:
                link = db.execute(
                    select(SyncMap).where(
                        SyncMap.entity_type == ENTITY_DISH, SyncMap.external_id == external_id
                    )
                ).scalar_one_or_none()

                if link is not None:
                    dish = db.get(Dish, uuid.UUID(link.local_id))
                    if dish is not None:
                        _apply_dish_fields(dish, raw)
                        dish.external_id = external_id
                        stats["updated"] += 1
                        continue

                dish = db.execute(
                    select(Dish).where(Dish.external_id == external_id)
                ).scalar_one_or_none()
                if dish is not None:
                    _apply_dish_fields(dish, raw)
                    stats["updated"] += 1
                    continue

                if not create_missing:
                    continue

                category = _ensure_default_category(db)
                dish = Dish(
                    category_id=category.id,
                    name=str(raw.get("name") or "Новый товар"),
                    price=int(Decimal(str(raw.get("price") or 0)) * 100),
                    external_id=external_id,
                )
                db.add(dish)
                db.flush()
                _apply_dish_fields(dish, raw)
                db.add(
                    SyncMap(
                        entity_type=ENTITY_DISH,
                        local_id=str(dish.id),
                        external_id=external_id,
                        last_synced_at=now,
                    )
                )
                stats["created"] += 1
            elif entity == ENTITY_CATEGORY:
                link = db.execute(
                    select(SyncMap).where(
                        SyncMap.entity_type == ENTITY_CATEGORY,
                        SyncMap.external_id == external_id,
                    )
                ).scalar_one_or_none()
                if link is not None:
                    cat = db.get(Category, uuid.UUID(link.local_id))
                    if cat is not None:
                        cat.name = str(raw.get("name") or cat.name)
                        cat.external_id = external_id
                        stats["updated"] += 1
                elif create_missing:
                    cat = Category(
                        name=str(raw.get("name") or "Группа из 1С"),
                        slug=f"onec-{external_id[:8]}",
                        external_id=external_id,
                    )
                    db.add(cat)
                    db.flush()
                    db.add(
                        SyncMap(
                            entity_type=ENTITY_CATEGORY,
                            local_id=str(cat.id),
                            external_id=external_id,
                            last_synced_at=now,
                        )
                    )
                    stats["created"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not kill the batch
            stats["errors"].append(str(exc)[:300])

    db.commit()
    return stats


def _apply_dish_fields(dish: Dish, raw: dict) -> None:
    if "name" in raw and raw["name"]:
        dish.name = str(raw["name"])[:200]
    if "price" in raw and raw["price"] is not None:
        dish.price = int(Decimal(str(raw["price"])) * 100)
    if "description" in raw:
        dish.description = str(raw["description"])
    if "is_available" in raw:
        dish.is_available = bool(raw["is_available"])
    if "article" in raw:
        dish.article = str(raw["article"])[:64] or None
    if "integration_code" in raw:
        dish.integration_code = str(raw["integration_code"])[:64] or None


def _ensure_default_category(db: Session) -> Category:
    cat = db.execute(select(Category).order_by(Category.sort_order).limit(1)).scalar_one_or_none()
    if cat is None:
        cat = Category(name="Товары из 1С", slug="onec-import", is_active=True)
        db.add(cat)
        db.flush()
    return cat
