"""Seed default category data on first startup.

Schema migrations are managed by Alembic (see ``alembic/`` and run with
``alembic upgrade head``). This module only handles idempotent reference-
data seeding for categories - those don't fit cleanly into a one-shot
migration because we want them to be top-up-able as new sub-categories
are added in code.
"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Category

_PARENTS = [
    ("Электроника",   "electronics",  "💻"),
    ("Авто",          "auto",         "🚗"),
    ("Одежда",        "clothing",     "👗"),
    ("Искусство",     "art",          "🎨"),
    ("Коллекционное", "collectibles", "🏺"),
    ("Спорт",         "sport",        "⚽"),
    ("Дом и сад",     "home",         "🏡"),
    ("Животные",      "animals",      "🐾"),
    ("Другое",        "other",        "📦"),
]

_SUBS_MAP = {
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


def _build_new_subs(
    parent_map: dict[str, int],
    existing_slugs: frozenset[str] = frozenset(),
) -> list[Category]:
    """Build child Category rows from _SUBS_MAP, filtering out anything
    already in ``existing_slugs`` (the top-up branch passes the current
    DB slug set; the fresh-install branch passes the empty default so
    every row is created). Shared so both branches stay aligned when a
    new sub-category is added to _SUBS_MAP."""
    new_subs: list[Category] = []
    for parent_slug, children in _SUBS_MAP.items():
        pid = parent_map.get(parent_slug)
        if not pid:
            continue
        for name, slug, icon in children:
            if slug in existing_slugs:
                continue
            new_subs.append(Category(name=name, slug=slug, icon=icon, parent_id=pid))
    return new_subs


async def seed_categories():
    async with SessionLocal() as db:
        # ``.first()`` returns the first row (or None), not a count -
        # the prior ``existing_count`` name read wrong; the test below
        # only cares whether *any* row exists.
        existing = (await db.execute(select(Category))).scalars().first()
        if existing is None:
            parents = [Category(name=n, slug=s, icon=i) for n, s, i in _PARENTS]
            db.add_all(parents)
            await db.commit()
            for p in parents:
                await db.refresh(p)

            parent_map = {p.slug: p.id for p in parents}
            db.add_all(_build_new_subs(parent_map))
            await db.commit()
        else:
            existing = (await db.execute(select(Category))).scalars().all()
            existing_slugs = frozenset(c.slug for c in existing)
            # Match parents by their canonical ``_PARENTS`` slug list
            # instead of inferring from ``parent_id IS NULL``. A future
            # category-tree refactor that converts a former parent into
            # a child of another (e.g. moving "other" under a real
            # parent) would otherwise leave the new orphan looking
            # like a parent here, and re-seeding would attach fresh
            # subs to the wrong row.
            _PARENT_SLUGS = frozenset(slug for _name, slug, _icon in _PARENTS)
            parent_map = {c.slug: c.id for c in existing if c.slug in _PARENT_SLUGS}
            new_subs = _build_new_subs(parent_map, existing_slugs)
            if new_subs:
                db.add_all(new_subs)
                await db.commit()
