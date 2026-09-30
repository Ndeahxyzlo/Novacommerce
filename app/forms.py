import re

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DecimalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    Optional,
    Regexp,
    ValidationError,
)

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def email_check(form, field):
    value = (field.data or "").strip()
    if not EMAIL_PATTERN.match(value) or len(value) > 255:
        raise ValidationError("Ingresa un correo válido.")


def password_check(form, field):
    value = field.data or ""
    if len(value) < 8:
        raise ValidationError("La contraseña debe tener al menos 8 caracteres.")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValidationError("La contraseña debe combinar letras y números.")


def strip_filter(value):
    return value.strip() if isinstance(value, str) else value


def lower_strip_filter(value):
    return value.strip().lower() if isinstance(value, str) else value


class LoginForm(FlaskForm):
    email = StringField("Correo", validators=[DataRequired(), email_check], filters=[lower_strip_filter])
    password = PasswordField("Contraseña", validators=[DataRequired()])
    remember = BooleanField("Mantener sesión iniciada")


class RegisterForm(FlaskForm):
    account_type = SelectField(
        "Tipo de cuenta",
        choices=[("customer", "Quiero comprar"), ("owner", "Quiero vender con mi empresa")],
        validators=[DataRequired()],
    )
    first_name = StringField("Nombre", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    last_name = StringField("Apellido", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    email = StringField("Correo", validators=[DataRequired(), email_check], filters=[lower_strip_filter])
    phone = StringField("Teléfono", validators=[Optional(), Length(max=30)], filters=[strip_filter])
    company_name = StringField("Nombre de la empresa", validators=[Optional(), Length(max=150)], filters=[strip_filter])
    password = PasswordField("Contraseña", validators=[DataRequired(), password_check])
    confirm = PasswordField("Confirmar contraseña", validators=[DataRequired(), EqualTo("password", "Las contraseñas no coinciden.")])

    def validate_company_name(self, field):
        if self.account_type.data == "owner" and not (field.data or "").strip():
            raise ValidationError("Indica el nombre de tu empresa.")


class ProfileForm(FlaskForm):
    first_name = StringField("Nombre", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    last_name = StringField("Apellido", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    phone = StringField("Teléfono", validators=[Optional(), Length(max=30)], filters=[strip_filter])


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Contraseña actual", validators=[DataRequired()])
    password = PasswordField("Nueva contraseña", validators=[DataRequired(), password_check])
    confirm = PasswordField("Confirmar contraseña", validators=[DataRequired(), EqualTo("password", "Las contraseñas no coinciden.")])


class ForgotPasswordForm(FlaskForm):
    email = StringField("Correo", validators=[DataRequired(), email_check], filters=[lower_strip_filter])


class ResetPasswordForm(FlaskForm):
    password = PasswordField("Nueva contraseña", validators=[DataRequired(), password_check])
    confirm = PasswordField("Confirmar contraseña", validators=[DataRequired(), EqualTo("password", "Las contraseñas no coinciden.")])


class CompanyForm(FlaskForm):
    name = StringField("Nombre", validators=[DataRequired(), Length(max=150)], filters=[strip_filter])
    description = TextAreaField("Descripción", validators=[Optional(), Length(max=2000)], filters=[strip_filter])
    email = StringField("Correo de contacto", validators=[Optional(), email_check], filters=[lower_strip_filter])
    phone = StringField("Teléfono", validators=[Optional(), Length(max=30)], filters=[strip_filter])
    city = StringField("Ciudad", validators=[Optional(), Length(max=80)], filters=[strip_filter])
    country = StringField("País", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    currency = SelectField("Moneda", choices=[("COP", "COP"), ("USD", "USD"), ("EUR", "EUR"), ("MXN", "MXN")])
    lead_time_days = IntegerField("Tiempo de reposición (días)", validators=[DataRequired(), NumberRange(min=1, max=365)])
    order_cost = DecimalField("Costo por pedido de reposición", places=2, validators=[NumberRange(min=0, max=1000000000)])
    holding_rate = DecimalField("Costo anual de mantener inventario (0 a 1)", places=4, validators=[NumberRange(min=0.01, max=1)])
    service_level = DecimalField("Nivel de servicio (0.5 a 0.999)", places=4, validators=[NumberRange(min=0.5, max=0.999)])


class ProductForm(FlaskForm):
    sku = StringField("SKU", validators=[DataRequired(), Length(max=60), Regexp(r"^[A-Za-z0-9._\-]+$", message="Usa letras, números, punto, guion o guion bajo.")], filters=[strip_filter])
    name = StringField("Nombre", validators=[DataRequired(), Length(max=200)], filters=[strip_filter])
    description = TextAreaField("Descripción", validators=[Optional(), Length(max=4000)], filters=[strip_filter])
    category = StringField("Categoría", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    price = DecimalField("Precio", places=2, validators=[NumberRange(min=0, max=100000000)])
    cost = DecimalField("Costo", places=2, validators=[NumberRange(min=0, max=100000000)])
    quantity = IntegerField("Stock inicial", validators=[Optional(), NumberRange(min=0, max=10000000)], default=0)
    active = BooleanField("Activo", default=True)


class StockAdjustForm(FlaskForm):
    delta = IntegerField("Cantidad (positiva entra, negativa sale)", validators=[DataRequired(), NumberRange(min=-1000000, max=1000000)])
    reason = SelectField(
        "Motivo",
        choices=[("restock", "Reposición"), ("adjustment", "Ajuste"), ("damage", "Daño o pérdida")],
    )


class CustomerForm(FlaskForm):
    first_name = StringField("Nombre", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    last_name = StringField("Apellido", validators=[DataRequired(), Length(max=80)], filters=[strip_filter])
    email = StringField("Correo", validators=[Optional(), email_check], filters=[lower_strip_filter])
    phone = StringField("Teléfono", validators=[Optional(), Length(max=30)], filters=[strip_filter])
    city = StringField("Ciudad", validators=[Optional(), Length(max=80)], filters=[strip_filter])
    country = StringField("País", validators=[Optional(), Length(max=80)], filters=[strip_filter])


class EmptyForm(FlaskForm):
    pass


class QuantityForm(FlaskForm):
    quantity = IntegerField("Cantidad", validators=[InputRequired(), NumberRange(min=0, max=10000)], default=1)


class CheckoutForm(FlaskForm):
    notes = TextAreaField("Notas del pedido", validators=[Optional(), Length(max=500)], filters=[strip_filter])
