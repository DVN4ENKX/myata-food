from __future__ import annotations

import json
import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.menu import Category, Dish, MenuSettings, ModifierGroup
from app.schemas.menu import (
    CategoryRead,
    CategoryTree,
    DishRead,
    MenuSettingsRead,
    ModifierGroupRead,
    ModifierRead,
)


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_-]+", "-", value)
    return value.strip("-") or "item"


def unique_slug(db: Session, name: str, exclude_id: uuid.UUID | None = None) -> str:
    base = slugify(name)
    slug = base
    n = 1
    while True:
        stmt = select(Category.id).where(Category.slug == slug)
        if exclude_id:
            stmt = stmt.where(Category.id != exclude_id)
        if db.execute(stmt).first() is None:
            return slug
        n += 1
        slug = f"{base}-{n}"


def load_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def dump_json_list(values: list[str] | None) -> str:
    return json.dumps(values or [], ensure_ascii=False)


def get_or_create_menu_settings(db: Session) -> MenuSettings:
    settings = db.execute(select(MenuSettings).limit(1)).scalar_one_or_none()
    if settings:
        return settings
    settings = MenuSettings()
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------
def modifier_group_read(group: ModifierGroup) -> ModifierGroupRead:
    obj = ModifierGroupRead.model_validate(group)
    obj.modifiers = [
        ModifierRead.model_validate(m) for m in group.modifiers if m.is_active
    ]
    return obj


def dish_read(dish: Dish) -> DishRead:
    obj = DishRead.model_validate(dish)
    obj.allergens = load_json_list(dish.allergens)
    obj.tags = load_json_list(dish.tags)
    obj.category_name = dish.category.name if dish.category else ""
    obj.modifier_groups = [
        modifier_group_read(g) for g in dish.modifier_groups if g.is_active
    ]
    return obj


def category_read(category: Category) -> CategoryRead:
    obj = CategoryRead.model_validate(category)
    obj.dishes_count = len(category.dishes)
    return obj


def build_tree(categories: list[Category], dishes_by_cat: dict) -> list[CategoryTree]:
    """Nest categories by parent_id and attach dishes to the right node."""

    def to_node(cat: Category) -> CategoryTree:
        node = CategoryTree(**category_read(cat).model_dump())
        node.dishes = [dish_read(d) for d in dishes_by_cat.get(cat.id, [])]
        return node

    nodes = {c.id: to_node(c) for c in categories}
    roots: list[CategoryTree] = []
    for cat in categories:
        node = nodes[cat.id]
        if cat.parent_id and cat.parent_id in nodes:
            nodes[cat.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


def fetch_dish(db: Session, dish_id: uuid.UUID) -> Dish | None:
    return db.execute(
        select(Dish)
        .options(
            selectinload(Dish.modifier_groups).selectinload(ModifierGroup.modifiers),
            selectinload(Dish.category),
        )
        .where(Dish.id == dish_id)
    ).scalar_one_or_none()


def public_menu_payload(db: Session, *, only_available: bool = True) -> tuple[list[Category], list[Dish]]:
    stmt = (
        select(Category)
        .options(selectinload(Category.dishes))
        .where(Category.is_active.is_(True), Category.show_in_qr.is_(True))
        .order_by(Category.sort_order, Category.name)
    )
    categories = list(db.execute(stmt).scalars().unique())

    dish_stmt = (
        select(Dish)
        .options(
            selectinload(Dish.modifier_groups).selectinload(ModifierGroup.modifiers),
            selectinload(Dish.category),
        )
        .where(
            Dish.is_active.is_(True),
            Dish.show_in_qr.is_(True),
            Dish.category_id.in_([c.id for c in categories] or [uuid.UUID(int=0)]),
        )
        .order_by(Dish.sort_order, Dish.name)
    )
    if only_available:
        dish_stmt = dish_stmt.where(Dish.is_available.is_(True))
    dishes = list(db.execute(dish_stmt).scalars().unique())
    return categories, dishes


def group_dishes(dishes: list[Dish]) -> dict[Any, list[Dish]]:
    grouped: dict[Any, list[Dish]] = {}
    for dish in dishes:
        grouped.setdefault(dish.category_id, []).append(dish)
    return grouped


def menu_settings_read(settings: MenuSettings) -> MenuSettingsRead:
    return MenuSettingsRead.model_validate(settings)
