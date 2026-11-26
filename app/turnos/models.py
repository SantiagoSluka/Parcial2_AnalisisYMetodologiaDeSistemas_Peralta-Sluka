import secrets

from ..extensions import db

# D3 realiza
profesional_prestacion = db.Table(
    "profesional_prestacion",
    db.Column("profesional_id", db.Integer, db.ForeignKey("profesional.id"), primary_key=True),
    db.Column("prestacion_id", db.Integer, db.ForeignKey("prestacion.id"), primary_key=True),
)

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def generar_token():
    return secrets.token_hex(16)  # Token 32 caracteres


class Paciente(db.Model):  # D6 Pacientes
    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(8), unique=True, nullable=False)
    nombre = db.Column(db.String(60), nullable=False)
    apellido = db.Column(db.String(60), nullable=False)
    telefono = db.Column(db.String(10))
    # Cuenta web
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), unique=True)

    usuario = db.relationship("Usuario", backref=db.backref("paciente", uselist=False))


class Prestacion(db.Model):  # D1 Prestaciones
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(60), nullable=False)
    tipo = db.Column(db.String(8), nullable=False)  # consulta | estudio
    precio = db.Column(db.Numeric(11, 2), nullable=False)
    admite_videoconsulta = db.Column(db.Boolean, nullable=False, default=False)
    descripcion = db.Column(db.String(160))  # Texto público
    icono = db.Column(db.String(8))
    color = db.Column(db.String(7))  # Color hex


class Franja(db.Model):  # D4 Franjas
    id = db.Column(db.Integer, primary_key=True)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id"), nullable=False)
    dia_semana = db.Column(db.Integer, nullable=False)  # Lunes = 0
    hora_desde = db.Column(db.Time, nullable=False)
    hora_hasta = db.Column(db.Time, nullable=False)
    duracion = db.Column(db.Integer, nullable=False)  # Minutos turno
    intervalo = db.Column(db.Integer, nullable=False, default=0)  # Minutos descanso


class Profesional(db.Model):  # D3 Profesionales
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(60), nullable=False)
    apellido = db.Column(db.String(60), nullable=False)
    especialidad = db.Column(db.String(60), nullable=False)
    titulo = db.Column(db.String(10))  # Dra., Lic.
    frase = db.Column(db.String(160))  # Frase pública
    prestaciones = db.relationship(Prestacion, secondary=profesional_prestacion, order_by=Prestacion.nombre)
    franjas = db.relationship(Franja, order_by=(Franja.dia_semana, Franja.hora_desde))

    @property
    def nombre_publico(self):
        return f"{self.titulo or ''} {self.apellido} {self.nombre}".strip()

    @property
    def iniciales(self):
        return (self.apellido[:1] + self.nombre[:1]).upper()


class Turno(db.Model):  # D7 Turnos
    # RNF-03 unicidad
    __table_args__ = (db.UniqueConstraint("profesional_id", "fecha", "hora", "posicion"),)

    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("paciente.id"), nullable=False)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id"), nullable=False)
    prestacion_id = db.Column(db.Integer, db.ForeignKey("prestacion.id"), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    posicion = db.Column(db.Integer, nullable=False, default=1)  # Posición en horario
    es_contraturno = db.Column(db.Boolean, nullable=False, default=False)
    estado = db.Column(db.String(10), nullable=False, default="pendiente")
    modalidad = db.Column(db.String(13), nullable=False)
    canal = db.Column(db.String(8), nullable=False, default="panel")  # Canal (6.2.4)
    token_comprobante = db.Column(db.String(32), unique=True, nullable=False, default=generar_token)

    paciente = db.relationship(Paciente)
    profesional = db.relationship(Profesional)
    prestacion = db.relationship(Prestacion)

    @property
    def duracion(self):
        """Duración según franja."""
        return next((f.duracion for f in self.profesional.franjas
                     if f.dia_semana == self.fecha.weekday() and f.hora_desde <= self.hora < f.hora_hasta), 30)
