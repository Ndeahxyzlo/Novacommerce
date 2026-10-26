from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, login_manager
from ..utils import utcnow

ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
ROLE_CUSTOMER = "customer"
ROLES = (ROLE_ADMIN, ROLE_OWNER, ROLE_CUSTOMER)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(30))
    role = db.Column(db.String(20), nullable=False, default=ROLE_CUSTOMER)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    password_changed_at = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    company = db.relationship("Company", back_populates="users")

    __table_args__ = (
        db.CheckConstraint("role in ('admin', 'owner', 'customer')", name="ck_users_role"),
        db.CheckConstraint("role <> 'owner' or company_id is not null", name="ck_users_owner_company"),
    )

    @property
    def is_active(self):
        return bool(self.active)

    @property
    def full_name(self):
        return "{} {}".format(self.first_name, self.last_name).strip()

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_owner(self):
        return self.role == ROLE_OWNER

    @property
    def is_customer(self):
        return self.role == ROLE_CUSTOMER

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)
        self.password_changed_at = utcnow()

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
