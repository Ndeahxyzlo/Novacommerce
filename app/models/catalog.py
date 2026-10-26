from ..extensions import db
from ..utils import utcnow


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(80), nullable=False, default="General")
    price = db.Column(db.Numeric(12, 2), nullable=False)
    cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    company = db.relationship("Company", back_populates="products")
    inventory = db.relationship("Inventory", back_populates="product", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("company_id", "sku", name="uq_products_company_sku"),
        db.CheckConstraint("price >= 0", name="ck_products_price"),
        db.CheckConstraint("cost >= 0", name="ck_products_cost"),
        db.Index("ix_products_company_category", "company_id", "category"),
    )


class Inventory(db.Model):
    __tablename__ = "inventory"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    reorder_point = db.Column(db.Integer, nullable=False, default=0)
    safety_stock = db.Column(db.Integer, nullable=False, default=0)
    eoq = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    product = db.relationship("Product", back_populates="inventory")

    __table_args__ = (
        db.CheckConstraint("quantity >= 0", name="ck_inventory_quantity"),
        db.CheckConstraint("reorder_point >= 0", name="ck_inventory_reorder_point"),
        db.CheckConstraint("safety_stock >= 0", name="ck_inventory_safety_stock"),
        db.CheckConstraint("eoq >= 0", name="ck_inventory_eoq"),
    )

    @property
    def needs_restock(self):
        return self.reorder_point > 0 and self.quantity <= self.reorder_point


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

    id = db.Column(db.BigInteger, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    delta = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(30), nullable=False)
    reference = db.Column(db.String(60))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    product = db.relationship("Product")

    __table_args__ = (
        db.Index("ix_movements_company_created", "company_id", "created_at"),
        db.Index("ix_movements_product", "product_id"),
    )


class CartItem(db.Model):
    __tablename__ = "cart_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    product = db.relationship("Product")

    __table_args__ = (
        db.UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),
        db.CheckConstraint("quantity > 0 and quantity <= 10000", name="ck_cart_quantity"),
    )


class Wishlist(db.Model):
    __tablename__ = "wishlists"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    product = db.relationship("Product")

    __table_args__ = (db.UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product"),)
