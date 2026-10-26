from ..extensions import db
from ..utils import utcnow

ORDER_STATUSES = ("pending", "paid", "shipped", "delivered", "cancelled")
ORDER_CHANNELS = ("store", "pos")

STATUS_LABELS = {
    "pending": "Pendiente",
    "paid": "Pagado",
    "shipped": "Enviado",
    "delivered": "Entregado",
    "cancelled": "Cancelado",
}

CHANNEL_LABELS = {"store": "Tienda en línea", "pos": "Venta directa"}


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    city = db.Column(db.String(80))
    country = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    orders = db.relationship("Order", back_populates="customer")

    __table_args__ = (
        db.UniqueConstraint("company_id", "email", name="uq_customers_company_email"),
        db.UniqueConstraint("company_id", "user_id", name="uq_customers_company_user"),
    )

    @property
    def full_name(self):
        return "{} {}".format(self.first_name, self.last_name).strip()


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"))
    number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    channel = db.Column(db.String(20), nullable=False, default="store")
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    customer = db.relationship("Customer", back_populates="orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id")

    __table_args__ = (
        db.UniqueConstraint("company_id", "number", name="uq_orders_company_number"),
        db.CheckConstraint("status in ('pending', 'paid', 'shipped', 'delivered', 'cancelled')", name="ck_orders_status"),
        db.CheckConstraint("channel in ('store', 'pos')", name="ck_orders_channel"),
        db.CheckConstraint("total >= 0", name="ck_orders_total"),
        db.Index("ix_orders_company_created", "company_id", "created_at"),
        db.Index("ix_orders_customer", "customer_id"),
        db.Index("ix_orders_updated", "updated_at"),
    )

    @property
    def code(self):
        return "NC-{}-{:06d}".format(self.company_id, self.number)

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.BigInteger, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    sku = db.Column(db.String(60), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    line_total = db.Column(db.Numeric(14, 2), nullable=False)

    order = db.relationship("Order", back_populates="items")

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
        db.CheckConstraint("unit_price >= 0", name="ck_order_items_price"),
        db.Index("ix_order_items_product", "product_id"),
    )
