import os

import bcrypt
from flask import abort
from flask_login import UserMixin, current_user

from ..extensions import db, login_manager

PERSONAL = ("administrador", "recepcion")


class Usuario(UserMixin, db.Model):  # D10 Usuarios
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    contrasena = db.Column(db.String(60), nullable=False)  # Hash bcrypt (RNF-01)
    rol = db.Column(db.String(13), nullable=False, default="paciente")  # administrador | recepcion | paciente

    @property
    def es_personal(self):
        return self.rol in PERSONAL

    def set_contrasena(self, texto):
        self.contrasena = bcrypt.hashpw(texto.encode(), bcrypt.gensalt()).decode()

    def verificar_contrasena(self, texto):
        clave = texto.encode()
        return len(clave) <= 72 and bcrypt.checkpw(clave, self.contrasena.encode())  # Límite bcrypt


@login_manager.user_loader
def cargar_usuario(id):
    return db.session.get(Usuario, int(id))


def solo_personal():
    """Acceso solo personal."""
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    if not current_user.es_personal:
        abort(403)


def crear_admin_desde_entorno():
    """Admin inicial (.env)."""
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    contrasena = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not contrasena or Usuario.query.filter_by(email=email).first():
        return
    if not 8 <= len(contrasena.encode()) <= 72:
        raise RuntimeError("ADMIN_PASSWORD tiene que tener entre 8 y 72 caracteres.")
    admin = Usuario(nombre=os.environ.get("ADMIN_NOMBRE", "Administración"), email=email, rol="administrador")
    admin.set_contrasena(contrasena)
    db.session.add(admin)
    db.session.commit()
