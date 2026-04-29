from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category

router = APIRouter(prefix="/api", tags=["categories"])


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    all_cats = db.query(Category).order_by(Category.id).all()
    parents = [c for c in all_cats if c.parent_id is None]
    children_map = {}
    for c in all_cats:
        if c.parent_id:
            children_map.setdefault(c.parent_id, []).append(c)
    return [
        {
            "id": p.id, "name": p.name, "slug": p.slug, "icon": p.icon,
            "children": [
                {"id": ch.id, "name": ch.name, "slug": ch.slug, "icon": ch.icon}
                for ch in children_map.get(p.id, [])
            ],
        }
        for p in parents
    ]
