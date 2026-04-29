"""Seed default category data on first startup.

Schema migrations are managed by Alembic (see ``alembic/`` and run with
``alembic upgrade head``). This module only handles idempotent reference-
data seeding for categories — those don't fit cleanly into a one-shot
migration because we want them to be top-up-able as new sub-categories
are added in code.
"""

from app.database import SessionLocal
from app.models import Category


def seed_categories():
    db = SessionLocal()
    try:
        if db.query(Category).count() == 0:
            parents = [
                Category(name="Электроника",   slug="electronics",  icon="💻"),
                Category(name="Авто",          slug="auto",         icon="🚗"),
                Category(name="Одежда",        slug="clothing",     icon="👗"),
                Category(name="Искусство",     slug="art",          icon="🎨"),
                Category(name="Коллекционное", slug="collectibles", icon="🏺"),
                Category(name="Спорт",         slug="sport",        icon="⚽"),
                Category(name="Дом и сад",     slug="home",         icon="🏡"),
                Category(name="Животные",      slug="animals",      icon="🐾"),
                Category(name="Другое",        slug="other",        icon="📦"),
            ]
            db.add_all(parents)
            db.commit()
            for p in parents:
                db.refresh(p)

            subs_map = {
                "electronics": [
                    ("Смартфоны",      "phones",    "📱"),
                    ("Ноутбуки",       "laptops",   "💻"),
                    ("Фото и видео",   "photo",     "📷"),
                    ("Аудио",          "audio",     "🎧"),
                    ("Игры и консоли", "gaming",    "🎮"),
                    ("ТВ и мониторы",  "tv",        "🖥️"),
                ],
                "auto": [
                    ("Легковые",  "cars",   "🚗"),
                    ("Мотоциклы", "motos",  "🏍️"),
                    ("Запчасти",  "parts",  "🔧"),
                    ("Грузовые",  "trucks", "🚛"),
                ],
                "clothing": [
                    ("Мужская",    "men",       "👔"),
                    ("Женская",    "women",     "👗"),
                    ("Детская",    "kids",      "🧒"),
                    ("Обувь",      "shoes",     "👟"),
                    ("Аксессуары", "accessory", "💍"),
                ],
                "art": [
                    ("Живопись",   "painting",  "🖼️"),
                    ("Скульптура", "sculpture", "🗿"),
                    ("Фотоарт",    "photoart",  "📸"),
                    ("Цифровое",   "digital",   "💾"),
                ],
                "sport": [
                    ("Велоспорт",      "cycling", "🚴"),
                    ("Фитнес",         "fitness", "🏋️"),
                    ("Зимние виды",    "winter",  "⛷️"),
                    ("Командные виды", "team",    "⚽"),
                ],
                "home": [
                    ("Мебель",      "furniture", "🛋️"),
                    ("Инструменты", "tools",     "🔨"),
                    ("Сад",         "garden",    "🌿"),
                    ("Декор",       "decor",     "🕯️"),
                ],
            }
            parent_map = {p.slug: p.id for p in parents}
            subs = []
            for parent_slug, children in subs_map.items():
                pid = parent_map.get(parent_slug)
                if not pid:
                    continue
                for name, slug, icon in children:
                    subs.append(Category(name=name, slug=slug, icon=icon, parent_id=pid))
            db.add_all(subs)
            db.commit()
        else:
            existing_slugs = {c.slug for c in db.query(Category).all()}
            parent_map = {
                c.slug: c.id
                for c in db.query(Category).filter(Category.parent_id == None).all()
            }
            subs_map = {
                "electronics": [("Смартфоны","phones","📱"),("Ноутбуки","laptops","💻"),("Фото и видео","photo","📷"),("Аудио","audio","🎧"),("Игры и консоли","gaming","🎮"),("ТВ и мониторы","tv","🖥️")],
                "auto":        [("Легковые","cars","🚗"),("Мотоциклы","motos","🏍️"),("Запчасти","parts","🔧"),("Грузовые","trucks","🚛")],
                "clothing":    [("Мужская","men","👔"),("Женская","women","👗"),("Детская","kids","🧒"),("Обувь","shoes","👟"),("Аксессуары","accessory","💍")],
                "art":         [("Живопись","painting","🖼️"),("Скульптура","sculpture","🗿"),("Фотоарт","photoart","📸"),("Цифровое","digital","💾")],
                "sport":       [("Велоспорт","cycling","🚴"),("Фитнес","fitness","🏋️"),("Зимние виды","winter","⛷️"),("Командные виды","team","⚽")],
                "home":        [("Мебель","furniture","🛋️"),("Инструменты","tools","🔨"),("Сад","garden","🌿"),("Декор","decor","🕯️")],
            }
            new_subs = []
            for parent_slug, children in subs_map.items():
                pid = parent_map.get(parent_slug)
                if not pid:
                    continue
                for name, slug, icon in children:
                    if slug not in existing_slugs:
                        new_subs.append(Category(name=name, slug=slug, icon=icon, parent_id=pid))
            if new_subs:
                db.add_all(new_subs)
                db.commit()
    finally:
        db.close()
