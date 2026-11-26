"""Migración de columnas."""
from sqlalchemy import inspect, text

from .extensions import db
from .turnos.models import generar_token

# Tabla, columna, tipo
COLUMNAS_NUEVAS = [
    ("turno", "canal", "VARCHAR(8) NOT NULL DEFAULT 'panel'"),
    ("turno", "token_comprobante", "VARCHAR(32)"),
    ("prestacion", "admite_videoconsulta", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("usuario", "rol", "VARCHAR(13) NOT NULL DEFAULT 'recepcion'"),
    # Sitio público
    ("paciente", "usuario_id", "INTEGER"),
    ("prestacion", "descripcion", "VARCHAR(160)"),
    ("prestacion", "icono", "VARCHAR(8)"),
    ("prestacion", "color", "VARCHAR(7)"),
    ("profesional", "titulo", "VARCHAR(10)"),
    ("profesional", "frase", "VARCHAR(160)"),
]


def actualizar_esquema():
    inspector = inspect(db.engine)
    agregadas = set()
    for tabla, columna, definicion in COLUMNAS_NUEVAS:
        if columna not in {c["name"] for c in inspector.get_columns(tabla)}:
            db.session.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}"))
            agregadas.add(columna)
    if not agregadas:
        return

    if "token_comprobante" in agregadas:
        for (id_turno,) in db.session.execute(text("SELECT id FROM turno")).all():
            db.session.execute(
                text("UPDATE turno SET token_comprobante = :token WHERE id = :id"),
                {"token": generar_token(), "id": id_turno},
            )
        db.session.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ux_turno_token_comprobante ON turno (token_comprobante)")
        )
    if "admite_videoconsulta" in agregadas:
        # Estudios presenciales
        db.session.execute(text("UPDATE prestacion SET admite_videoconsulta = (tipo = 'consulta')"))
    if "rol" in agregadas:
        # Primer administrador
        db.session.execute(
            text("UPDATE usuario SET rol = 'administrador' WHERE id = (SELECT MIN(id) FROM usuario)")
        )
    db.session.commit()
