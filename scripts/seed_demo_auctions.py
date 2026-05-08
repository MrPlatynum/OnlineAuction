"""Seed 25 demo auctions for local testing.

Run from project root:
    python -m scripts.seed_demo_auctions

Creates a demo user "demo" (password: demo) if missing, then inserts
25 active auctions spread across categories with varied prices,
end times, and a mix of BID/BIN types.

Idempotent on the user; auctions are appended every run.
"""
from __future__ import annotations

import asyncio
import random
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Auction, Category, User
from app.utils.security import hash_password
from app.utils.time import utcnow

DEMO_USERNAME = "demo"
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo"


# (title, description, category_slug, type, price, duration_minutes)
LOTS: list[tuple[str, str, str, str, int, int]] = [
    ("iPhone 15 Pro 256GB", "Состояние нового, в коробке, все аксессуары. Гарантия 1 год.", "phones", "bid", 850, 360),
    ("MacBook Pro M3 14\"", "16GB RAM, 512GB SSD, Space Black. Куплен в марте, использовался месяц.", "laptops", "bid", 1700, 720),
    ("Sony A7 IV + 28-70mm", "Полный комплект, пробег 4k кадров. Идеальное состояние.", "photo", "bid", 2100, 480),
    ("AirPods Pro 2 USB-C", "Запечатанные. Apple Care+ до 2027.", "audio", "bin", 220, 1440),
    ("PS5 Slim Disc Edition", "Новая, с тремя играми: GoW Ragnarok, Spider-Man 2, Returnal.", "gaming", "bid", 480, 600),
    ("LG OLED 55\" C3", "2024 год выпуска, 4K 120Hz, идеально для PS5/Xbox.", "tv", "bid", 1250, 540),

    ("BMW 3-series 2019", "Пробег 78 000 км, один владелец, полная история ТО.", "cars", "bid", 22000, 4320),
    ("Yamaha MT-07 2022", "9 000 км, как из салона. Зимой стоял в гараже.", "motos", "bid", 6800, 2880),
    ("Колёса Michelin 245/45 R18", "Комплект, остаток протектора 80%. Сезон 2024.", "parts", "bin", 480, 4320),

    ("Tom Ford костюм 50 размер", "Серый, 100% шерсть, носился 2 раза. Чек прилагается.", "men", "bid", 950, 720),
    ("Платье Valentino весна-лето", "Размер 38, оригинал, новое с биркой.", "women", "bid", 1400, 1440),
    ("Air Jordan 1 Chicago Lost & Found", "Размер US 10, deadstock в коробке.", "shoes", "bin", 650, 2880),
    ("Часы Rolex Submariner 116610LN", "2018 год, full set, недавнее ТО у официала.", "accessory", "bid", 12500, 5760),

    ("Картина маслом 60x80", "Морской пейзаж, художник М. К. Антонов, 2023.", "painting", "bid", 320, 1080),
    ("Бронзовая скульптура (XX век)", "Высота 42 см, подпись на основании, отличная сохранность.", "sculpture", "bid", 780, 2160),
    ("Лимитированная серия фото-принта", "10/50, подпись автора, рамка дуб.", "photoart", "bid", 240, 1440),
    ("NFT-арт + физический холст", "Уникальная цифровая работа, токен на Ethereum, печать на холсте.", "digital", "bid", 600, 720),

    ("Велосипед Specialized Tarmac SL7", "Размер 56, Ultegra Di2, в идеальном состоянии.", "cycling", "bid", 4200, 2160),
    ("Гриф олимпийский 20кг + 100кг блинов", "Профессиональный, для дома, чугун в обрезиненной отделке.", "fitness", "bin", 380, 1440),
    ("Лыжный комплект Atomic Redster", "Лыжи 175см, ботинки 27.5, палки. Сезон катался в Шерегеше.", "winter", "bid", 540, 1440),

    ("Угловой диван Pottery Barn", "Кожа, 3,2 м, состояние отличное. Самовывоз.", "furniture", "bid", 1100, 2880),
    ("Шуруповёрт Bosch GSR 18V-60", "С двумя АКБ 4Ah и кейсом, использовался пару раз.", "tools", "bin", 220, 1440),
    ("Дубовая бочка для виски 50л", "Новая, для домашнего созревания напитков.", "garden", "bid", 360, 2160),
    ("Винтажная керосиновая лампа", "Латунь, 1920-е годы, рабочее состояние.", "decor", "bid", 180, 1080),

    ("Набор покемон-карт 1999 базовый сет", "12 редких карт включая Charizard holo. PSA 8.", "collectibles", "bid", 3500, 2880),
]


async def get_or_create_demo_user(db) -> User:
    user = (await db.execute(select(User).where(User.username == DEMO_USERNAME))).scalar_one_or_none()
    if user:
        return user
    user = User(
        username=DEMO_USERNAME,
        email=DEMO_EMAIL,
        hashed_password=hash_password(DEMO_PASSWORD),
        balance=Decimal("100000.00"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def seed():
    async with SessionLocal() as db:
        cats = (await db.execute(select(Category))).scalars().all()
        slug_to_id = {c.slug: c.id for c in cats}
        if not slug_to_id:
            print("No categories found — run app once (or seed_categories) first.")
            return

        user = await get_or_create_demo_user(db)
        now = utcnow()

        created = 0
        for title, desc, cat_slug, atype, price, dur_min in LOTS:
            cat_id = slug_to_id.get(cat_slug)
            if cat_id is None:
                continue
            jitter = random.randint(-20, 20)
            end = now + timedelta(minutes=dur_min + jitter)
            starting = Decimal(price)
            bin_price = Decimal(price) if atype == "bin" else None
            db.add(
                Auction(
                    title=title,
                    description=desc,
                    starting_price=starting,
                    current_price=starting,
                    image_url=None,
                    start_time=now,
                    end_time=end,
                    is_active=True,
                    is_completed=False,
                    created_by=user.id,
                    category_id=cat_id,
                    auction_type=atype,
                    bin_price=bin_price,
                )
            )
            created += 1
        await db.commit()
        print(f"Seeded {created} demo auctions for user '{user.username}' (password: {DEMO_PASSWORD}).")


if __name__ == "__main__":
    asyncio.run(seed())
