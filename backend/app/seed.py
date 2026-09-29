from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Role
from app.models.hall import Hall, Reservation, Table
from app.models.integration import IntegrationSetting
from app.models.menu import (
    Category,
    Dish,
    MenuSettings,
    Modifier,
    ModifierGroup,
    dish_modifier_groups,
)
from app.models.user import AppSetting, User

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
MANAGER_USERNAME = "manager"
MANAGER_PASSWORD = "manager123"
WAITER_USERNAME = "waiter"
WAITER_PASSWORD = "waiter123"

# (name, description, price_rub, weight, kcal, minutes, allergens, tags)
MENU_SEED: list[tuple[str, str, list[tuple[str, str, int, int, int, int, list[str], list[str]]]]] = [
    (
        "Супы",
        "Горячие и холодные супы дня",
        [
            ("Борщ с говядиной", "Классический борщ с чесночными пампушками", 390, 300, 180, 15, ["глютен", "молоко"], ["хит"]),
            ("Крем-суп из тыквы", "Нежный тыквенный крем с кокосовыми сливками", 350, 280, 150, 12, ["молоко"], ["веган"]),
            ("Солянка мясная", "Острый мясной сборный суп с соленьями", 420, 320, 240, 18, [], ["острое"]),
            ("Уха из лосося", "Наваристый суп из лосося с укропом", 520, 350, 210, 15, ["рыба"], ["хит"]),
        ],
    ),
    (
        "Салаты",
        "Свежие овощи и тёплые закуски",
        [
            ("Цезарь с курицей", "Романо, пармезан, соус цезарь, гренки", 490, 280, 340, 10, ["молоко", "глютен", "яйцо"], ["хит"]),
            ("Греческий", "Овощи, фета, маслины, орегано", 420, 260, 250, 8, ["молоко"], ["веган", "свежее"]),
            ("Винегрет с грибами", "Классический винегрет с жареными грибами", 380, 240, 210, 9, ["горчица"], ["постное"]),
            ("Салат с лососем", "Слабосолёный лосось, авокадо, микс салатов", 620, 300, 380, 12, ["рыба"], ["фирменное"]),
        ],
    ),
    (
        "Горячее",
        "Основные блюда из свежих продуктов",
        [
            ("Паста карбонара", "Спагетти, бекон, яйцо, пармезан", 560, 320, 620, 18, ["глютен", "яйцо", "молоко"], ["хит"]),
            ("Стейк из говядины", "Говядина зернового откорма 250 г, соус демиглас", 1850, 250, 780, 25, [], ["мясо"]),
            ("Курица в сливочном соусе", "Филе курицы, шпинат, сливки", 690, 300, 520, 20, ["молоко"], []),
            ("Рыба по-французски", "Треска в сливках с сыром", 720, 300, 560, 22, ["рыба", "молоко", "глютен"], []),
            ("Долма", "Виноградные листья с говядиной и рисом", 480, 260, 400, 20, [], ["постное"]),
        ],
    ),
    (
        "Пицца",
        "На тонком тесте, 30 см",
        [
            ("Маргарита", "Томатный соус, моцарелла, базилик", 590, 450, 780, 15, ["молоко", "глютен"], ["вегетарианское"]),
            ("Четыре сыра", "Моцарелла, пармезан, гауда, чеддер", 690, 450, 920, 15, ["молоко", "глютен"], []),
            ("Пепперони", "Пепперони, моцарелла, оливки, халапеньо", 720, 460, 1010, 16, ["молоко", "глютен"], ["острое"]),
            ("Маргерита с грибами", "Шампиньоны, моцарелла, тимьян", 660, 450, 850, 15, ["молоко", "глютен"], ["вегетарианское"]),
        ],
    ),
    (
        "Напитки",
        "Холодные и горячие напитки",
        [
            ("Эспрессо", "Обжарка недели, 30 мл", 180, 30, 5, 3, [], ["кофе"]),
            ("Капучино", "Эспрессо, молоко, пена", 290, 250, 120, 5, ["молоко"], ["кофе"]),
            ("Латте", "Эспрессо и молоко", 290, 300, 130, 5, ["молоко"], ["кофе"]),
            ("Раф на кокосовых сливках", "Мягкий, с ванилью", 340, 300, 220, 6, ["молоко"], ["кофе"]),
            ("Морс клюквенный", "250 мл, собственного приготовления", 240, 250, 110, 0, [], ["холодное"]),
            ("Свежевыжатый апельсиновый", "250 мл", 450, 250, 110, 5, [], ["свежее", "сок"]),
            ("Чай травяной ассорти", "Иван-чай, мята, чабрец", 250, 400, 10, 5, [], ["чай"]),
        ],
    ),
    (
        "Десерты",
        "Фирменные десерты шефа",
        [
            ("Медовик", "Классический, 120 г", 420, 120, 380, 5, ["молоко", "глютен"], ["хит"]),
            ("Шоколадный фондан", "Тёплый шоколадный кекс с мороженым", 490, 140, 420, 10, ["молоко", "глютен", "яйцо"], ["фирменное"]),
            ("Панна котта", "Сливочный крем с ягодным соусом", 390, 130, 300, 3, ["молоко"], []),
            ("Сорбе", "Фруктовый, 100 мл", 290, 100, 180, 0, [], ["веган"]),
            ("Сырная тарелка", "5 сыров, мёд, орехи, виноград", 890, 260, 640, 10, ["молоко", "орехи"], ["деликатес"]),
        ],
    ),
    (
        "Завтраки",
        "Подаём с 8:00 до 12:00",
        [
            ("Сырники со сметаной", "Домашние, с ягодным джемом", 390, 220, 420, 12, ["молоко", "глютен", "яйцо"], []),
            ("Омлет с беконом", "Яйца, бекон, зелень, тост", 420, 280, 480, 10, ["яйцо", "глютен"], ["хит"]),
            ("Гранола с йогуртом", "Йогурт, гранола, мёд, фрукты", 380, 300, 390, 5, ["молоко", "орехи"], []),
        ],
    ),
]

