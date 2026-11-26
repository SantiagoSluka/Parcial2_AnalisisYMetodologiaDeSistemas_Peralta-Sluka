"""Páginas de error."""
from flask import render_template, request
from werkzeug.exceptions import HTTPException

from .extensions import db

MENSAJES = {
    403: ("Esta sección es del personal del consultorio", "Desde tu cuenta podés sacar turnos y verlos en «Mis turnos»."),
    404: ("Esta página no existe", "Revisá la dirección e intentá de nuevo."),
    405: ("Esa acción no se puede hacer desde acá", "Usá los botones de la página para operar sobre los turnos."),
    500: ("Algo salió mal", "No se pudo completar la operación. Probá de nuevo en un momento."),
}


def _pantalla(codigo):
    titulo, mensaje = MENSAJES.get(codigo, ("No se pudo completar el pedido", "Volvé al inicio e intentá de nuevo."))
    if codigo == 404 and request.path.startswith(("/panel/turnos/", "/mis-turnos/")) \
            and request.path.rstrip("/") not in ("/panel/turnos", "/mis-turnos"):
        titulo, mensaje = "No encontramos ese turno", "Puede que se haya eliminado o que el enlace no sea correcto."
    return render_template("error.html", codigo=codigo, titulo=titulo, mensaje=mensaje), codigo


def registrar(app):
    @app.errorhandler(HTTPException)
    def error_http(error):
        if error.code is None or error.code < 400:  # Sin error
            return error
        return _pantalla(error.code)

    @app.errorhandler(500)
    def error_interno(error):
        db.session.rollback()  # Rollback
        return _pantalla(500)
