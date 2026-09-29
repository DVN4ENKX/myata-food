from __future__ import annotations

import json
import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[int, Field(ge=0, le=100_000_000)]


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# categories (Супы, Напитки, ...)
# --------------------------------------------------------------------------
class CategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    icon: str = "dish"
    image_url: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None
    sort_order: int = 0
    color: str | None = None
    is_active: bool = True
    show_in_qr: bool = True
    external_id: str | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    icon: str | None = None
    image_url: str | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int | None = None
    color: str | None = None
    is_active: bool | None = None
    show_in_qr: bool | None = None
    external_id: str | None = None


class CategoryRead(ORMBase, CategoryBase):
    id: uuid.UUID
    slug: str
    dishes_count: int = 0


# --------------------------------------------------------------------------
# modifiers
# --------------------------------------------------------------------------
class ModifierBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_delta: int = 0
    is_default: bool = False
    sort_order: int = 0
    is_active: bool = True
    external_id: str | None = None


class ModifierRead(ORMBase, ModifierBase):
    id: uuid.UUID


class ModifierGroupBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    min_select: int = Field(default=0, ge=0)
    max_select: int = Field(default=1, ge=1)
    sort_order: int = 0
    is_active: bool = True


class ModifierGroupCreate(ModifierGroupBase):
    modifiers: list[ModifierBase] = []


class ModifierGroupRead(ORMBase, ModifierGroupBase):
    id: uuid.UUID
    modifiers: list[ModifierRead] = []


# --------------------------------------------------------------------------
# dishes
# --------------------------------------------------------------------------
class DishBase(BaseModel):
    category_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    price: Money = 0
    old_price: Money | None = None
    weight_grams: int | None = Field(default=None, ge=0, le=100_000)
    calories: int | None = Field(default=None, ge=0, le=100_000)
    cooking_minutes: int = Field(default=10, ge=0, le=1440)
    allergens: list[str] = []
    tags: list[str] = []
    image_url: str | None = Field(default=None, max_length=500)
    sort_order: int = 0
    kind: str = "dish"
    is_active: bool = True
    is_available: bool = True
    show_in_qr: bool = True
    external_id: str | None = None
    integration_code: str | None = None
    article: str | None = None
    modifier_group_ids: list[uuid.UUID] = []


class DishCreate(DishBase):
    pass


class DishUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    price: Money | None = None
    old_price: Money | None = None
    weight_grams: int | None = Field(default=None, ge=0, le=100_000)
    calories: int | None = Field(default=None, ge=0, le=100_000)
    cooking_minutes: int | None = Field(default=None, ge=0, le=1440)
    allergens: list[str] | None = None
    tags: list[str] | None = None
    image_url: str | None = None
    sort_order: int | None = None
    kind: str | None = None
    is_active: bool | None = None
    is_available: bool | None = None
    show_in_qr: bool | None = None
    external_id: str | None = None
    integration_code: str | None = None
    article: str | None = None
    modifier_group_ids: list[uuid.UUID] | None = None


class DishRead(ORMBase):
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str = ""
    name: str
    description: str = ""
    price: int
    old_price: int | None = None
    weight_grams: int | None = None
    calories: int | None = None
    cooking_minutes: int = 10
    allergens: list[str] = []
    tags: list[str] = []
    image_url: str | None = None
    sort_order: int = 0
    kind: str = "dish"
    is_active: bool = True
    is_available: bool = True
    show_in_qr: bool = True
    external_id: str | None = None
    integration_code: str | None = None
    article: str | None = None
    modifier_groups: list[ModifierGroupRead] = []

    @field_validator("allergens", "tags", mode="before")
    @classmethod
    def _parse_json_list(cls, v: object) -> list[str]:
        """The columns hold JSON text; accept either form."""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except (ValueError, TypeError):
                return []
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        return []


class CategoryTree(CategoryRead):
    children: list[CategoryTree] = []
    dishes: list[DishRead] = []


# --------------------------------------------------------------------------
# menu-wide settings
# --------------------------------------------------------------------------
class MenuSettingsRead(ORMBase):
    id: uuid.UUID
    title: str
    subtitle: str
    currency_symbol: str
    show_weights: bool
    show_calories: bool
    show_allergens: bool
    welcome_text: str
    footer_text: str
    theme_color: str


class MenuSettingsUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    currency_symbol: str | None = Field(default=None, max_length=8)
    show_weights: bool | None = None
    show_calories: bool | None = None
    show_allergens: bool | None = None
    welcome_text: str | None = None
    footer_text: str | None = None
    theme_color: str | None = None


class PublicMenu(BaseModel):
    venue: str
    table_name: str
    table_number: str
    hall_name: str
    settings: MenuSettingsRead
    categories: list[CategoryTree]
    dishes_count: int


class ReorderItem(BaseModel):
    id: uuid.UUID
    sort_order: int


class ReorderRequest(BaseModel):
    items: list[ReorderItem] = Field(min_length=1, max_length=500)


# --------------------------------------------------------------------------
# availability ("стоп-лист")
# --------------------------------------------------------------------------
class AvailabilitySet(BaseModel):
    is_available: bool = True


class BulkAvailability(BaseModel):
    dish_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    is_available: bool = False