HALLS = [
    {
        "name": "Основной зал",
        "description": "Зал с окнами, 40 посадочных мест",
        "layout_width": 1400,
        "layout_height": 900,
        "tables": [
            # name, seats, shape, x, y, w, h
            ("Т-1", 2, "round", 90, 90, 110, 110),
            ("Т-2", 2, "round", 280, 90, 110, 110),
            ("Т-3", 4, "rect", 480, 80, 180, 100),
            ("Т-4", 4, "rect", 740, 80, 180, 100),
            ("Т-5", 6, "rect", 1000, 80, 220, 100),
            ("Т-6", 2, "round", 90, 300, 110, 110),
            ("Т-7", 2, "round", 280, 300, 110, 110),
            ("Т-8", 4, "rect", 480, 290, 180, 100),
            ("Т-9", 4, "rect", 740, 290, 180, 100),
            ("Т-10", 2, "round", 90, 510, 110, 110),
            ("Т-11", 4, "rect", 280, 500, 180, 100),
            ("Т-12", 8, "rect", 540, 500, 280, 100),
        ],
    },
    {
        "name": "Летняя веранда",
        "description": "Открытая терраса, работает в тёплый сезон",
        "layout_width": 1200,
        "layout_height": 800,
        "tables": [
            ("В-1", 4, "square", 120, 120, 110, 110),
            ("В-2", 4, "square", 320, 120, 110, 110),
            ("В-3", 4, "square", 520, 120, 110, 110),
            ("В-4", 2, "round", 780, 140, 110, 110),
            ("В-5", 6, "rect", 980, 110, 200, 110),
            ("В-6", 4, "square", 200, 380, 110, 110),
            ("В-7", 4, "square", 400, 380, 110, 110),
            ("В-8", 6, "rect", 620, 370, 200, 110),
        ],
    },
]


def _staff(db: Session) -> None:
    if db.execute(select(func.count(User.id))).scalar():
        return

    db.add_all(
        [
            User(
                username=ADMIN_USERNAME,
                full_name="Администратор",
                role=Role.owner,
                hashed_password=hash_password(ADMIN_PASSWORD),
                can_manage_menu=True,
                can_manage_hall=True,
                can_manage_orders=True,
                can_manage_users=True,
                can_view_reports=True,
            ),
            User(
                username=MANAGER_USERNAME,
                full_name="Менеджер смены",
                phone="+7 900 000-00-01",
                role=Role.manager,
                hashed_password=hash_password(MANAGER_PASSWORD),
                pin_hash=hash_password("1234"),
                can_manage_menu=True,
                can_manage_hall=True,
                can_manage_orders=True,
                can_manage_users=False,
                can_view_reports=True,
            ),
            User(
                username=WAITER_USERNAME,
                full_name="Официант",
                role=Role.waiter,
                hashed_password=hash_password(WAITER_PASSWORD),
                pin_hash=hash_password("1111"),
                can_manage_menu=False,
                can_manage_hall=False,
                can_manage_orders=True,
                can_manage_users=False,
                can_view_reports=False,
            ),
        ]
    )
    db.flush()


