import re
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from ..extensions import db
from ..turnos.models import Paciente
from ..turnos.services import NOMBRE_VALIDO
from .models import Usuario

bp = Blueprint("auth", __name__)


def _destino():
    """Redirección post-login."""
    destino = request.args.get("next", "")
    partes = urlsplit(destino)
    if destino.startswith("/") and not destino.startswith("//") and "\\" not in destino and not partes.netloc:
        return destino
    return url_for("turnos.lista" if current_user.es_personal else "publico.mis_turnos")


@bp.before_request
def ya_logueado():
    # Sesión activa
    if current_user.is_authenticated and request.endpoint in ("auth.login", "auth.registro"):
        return redirect(_destino())


def _error_de_registro(f):
    if not re.fullmatch(r"\d{7,8}", f["dni"]):
        return "El DNI tiene que tener 7 u 8 números, sin puntos."
    if not (NOMBRE_VALIDO.fullmatch(f["nombre"]) and NOMBRE_VALIDO.fullmatch(f["apellido"])):
        return "Nombre y apellido: solo letras, espacios, ' o -, hasta 60 caracteres."
    if not re.fullmatch(r"\d{10}", f["telefono"]):  # Teléfono obligatorio
        return "El teléfono tiene que tener 10 números (característica + número, sin 0 ni 15)."
    if "@" not in f["email"] or len(f["email"]) > 120:
        return "Ingresá un email válido."
    if not 8 <= len(f["contrasena"].encode()) <= 72:
        return "La contraseña tiene que tener entre 8 y 72 caracteres."
    if Usuario.query.filter_by(email=f["email"]).first():
        return "Ya existe una cuenta con ese email. Ingresá con tu contraseña."
    return None


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    """Registro de pacientes."""
    if request.method == "POST":
        f = {k: request.form.get(k, "").strip() for k in ("nombre", "apellido", "dni", "telefono", "email")}
        f["email"] = f["email"].lower()
        f["contrasena"] = request.form.get("contrasena", "")
        error = _error_de_registro(f)
        # RF-07 vinculación
        paciente = Paciente.query.filter_by(dni=f["dni"]).first() if not error else None
        if paciente and paciente.usuario_id:
            error = "Ese DNI ya tiene una cuenta. Ingresá con tu email y contraseña."
        elif paciente and paciente.apellido.lower() != f["apellido"].lower():
            error = "Ese DNI está registrado con otro apellido. Comunicate con el consultorio."
        if error:
            flash(error, "error")
            return render_template("auth/registro.html"), 400
        usuario = Usuario(nombre=f["nombre"], email=f["email"], rol="paciente")
        usuario.set_contrasena(f["contrasena"])
        if paciente is None:
            paciente = Paciente(dni=f["dni"], apellido=f["apellido"])
            db.session.add(paciente)
        paciente.nombre, paciente.telefono, paciente.usuario = f["nombre"], f["telefono"], usuario
        db.session.commit()
        login_user(usuario)
        flash(f"¡Bienvenido/a, {usuario.nombre}! Tu cuenta quedó creada.", "ok")
        return redirect(_destino())
    return render_template("auth/registro.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = Usuario.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if usuario and usuario.verificar_contrasena(request.form.get("contrasena", "")):
            login_user(usuario)
            return redirect(_destino())
        flash("Email o contraseña incorrectos.", "error")
    return render_template("auth/login.html")


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("publico.inicio"))
