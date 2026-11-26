import os
import re
from pathlib import Path
from urllib.parse import parse_qs

import joblib
from dotenv import load_dotenv
from flask import Flask, redirect, url_for

from .errores import registrar as registrar_errores
from .extensions import db, login_manager

RAIZ = Path(__file__).resolve().parent.parent


class MethodOverride:
    """Override de verbos."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        if environ["REQUEST_METHOD"] == "POST":
            metodo = parse_qs(environ.get("QUERY_STRING", "")).get("_method", [""])[0].upper()
            if metodo in ("PUT", "PATCH", "DELETE"):
                environ["REQUEST_METHOD"] = metodo
        return self.wsgi_app(environ, start_response)


def create_app(config=None):
    load_dotenv()
    app = Flask(__name__)
    url_db = os.environ.get("DATABASE_URL") or "sqlite:///consultorio.db"
    app.config.update(
        SECRET_KEY=os.environ["SECRET_KEY"],
        # Driver psycopg2
        SQLALCHEMY_DATABASE_URI=re.sub(r"^postgres(ql)?://", "postgresql+psycopg2://", url_db),
        # Protección CSRF
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)
    app.wsgi_app = MethodOverride(app.wsgi_app)

    db.init_app(app)
    login_manager.init_app(app)

    from .auth.routes import bp as auth_bp
    from .prediccion.routes import bp as prediccion_bp
    from .publico.routes import bp as publico_bp
    from .turnos.routes import bp as turnos_bp

    app.register_blueprint(publico_bp)  # Sitio pacientes
    app.register_blueprint(auth_bp)
    app.register_blueprint(turnos_bp)  # Panel personal
    app.register_blueprint(prediccion_bp)
    registrar_errores(app)
    app.add_url_rule("/panel/", "panel", lambda: redirect(url_for("turnos.lista")))

    # Modelo IA
    app.extensions["modelo_ausentismo"] = joblib.load(RAIZ / "ml" / "modelo_ausentismo.joblib")

    with app.app_context():
        from .auth.models import crear_admin_desde_entorno
        from .esquema import actualizar_esquema
        from .turnos.services import cargar_datos_iniciales

        db.create_all()  # Tablas nuevas
        actualizar_esquema()  # Columnas nuevas
        cargar_datos_iniciales()
        crear_admin_desde_entorno()
    return app
