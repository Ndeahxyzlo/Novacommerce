from ..extensions import db
from ..utils import utcnow


class DemandForecast(db.Model):
    __tablename__ = "demand_forecasts"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    week_start = db.Column(db.Date, nullable=False)
    predicted_units = db.Column(db.Float, nullable=False)
    model_kind = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    product = db.relationship("Product")

    __table_args__ = (db.UniqueConstraint("product_id", "week_start", name="uq_forecast_product_week"),)


class MlRun(db.Model):
    __tablename__ = "ml_runs"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    kind = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="ok")
    metrics = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class AccessLog(db.Model):
    __tablename__ = "access_logs"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    email = db.Column(db.String(255))
    ip = db.Column(db.String(45), nullable=False)
    event = db.Column(db.String(30), nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    path = db.Column(db.String(200))
    user_agent = db.Column(db.String(255))
    label = db.Column(db.Integer)
    risk = db.Column(db.Float)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        db.Index("ix_access_ip_created", "ip", "created_at"),
        db.Index("ix_access_email_created", "email", "created_at"),
        db.Index("ix_access_created", "created_at"),
    )
