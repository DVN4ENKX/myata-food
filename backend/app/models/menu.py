from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BaseHelpers


class Category(Base):
    """Menu grouping: Супы, Напитки, Десерты..."""

    __tablename__ = "menu_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    name: Mapped[str] = mapped_column(String(120), index=True)
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(60), default="dish")
    image_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # nesting, e.g. "Напитки" -> "Кофе"
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="SET NULL"), default=None, index=True
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str | None] = mapped_column(String(20), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_qr: Mapped[bool] = mapped_column(Boolean, default=True)

    # 1C:UNF linkage
    external_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    dishes: Mapped[list[Dish]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="Dish.sort_order",
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    parent: Mapped[Category | None] = relationship(
        back_populates="children",
        remote_side="Category.id",
    )


class ModifierGroup(Base):
    """Option group attached to dishes: Размер, Добавки, Температура..."""

    __tablename__ = "modifier_groups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    name: Mapped[str] = mapped_column(String(120))
    min_select: Mapped[int] = mapped_column(Integer, default=0)
    max_select: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    modifiers: Mapped[list[Modifier]] = relationship(
        back_populates="group", cascade="all, delete-orphan", order_by="Modifier.sort_order"
    )


class Modifier(Base):
    __tablename__ = "modifiers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modifier_groups.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    price_delta: Mapped[int] = mapped_column(Integer, default=0)  # kopecks
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    external_id: Mapped[str | None] = mapped_column(String(64), default=None)

    group: Mapped[ModifierGroup] = relationship(back_populates="modifiers")


class Dish(Base):
    __tablename__ = "dishes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int] = mapped_column(Integer, default=0)  # kopecks
    old_price: Mapped[int | None] = mapped_column(Integer, default=None)

    weight_grams: Mapped[int | None] = mapped_column(Integer, default=None)
    calories: Mapped[int | None] = mapped_column(Integer, default=None)
    cooking_minutes: Mapped[int] = mapped_column(Integer, default=10)
    allergens: Mapped[str] = mapped_column(Text, default="[]")  # json list[str]
    tags: Mapped[str] = mapped_column(Text, default="[]")  # json list[str]

    image_url: Mapped[str | None] = mapped_column(String(500), default=None)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    kind: Mapped[str] = mapped_column(String(20), default="dish")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # in the menu
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)  # orderable right now
    show_in_qr: Mapped[bool] = mapped_column(Boolean, default=True)

    # 1C:UNF linkage
    external_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    integration_code: Mapped[str | None] = mapped_column(String(64), default=None)
    article: Mapped[str | None] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[Category] = relationship(back_populates="dishes")
    modifier_groups: Mapped[list[ModifierGroup]] = relationship(secondary="dish_modifier_groups")


class dish_modifier_groups(Base):  # noqa: N801
    __tablename__ = "dish_modifier_groups"

    dish_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dishes.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modifier_groups.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class MenuSettings(Base):
    """Single-row table holding menu-wide presentation settings."""

    __tablename__ = "menu_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=BaseHelpers.new_id)
    title: Mapped[str] = mapped_column(String(200), default="Меню")
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    currency_symbol: Mapped[str] = mapped_column(String(8), default="₽")
    show_weights: Mapped[bool] = mapped_column(Boolean, default=True)
    show_calories: Mapped[bool] = mapped_column(Boolean, default=False)
    show_allergens: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome_text: Mapped[str] = mapped_column(Text, default="")
    footer_text: Mapped[str] = mapped_column(Text, default="")
    theme_color: Mapped[str] = mapped_column(String(20), default="#8b1e1e")
