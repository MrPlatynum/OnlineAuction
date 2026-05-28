from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    # ``nullable=False`` on the unique columns is load-bearing: Postgres
    # treats NULL as distinct in UNIQUE indexes, so without this two or
    # more rows with ``slug=NULL`` could legally coexist and break the
    # ``/categories/<slug>`` route plus the seed-time "already exists"
    # check. The seed always populates both fields, but admin tools and
    # future migrations need the constraint enforced at the schema.
    name = Column(String(100), unique=True, index=True, nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    icon = Column(String(20), default="📦")
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    auctions = relationship("Auction", back_populates="category")
    children = relationship(
        "Category", back_populates="parent", foreign_keys="Category.parent_id"
    )
    parent = relationship(
        "Category",
        back_populates="children",
        foreign_keys="Category.parent_id",
        remote_side="Category.id",
    )
