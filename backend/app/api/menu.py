from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, MenuEditor, MenuViewer
from app.models.menu import Category, Dish, Modifier, ModifierGroup
from app.schemas.menu import (
    AvailabilitySet,
    BulkAvailability,
    CategoryCreate,
    CategoryRead,
    CategoryTree,
    CategoryUpdate,
    DishCreate,
    DishRead,
    DishUpdate,
    MenuSettingsRead,
    MenuSettingsUpdate,
    ModifierGroupCreate,
    ModifierGroupRead,
    ReorderRequest,
)
from app.services.menu import (
    build_tree,
    category_read,
    dish_read,
    dump_json_list,
    fetch_dish,
    get_or_create_menu_settings,
    group_dishes,
    menu_settings_read,
    unique_slug,
)
from app.services.ws import publish_menu_changed

router = APIRouter(prefix="/admin/menu", tags=["admin:menu"])


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------
@router.get("/settings", response_model=MenuSettingsRead)
def read_settings(_: MenuViewer, db: DbSession) -> MenuSettingsRead:
    return menu_settings_read(get_or_create_menu_settings(db))


@router.put("/settings", response_model=MenuSettingsRead)
def update_settings(
    payload: MenuSettingsUpdate, _: MenuEditor, db: DbSession
) -> MenuSettingsRead:
    row = get_or_create_menu_settings(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return menu_settings_read(row)


# --------------------------------------------------------------------------
# categories
# --------------------------------------------------------------------------
@router.get("/categories", response_model=list[CategoryRead])
def list_categories(
    _: MenuViewer,
    db: DbSession,
    include_inactive: bool = Query(True),
) -> list[CategoryRead]:
    stmt = select(Category)
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    rows = list(db.execute(stmt.order_by(Category.sort_order, Category.name)).scalars().unique())
    return [category_read(c) for c in rows]


@router.get("/categories/tree", response_model=list[CategoryTree])
def categories_tree(_: MenuViewer, db: DbSession) -> list[CategoryTree]:
    from app.services.menu import public_menu_payload

    categories, dishes = public_menu_payload(db, only_available=False)
    return build_tree(categories, group_dishes(dishes))


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, _: MenuEditor, db: DbSession) -> CategoryRead:
    cat = Category(
        **payload.model_dump(exclude={"parent_id"}),
        slug=unique_slug(db, payload.name),
        parent_id=payload.parent_id,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return category_read(cat)


@router.patch("/categories/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, _: MenuEditor, db: DbSession
) -> CategoryRead:
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != cat.name:
        cat.slug = unique_slug(db, data["name"], exclude_id=cat.id)
    for field, value in data.items():
        setattr(cat, field, value)
    db.commit()
    db.refresh(cat)
    return category_read(cat)


@router.delete("/categories/{category_id}")
def delete_category(category_id: uuid.UUID, _: MenuEditor, db: DbSession) -> dict:
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    dish_count = db.execute(
        select(func.count(Dish.id)).where(Dish.category_id == category_id)
    ).scalar()
    if dish_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"В категории есть блюда ({dish_count}). Перенесите их или скройте категорию.",
        )
    db.delete(cat)
    db.commit()
    return {"ok": True}


@router.post("/categories/reorder")
def reorder_categories(payload: ReorderRequest, _: MenuEditor, db: DbSession) -> dict:
    for row in payload.items:
        cat = db.get(Category, row.id)
        if cat:
            cat.sort_order = row.sort_order
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# modifier groups
# --------------------------------------------------------------------------
@router.get("/modifier-groups", response_model=list[ModifierGroupRead])
def list_modifier_groups(_: MenuViewer, db: DbSession) -> list[ModifierGroupRead]:
    from app.services.menu import modifier_group_read

    rows = db.execute(
        select(ModifierGroup).order_by(ModifierGroup.sort_order, ModifierGroup.name)
    ).scalars().unique()
    return [modifier_group_read(g) for g in rows]


