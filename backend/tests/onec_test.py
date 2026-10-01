"""Contract of the 1C exchange: the XML must be parseable and shaped right.

Every attribute has to be quoted - an unquoted value makes the whole document
unwell-formed and 1C would reject the file before reading a single node.
"""

from __future__ import annotations

import sys
import uuid
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.integration import OneCPush  # noqa: E402
from app.services.onec import exchange as onec  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


class _Collector(BaseHTTPRequestHandler):
    """Stands in for the 1C HTTP web service."""

    bodies: list[bytes] = []
    auth: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        _Collector.bodies.append(self.rfile.read(length))
        _Collector.auth.append(self.headers.get("Authorization", ""))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("загружено".encode())

    def log_message(self, *args) -> None:  # silence the default stderr log
        return


def run() -> int:
    from app.db.session import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        cfg = onec.get_settings(db)
        admin = db.query(User).order_by(User.id).first()

        # --- 1. every entity group is well-formed XML -----------------------
        print("\n[1] well-formedness of the export package")
        nodes = onec.build_package(
            db, categories=True, dishes=True, modifiers=True, orders=True, day_closes=True
        )
        xml = onec.to_xml(nodes, cfg, exchange_name="contract")
        try:
            root = ET.fromstring(xml)
            check("export parses", True)
        except ET.ParseError as exc:
            check("export parses", False, f"-> {exc}")
            return 1

        check("root tag", root.tag == "СообщениеОбмена", root.tag)
        check("envelope attributes quoted",
              root.get("ДатаОтправки") and root.get("Ид") and root.get("ПланОбмена"),
              str(root.attrib))

        # An order carries its own Ссылка plus the table's - the table must use
        # a distinct attribute name, otherwise the element is not well-formed.
        duplicates = [f"<{el.tag}>: {sorted(el.attrib)}"
                      for el in root.iter() if len(el.attrib) != len(set(el.attrib))]
        check("no element repeats an attribute name", not duplicates,
              "; ".join(duplicates[:3]))
        check("sender element", root.findtext("Отправитель") == "1C")
        check("parameters element", len(root.findall("Параметры")) == 2)

        groups = {g.get("Имя"): g for g in root.findall("Группа")}
        # Модификаторы и блюда - это один и тот же справочник в 1С, поэтому
        # групп столько же, сколько различных имён типов. Пустые группы
        # в сообщение не попадают.
        check("group names are known entity types", set(groups) <= set(onec.ENTITY_TYPES),
              str(set(groups) - set(onec.ENTITY_TYPES)))
        check("empty entity types are omitted",
              set(onec.ENTITY_TYPES) - set(groups) == {k for k, v in nodes.items() if not v},
              str(set(onec.ENTITY_TYPES) - set(groups)))
        for name, group in groups.items():
            declared = int(group.get("Количество", "0"))
            check(f"count matches '{name}'", declared == len(list(group)), f"{declared}")

        # --- 2. node attributes the 1C side reads ---------------------------
        print("\n[2] node attributes")
        catalogue = groups.get(onec.ENTITY_DISH)
        if catalogue is not None:
            # Модификаторы лежат в том же справочнике и помечены Услуга="true",
            # поэтому блюда отбираем по наличию признака Доступно.
            dishes = [n for n in catalogue if n.get("Услуга") is None]
            mods = [n for n in catalogue if n.get("Услуга") == "true"]
            check("modifiers are services in the same catalogue", bool(mods), str(len(mods)))
            for first in dishes[:1]:
                for attr in ("Ссылка", "Код", "Наименование", "ЦенаНДС", "ВидНДС", "Доступно"):
                    check(f"Номенклатура.{attr}", first.get(attr) is not None, str(first.attrib))
                check("Номенклатура.Ссылка is a guid", len(first.get("Ссылка", "")) == 32,
                      first.get("Ссылка"))
                check("Номенклатура.ЦенаНДС is decimal", "." in first.get("ЦенаНДС", ""),
                      first.get("ЦенаНДС"))
                check("booleans are quoted strings", first.get("Доступно") in ("true", "false"),
                      repr(first.get("Доступно")))

        orders = groups.get(onec.ENTITY_ORDER)
        if orders is not None and len(list(orders)):
            order = list(orders)[0]
            for attr in ("Ссылка", "Номер", "Дата", "Статус", "Итого"):
                check(f"ЗаказПокупателя.{attr}", order.get(attr) is not None, str(order.attrib))
            check("ЗаказПокупателя.Дата quoted", "-" in order.get("Дата", ""))
            for item in order.findall("Товар"):
                check("Товар.Цена quoted", item.get("Цена") is not None)
                for mod in item.findall("Модификатор"):
                    check("Модификатор.Цена quoted", mod.get("Цена") is not None)

        closes = groups.get(onec.ENTITY_DAY_CLOSE)
        if closes is not None and len(list(closes)):
            close = list(closes)[0]
            check("ЗакрытиеДня.Выручка quoted", close.get("Выручка") is not None)
            check("ЗакрытиеДня.Выручка is decimal", "." in close.get("Выручка", ""),
                  close.get("Выручка"))

        # --- 3. special characters must survive a round-trip ---------------
        print("\n[3] escaping")
        from app.models.menu import Category

        tricky = Category(
            name='Еда "по-быстрому" & <новики>',
            slug="tricky-escaping-fixture",
            description="a < b & c > d",
        )
        db.add(tricky)
        db.flush()
        node = onec.category_node(db, tricky)
        parsed = ET.fromstring(node)
        check("quotes/ampersands in text and attributes",
              parsed.get("Наименование") == 'Еда "по-быстрому" & <новики>',
              parsed.get("Наименование"))
        check("description preserved", parsed.text == "a < b & c > d", parsed.text)
        db.delete(tricky)
        db.commit()

        # --- 4. delivery to the web service --------------------------------
        print("\n[4] delivery")
        _Collector.bodies.clear()
        _Collector.auth.clear()
        server = HTTPServer(("127.0.0.1", 0), _Collector)
        port = server.server_address[1]
        Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/hs/Exchange/Load"

        cfg.endpoint_url = url
        cfg.login = "Exchange"
        cfg.password = "s3cret"
        db.commit()

        result = onec.run_export(db, dishes=True, modifiers=False, categories=False,
                                 orders=False, day_closes=False,
                                 user=admin, deliver=True)
        server.shutdown()

        check("delivered without error", not result.get("error"), str(result.get("error")))
        check("one request received", len(_Collector.bodies) == 1, str(len(_Collector.bodies)))
        if _Collector.bodies:
            received = _Collector.bodies[0]
            try:
                ET.fromstring(received)
                check("delivered body is valid XML", True)
            except ET.ParseError as exc:
                check("delivered body is valid XML", False, f"-> {exc}")
        check("basic auth sent", _Collector.auth[0].startswith("Basic ") if _Collector.auth else False,
              str(_Collector.auth))
        check("log marks success", result["log"].status == "success", result["log"].status)
        from app.core.config import settings as app_settings

        saved = app_settings.exports_path / result["file_name"]
        check("file kept as fallback", saved.is_file(), str(saved))

        # --- 5. delivery failure is reported, not swallowed -----------------
        print("\n[5] delivery failure")
        cfg.endpoint_url = "http://127.0.0.1:9/unreachable"
        db.commit()
        failed = onec.run_export(db, dishes=True, modifiers=False, categories=False,
                                 orders=False, day_closes=False,
                                 user=admin, deliver=True)
        check("error surfaced", bool(failed.get("error")), str(failed)[:120])
        check("log marks error", failed["log"].status == "error", failed["log"].status)

        cfg.endpoint_url = ""
        db.commit()
        missing = onec.run_export(db, dishes=True, modifiers=False, categories=False,
                                  orders=False, day_closes=False,
                                  user=admin, deliver=True)
        check("empty endpoint_url refused", "endpoint_url" in str(missing.get("error", "")),
              str(missing.get("error")))

        # --- 6. inbound push shape -----------------------------------------
        print("\n[6] inbound push schema")
        push = OneCPush(items=[{
            "entity": onec.ENTITY_DISH, "external_id": "CONTRACT-1",
            "name": "Контракт", "price": 12.5, "is_available": False,
        }])
        stats = onec.apply_incoming(db, push.items)
        check("created", stats["created"] == 1, str(stats))
        again = onec.apply_incoming(db, push.items)
        check("idempotent on repeat", again["created"] == 0 and again["updated"] == 1, str(again))

        from app.models.integration import SyncMap
        from app.models.menu import Dish

        dish = db.query(Dish).filter(Dish.external_id == "CONTRACT-1").one()
        check("price converted to kopecks", dish.price == 1250, str(dish.price))
        check("is_available applied", dish.is_available is False, str(dish.is_available))

        # A mapping row left dangling by a deletion must be repaired, not
        # duplicated: the unique index on (entity_type, external_id) would blow up.
        db.delete(dish)
        db.commit()
        repaired = onec.apply_incoming(db, push.items)
        check("dangling mapping repaired", repaired["created"] == 1, str(repaired))
        check("no duplicate mapping",
              db.query(SyncMap).filter(
                  SyncMap.entity_type == onec.ENTITY_DISH,
                  SyncMap.external_id == "CONTRACT-1").count() == 1)
        healed = db.query(SyncMap).filter(
            SyncMap.entity_type == onec.ENTITY_DISH, SyncMap.external_id == "CONTRACT-1"
        ).one()
        check("mapping points at a live dish",
              db.get(Dish, uuid.UUID(healed.local_id)) is not None, healed.local_id)

        db.query(Dish).filter(Dish.external_id == "CONTRACT-1").delete()
        db.query(SyncMap).filter(SyncMap.external_id == "CONTRACT-1").delete()
        db.commit()

        # --- 7. everything the 1C extension actually reads -------------------
        # Повторяет правила чтения из onec-extension/Myata/CommonModules/ОбменСMyata.
        print("\n[7] attributes read by the 1C extension")
        from app.models.hall import DayClose
        from app.models.order import Order, OrderItem

        day_close = db.query(DayClose).filter(
            DayClose.business_date == "2099-12-31").first()
        if day_close is None:
            day_close = DayClose(business_date="2099-12-31", guests_total=7,
                                 orders_total=3, revenue_total=1234.56,
                                 notes="проверка контракта")
            db.add(day_close)
        dish_for_order = db.query(Dish).first()
        order = db.query(Order).filter(
            Order.order_number == "CONTRACT-1").first()
        if order is None:
            order = Order(order_number="CONTRACT-1", status="closed", source="qr",
                          guests_count=2, client_name="Проверка", total_amount=1500.00)
            db.add(order)
            db.flush()
            db.add(OrderItem(
                order_id=order.id, dish_id=dish_for_order.id,
                dish_name=dish_for_order.name, quantity=2, price=750.00,
            ))
        db.commit()

        try:
            nodes = onec.build_package(db, categories=True, dishes=True, modifiers=True,
                                       orders=True, day_closes=True)
            package = ET.fromstring(onec.to_xml(nodes, cfg, exchange_name="ext"))

            check("extension reads ПланОбмена", package.get("ПланОбмена") is not None)
            check("extension reads Ид", package.get("Ид") is not None)
            check("extension reads Отправитель",
                  package.findtext("Отправитель") == "1C")

            seen = set()
            dish_checked = service_checked = False
            for group in package.findall("Группа"):
                name = group.get("Имя")
                seen.add(name)
                if name == "Справочник.Номенклатура":
                    # Модификатор отличается от блюда признаком Услуга="true"
                    # и не имеет артикула и признаков меню.
                    for node in group.findall("Номенклатура"):
                        if node.get("Услуга") == "true":
                            if service_checked:
                                continue
                            service_checked = True
                            for attr in ("Ссылка", "Код", "Наименование",
                                         "ЦенаНДС", "ВидНДС", "Активен"):
                                check(f"extension reads Модификатор.{attr}",
                                      node.get(attr) is not None, str(node.attrib))
                        else:
                            if dish_checked:
                                continue
                            dish_checked = True
                            for attr in ("Ссылка", "Код", "Наименование", "Артикул",
                                         "ЦенаНДС", "ВидНДС", "ВМеню",
                                         "Доступно", "ПоказыватьВQR"):
                                check(f"extension reads Номенклатура.{attr}",
                                      node.get(attr) is not None, str(node.attrib))
                elif name == "Справочник.НоменклатураГруппы":
                    for node in group.findall("НоменклатураГруппа")[:1]:
                        for attr in ("Ссылка", "Код", "Наименование"):
                            check(f"extension reads НоменклатураГруппа.{attr}",
                                  node.get(attr) is not None, str(node.attrib))
                elif name == "Справочник.Столы":
                    for node in group.findall("Стол")[:1]:
                        check("extension reads Стол.Наименование",
                              node.get("Наименование") is not None)
                elif name == "Документ.ЗаказПокупателя":
                    for node in group.findall("ЗаказПокупателя")[:1]:
                        for attr in ("Ссылка", "Номер", "Дата", "Статус", "Итого"):
                            check(f"extension reads ЗаказПокупателя.{attr}",
                                  node.get(attr) is not None, str(node.attrib))
                        items = node.findall("Товар")
                        check("order carries items", len(items) >= 1, str(len(items)))
                        for item in items[:1]:
                            for attr in ("Наименование", "Количество", "Цена"):
                                check(f"extension reads Товар.{attr}",
                                      item.get(attr) is not None, str(item.attrib))
                elif name == "Отчет.ЗакрытиеДня":
                    for node in group.findall("ЗакрытиеДня")[:1]:
                        for attr in ("Ссылка", "Дата", "Гостей", "Заказов", "Выручка"):
                            check(f"extension reads ЗакрытиеДня.{attr}",
                                  node.get(attr) is not None, str(node.attrib))

            check("all six entity types reached the extension",
                  seen == set(onec.ENTITY_TYPES), str(seen ^ set(onec.ENTITY_TYPES)))
        finally:
            db.delete(order)
            db.delete(day_close)
            db.commit()
    finally:
        db.close()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(run())