def _menu(db: Session) -> None:
    if db.execute(select(func.count(Dish.id))).scalar():
        return

    db.add(
        MenuSettings(
            title="Меню Myata",
            subtitle="Кафе-бар · Домашняя кухня и свежая выпечка",
            currency_symbol="₽",
            show_weights=True,
            show_calories=False,
            show_allergens=True,
            welcome_text="Выберите блюдо и добавьте в корзину — официант принесёт заказ за ваш стол.",
            footer_text="Аллергены указаны по ФЗ. О наличии блюд можно уточнить у официанта.",
            theme_color="#8b1e1e",
        )
    )

    size_group = ModifierGroup(name="Размер порции", min_select=1, max_select=1, sort_order=1)
    size_group.modifiers = [
        Modifier(name="Стандарт 300 г", price_delta=0, is_default=True, sort_order=1),
        Modifier(name="Большая 450 г", price_delta=15000, sort_order=2),
    ]

    milk_group = ModifierGroup(name="Дополнительное молоко", min_select=0, max_select=1, sort_order=2)
    milk_group.modifiers = [
        Modifier(name="Обычное молоко", price_delta=0, sort_order=1),
        Modifier(name="Овсяное молоко", price_delta=5000, sort_order=2),
        Modifier(name="Без молока (на кокосовом)", price_delta=5000, sort_order=3),
    ]

    extras_group = ModifierGroup(name="Добавки к напиткам", min_select=0, max_select=3, sort_order=3)
    extras_group.modifiers = [
        Modifier(name="Двойной эспрессо", price_delta=8000, sort_order=1),
        Modifier(name="Сироп ванильный", price_delta=2000, sort_order=2),
        Modifier(name="Сискон корица", price_delta=2000, sort_order=3),
        Modifier(name="Взбитые сливки", price_delta=3000, sort_order=4),
    ]

    groups = [size_group, milk_group, extras_group]
    db.add_all(groups)
    db.flush()

    drink_groups = [milk_group, extras_group]
    main_groups = [size_group, milk_group]

    for cat_order, (cat_name, cat_desc, dishes) in enumerate(MENU_SEED):
        category = Category(
            name=cat_name,
            slug=f"cat-{cat_order + 1}",
            description=cat_desc,
            icon=("soup", "salad", "main", "pizza", "drink", "dessert", "breakfast")[cat_order],
            sort_order=cat_order,
        )
        db.add(category)
        db.flush()

        for idx, row in enumerate(dishes):
            name, desc, price, weight, kcal, minutes, allergens, tags = row
            dish = Dish(
                category_id=category.id,
                name=name,
                description=desc,
                price=price * 100,
                weight_grams=weight,
                calories=kcal,
                cooking_minutes=minutes,
                allergens=json.dumps(allergens, ensure_ascii=False),
                tags=json.dumps(tags, ensure_ascii=False),
                sort_order=idx,
                article=f"MY-{cat_order + 1}{idx + 1:03d}",
            )
            db.add(dish)
            db.flush()

            for group in (drink_groups if cat_name == "Напитки" else main_groups):
                db.add(
                    dish_modifier_groups(dish_id=dish.id, group_id=group.id)
                )

    db.flush()


def _hall(db: Session) -> None:
    if db.execute(select(func.count(Table.id))).scalar():
        return

    from app.services.qr import new_table_token

    for hall_order, spec in enumerate(HALLS):
        hall = Hall(
            name=spec["name"],
            description=spec["description"],
            layout_width=spec["layout_width"],
            layout_height=spec["layout_height"],
            sort_order=hall_order,
        )
        db.add(hall)
        db.flush()

        for t_order, (name, seats, shape, x, y, w, h) in enumerate(spec["tables"]):
            db.add(
                Table(
                    hall_id=hall.id,
                    name=name,
                    seats=seats,
                    shape=shape,
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    sort_order=t_order,
                    qr_token=new_table_token(),
                    external_id=f"TBL-{name}",
                )
            )
        db.flush()


def _reservations(db: Session) -> None:
    if db.execute(select(func.count(Reservation.id))).scalar():
        return

    now = datetime.now(UTC)
    tables = list(db.execute(select(Table).order_by(Table.name)).scalars().unique())
    samples = [
        (0, 1, "Ирина", "+7 900 111-22-33", 4),
        (1, 2, "Сергей", "+7 900 444-55-66", 6),
        (2, 4, "Анна", "+7 900 777-88-99", 2),
    ]
    for offset, table_idx, name, phone, guests in samples:
        if table_idx >= len(tables):
            continue
        db.add(
            Reservation(
                table_id=tables[table_idx].id,
                guest_name=name,
                phone=phone,
                guests_count=guests,
                reserved_at=now + timedelta(hours=offset + 1),
                duration_minutes=120,
                comment="Окно у окна" if offset == 0 else "",
            )
        )
    db.flush()


def _settings(db: Session) -> None:
    if db.execute(select(func.count(AppSetting.id))).scalar():
        return
    db.add_all(
        [
            AppSetting(key="venue_name", value="Myata Food"),
            AppSetting(key="venue_address", value="ул. Гастрономическая, 12"),
            AppSetting(key="venue_phone", value="+7 495 000-00-00"),
            AppSetting(key="wifi_network", value="Myata_Guest"),
            AppSetting(key="wifi_password", value="myata2024"),
            AppSetting(key="work_from", value="11:00"),
            AppSetting(key="work_to", value="00:00"),
        ]
    )
    db.add(IntegrationSetting(exchange_plan="ОбменMyata", enabled=False))
    db.flush()


def seed_if_empty(db: Session) -> None:
    _staff(db)
    _menu(db)
    _hall(db)
    _reservations(db)
    _settings(db)
    db.commit()
