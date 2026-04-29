from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    slug = Column(String, unique=True, index=True)
    icon = Column(String, default="📦")
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
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
