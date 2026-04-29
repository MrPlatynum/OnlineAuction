from sqlalchemy import inspect, text

from app.database import Base, SessionLocal, engine
from app.models import Category


def create_tables():
    Base.metadata.create_all(bind=engine)


def run_migrations():
    """Автомиграция — добавляем новые колонки если их нет."""
    with engine.connect() as conn:
        inspector = inspect(engine)
        existing_cols = [c['name'] for c in inspector.get_columns('auctions')]
        if 'category_id' not in existing_cols:
            conn.execute(text("ALTER TABLE auctions ADD COLUMN category_id INTEGER REFERENCES categories(id)"))
            conn.commit()
        if 'auction_type' not in existing_cols:
            conn.execute(text("ALTER TABLE auctions ADD COLUMN auction_type TEXT DEFAULT 'bid'"))
            conn.commit()
        conn.execute(text("UPDATE auctions SET auction_type = 'bid' WHERE auction_type IS NULL"))
        conn.commit()
        if 'bin_price' not in existing_cols:
            conn.execute(text("ALTER TABLE auctions ADD COLUMN bin_price REAL"))
            conn.commit()
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auction_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id INTEGER NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                "order" INTEGER DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL REFERENCES users(id),
                reviewer_id INTEGER NOT NULL REFERENCES users(id),
                auction_id INTEGER REFERENCES auctions(id),
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL REFERENCES users(id),
                seller_id INTEGER NOT NULL REFERENCES users(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(subscriber_id, seller_id)
            )
        """))
        conn.commit()

        cat_cols = [c['name'] for c in inspector.get_columns('categories')]
        if 'parent_id' not in cat_cols:
            conn.execute(text("ALTER TABLE categories ADD COLUMN parent_id INTEGER REFERENCES categories(id)"))
            conn.commit()

        user_cols = [c['name'] for c in inspector.get_columns('users')]
        if 'avatar_url' not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url TEXT"))
            conn.commit()

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                balance_after REAL NOT NULL,
                description TEXT,
                auction_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()


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
