from ..extensions import db
from ..utils import utcnow


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(170), nullable=False, unique=True)
    description = db.Column(db.Text)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    city = db.Column(db.String(80))
    country = db.Column(db.String(80), nullable=False, default="Colombia")
    currency = db.Column(db.String(3), nullable=False, default="COP")
    order_seq = db.Column(db.Integer, nullable=False, default=0)
    lead_time_days = db.Column(db.Integer, nullable=False, default=7)
    order_cost = db.Column(db.Numeric(12, 2), nullable=False, default=50000)
    holding_rate = db.Column(db.Numeric(5, 4), nullable=False, default=0.20)
    service_level = db.Column(db.Numeric(5, 4), nullable=False, default=0.95)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    users = db.relationship("User", back_populates="company")
    products = db.relationship("Product", back_populates="company", cascade="all, delete-orphan")

    __table_args__ = (
        db.CheckConstraint("lead_time_days > 0", name="ck_companies_lead_time"),
        db.CheckConstraint("order_cost >= 0", name="ck_companies_order_cost"),
        db.CheckConstraint("holding_rate > 0 and holding_rate <= 1", name="ck_companies_holding_rate"),
        db.CheckConstraint("service_level >= 0.5 and service_level < 1", name="ck_companies_service_level"),
    )