@router.post(
    "/modifier-groups", response_model=ModifierGroupRead, status_code=status.HTTP_201_CREATED
)
def create_modifier_group(
    payload: ModifierGroupCreate, _: MenuEditor, db: DbSession
) -> ModifierGroupRead:
    group = ModifierGroup(
        name=payload.name,
        min_select=payload.min_select,
        max_select=payload.max_select,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    for m in payload.modifiers:
        group.modifiers.append(Modifier(**m.model_dump()))
    db.add(group)
    db.commit()
    db.refresh(group)
    from app.services.menu import modifier_group_read

    return modifier_group_read(group)


@router.delete("/modifier-groups/{group_id}")
def delete_modifier_group(group_id: uuid.UUID, _: MenuEditor, db: DbSession) -> dict:
    group = db.get(ModifierGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    db.delete(group)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# dishes
# --------------------------------------------------------------------------
@router.get("/dishes", response_model=list[DishRead])
def list_dishes(
    _: MenuViewer,
    db: DbSession,
    category_id: uuid.UUID | None = None,
    search: str | None = Query(default=None, max_length=100),
    include_inactive: bool = Query(True),
) -> list[DishRead]:
    from sqlalchemy.orm import selectinload

    stmt = select(Dish).options(
        selectinload(Dish.category),
        selectinload(Dish.modifier_groups).selectinload(ModifierGroup.modifiers),
    )
    if category_id:
        stmt = stmt.where(Dish.category_id == category_id)
    if not include_inactive:
        stmt = stmt.where(Dish.is_active.is_(True))
    rows = list(
        db.execute(stmt.order_by(Dish.sort_order, Dish.name)).scalars().unique()
    )
    if search:
        # SQLite's LIKE/ILIKE only folds ASCII, so filtering in Python keeps
        # case-insensitive search working for Cyrillic names on every backend.
        needle = search.strip().casefold()
        if needle:
            rows = [d for d in rows if needle in d.name.casefold()]
    return [dish_read(d) for d in rows]


@router.get("/dishes/{dish_id}", response_model=DishRead)
def get_dish(dish_id: uuid.UUID, _: MenuViewer, db: DbSession) -> DishRead:
    dish = fetch_dish(db, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")
    return dish_read(dish)


@router.post("/dishes", response_model=DishRead, status_code=status.HTTP_201_CREATED)
def create_dish(payload: DishCreate, _: MenuEditor, db: DbSession) -> DishRead:
    if db.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=400, detail="Категория не найдена")

    data = payload.model_dump(exclude={"allergens", "tags", "modifier_group_ids"})
    dish = Dish(
        **data,
        allergens=dump_json_list(payload.allergens),
        tags=dump_json_list(payload.tags),
    )
    db.add(dish)
    db.flush()

    if payload.modifier_group_ids:
        groups = list(
            db.execute(
                select(ModifierGroup).where(ModifierGroup.id.in_(payload.modifier_group_ids))
            ).scalars()
        )
        dish.modifier_groups = groups

    db.commit()
    created = fetch_dish(db, dish.id)
    db.refresh(created)
    publish_menu_changed()
    return dish_read(created)


@router.patch("/dishes/{dish_id}", response_model=DishRead)
def update_dish(
    dish_id: uuid.UUID, payload: DishUpdate, _: MenuEditor, db: DbSession
) -> DishRead:
    dish = fetch_dish(db, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")

    data = payload.model_dump(exclude_unset=True)
    if "allergens" in data:
        dish.allergens = dump_json_list(data.pop("allergens"))
    if "tags" in data:
        dish.tags = dump_json_list(data.pop("tags"))
    group_ids = data.pop("modifier_group_ids", None)
    for field, value in data.items():
        setattr(dish, field, value)

    if group_ids is not None:
        dish.modifier_groups = list(
            db.execute(select(ModifierGroup).where(ModifierGroup.id.in_(group_ids))).scalars()
        )

    db.commit()
    updated = fetch_dish(db, dish_id)
    db.refresh(updated)
    publish_menu_changed()
    return dish_read(updated)


@router.post("/dishes/{dish_id}/availability")
def set_availability(
    dish_id: uuid.UUID, payload: AvailabilitySet, _: MenuEditor, db: DbSession
) -> dict:
    dish = db.get(Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")
    dish.is_available = payload.is_available
    db.commit()
    publish_menu_changed()
    return {"ok": True, "is_available": dish.is_available}


@router.post("/dishes/bulk-availability")
def bulk_availability(
    payload: BulkAvailability, _: MenuEditor, db: DbSession
) -> dict:
    """Stop-the-line switch when an ingredient runs out."""

    if not payload.dish_ids:
        return {"ok": True, "updated": 0}
    found = list(
        db.execute(select(Dish).where(Dish.id.in_(payload.dish_ids))).scalars().unique()
    )
    for d in found:
        d.is_available = payload.is_available
    db.commit()
    publish_menu_changed()
    return {"ok": True, "updated": len(found)}


@router.delete("/dishes/{dish_id}")
def delete_dish(dish_id: uuid.UUID, _: MenuEditor, db: DbSession) -> dict:
    dish = db.get(Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")
    db.delete(dish)
    db.commit()
    publish_menu_changed()
    return {"ok": True}


@router.post("/dishes/reorder")
def reorder_dishes(payload: ReorderRequest, _: MenuEditor, db: DbSession) -> dict:
    for row in payload.items:
        dish = db.get(Dish, row.id)
        if dish:
            dish.sort_order = row.sort_order
    db.commit()
    publish_menu_changed()
    return {"ok": True}


@router.get("/stats")
def menu_stats(_: MenuViewer, db: DbSession) -> dict:
    total = db.execute(select(func.count(Dish.id))).scalar()
    available = db.execute(
        select(func.count(Dish.id)).where(Dish.is_available.is_(True), Dish.is_active.is_(True))
    ).scalar()
    categories = db.execute(select(func.count(Category.id))).scalar()
    hidden = db.execute(
        select(func.count(Category.id)).where(Category.is_active.is_(False))
    ).scalar()
    avg = db.execute(
        select(func.coalesce(func.avg(Dish.price), 0)).where(Dish.is_active.is_(True))
    ).scalar()
    return {
        "dishes_total": total,
        "dishes_available": available,
        "dishes_unavailable": total - available,
        "categories_total": categories,
        "categories_hidden": hidden,
        "avg_price": int(avg or 0),
    }


