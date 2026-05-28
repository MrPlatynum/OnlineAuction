"""Read-only category tree.

Categories are seeded by ``services.seed_data.seed_categories`` on
every startup - the API just surfaces the resulting parent/child tree
so the create-lot form and the listing filter can render it.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Category

router = APIRouter(prefix="/api", tags=["categories"])


@router.get("/categories")
async def get_categories(response: Response, db: AsyncSession = Depends(get_db)):
    # Categories are seeded at startup and effectively immutable in
    # the lifetime of a deployment, so a five-minute public cache is
    # a free latency win on every page-load (the listing filter and
    # the create-lot form both fetch this on render).
    response.headers["Cache-Control"] = "public, max-age=300"
    all_cats = (
        await db.execute(select(Category).order_by(Category.id))
    ).scalars().all()
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
