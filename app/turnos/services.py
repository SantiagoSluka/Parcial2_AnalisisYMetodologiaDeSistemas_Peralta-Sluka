"""Gestor de turnos."""
import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from .models import Franja, Paciente, Prestacion, Profesional, Turno, profesional_prestacion

ESTADOS = ["pendiente", "confirmado", "atendido", "ausente", "cancelado"]  # estado_turno (6.2.4)
ACTIVOS = ("pendiente", "confirmado")
MODALIDADES = ["presencial", "videoconsulta"]  # modalidad (6.2.4)
ANTICIPACION_MINIMA = timedelta(hours=2)  # AL-08
VENTANA_MAXIMA = timedelta(days=60)  # AL-08
ANTICIPACION_CANCELACION = timedelta(hours=4)  # AL-08 cancelación
TOPE_ACTIVOS = 2  # AL-08
NOMBRE_VALIDO = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{1,60}")  # nombre / apellido (6.2.4)
# Simplificación: UTC-3
HORA_ARGENTINA = timezone(timedelta(hours=-3))


def ahora():
    # Hora Argentina
    return datetime.now(HORA_ARGENTINA).replace(tzinfo=None)


def _buscar(modelo, valor):
    return db.session.get(modelo, int(valor)) if valor and valor.isdigit() else None


def guardar_turno(form, turno=None, canal="panel"):
    """Alta o modificación."""
    dni = form.get("dni", "").strip()
    nombre = form.get("nombre", "").strip()
    apellido = form.get("apellido", "").strip()
    telefono = form.get("telefono", "").strip() or None
    if not re.fullmatch(r"\d{7,8}", dni):
        raise ValueError("El DNI debe tener 7 u 8 dígitos, sin puntos.")
    if not (NOMBRE_VALIDO.fullmatch(nombre) and NOMBRE_VALIDO.fullmatch(apellido)):
        raise ValueError("Nombre y apellido: solo letras, espacios, ' o -, hasta 60 caracteres.")
    if telefono and not re.fullmatch(r"\d{10}", telefono):
        raise ValueError("El teléfono debe tener 10 dígitos (característica + número, sin 0 ni 15).")
    profesional = _buscar(Profesional, form.get("profesional_id"))
    prestacion = _buscar(Prestacion, form.get("prestacion_id"))
    if not profesional or not prestacion:
        raise ValueError("Elegí un profesional y una prestación.")
    try:
        fecha = date.fromisoformat(form.get("fecha", ""))
        hora = time.fromisoformat(form.get("hora", ""))
    except ValueError:
        raise ValueError("Fecha u hora inválida.") from None
    estado = form.get("estado", "pendiente")
    modalidad = form.get("modalidad", "")
    if estado not in ESTADOS or modalidad not in MODALIDADES:
        raise ValueError("Estado o modalidad inválidos.")

    # D3 y D1
    nuevo_servicio = turno is None or (turno.profesional_id, turno.prestacion_id, turno.modalidad) != (
        profesional.id, prestacion.id, modalidad)
    if nuevo_servicio:
        if prestacion not in profesional.prestaciones:
            raise ValueError(f"{profesional.apellido}, {profesional.nombre} no realiza {prestacion.nombre}.")
        if modalidad == "videoconsulta" and not prestacion.admite_videoconsulta:
            raise ValueError(f"{prestacion.nombre} no admite videoconsulta: elegí la modalidad presencial.")

    # RF-07 identificación
    paciente = Paciente.query.filter_by(dni=dni).first()
    if paciente and paciente.apellido.lower() != apellido.lower():
        raise ValueError("Ese DNI ya está registrado con otro apellido.")

    # RF-08 reglas
    nuevo_horario = turno is None or (turno.profesional_id, turno.fecha, turno.hora) != (profesional.id, fecha, hora)
    if nuevo_horario:
        inicio = datetime.combine(fecha, hora)
        if inicio < ahora() + ANTICIPACION_MINIMA:
            raise ValueError("El turno debe darse con al menos 2 horas de anticipación.")
        if inicio > ahora() + VENTANA_MAXIMA:
            raise ValueError("No se pueden dar turnos con más de 60 días de anticipación.")
    if estado in ACTIVOS and paciente:
        activos = Turno.query.filter(Turno.paciente_id == paciente.id, Turno.estado.in_(ACTIVOS))
        if turno:
            activos = activos.filter(Turno.id != turno.id)
        if activos.count() >= TOPE_ACTIVOS:
            raise ValueError(f"El paciente ya tiene {TOPE_ACTIVOS} turnos activos (pendientes o confirmados).")

    # RNF-03 contra-turno
    reactivado = turno is not None and turno.estado == "cancelado" and estado != "cancelado"
    liberar = None
    if nuevo_horario or reactivado:
        otros = Turno.query.filter(Turno.profesional_id == profesional.id, Turno.fecha == fecha, Turno.hora == hora)
        if turno is not None and turno.id is not None:
            otros = otros.filter(Turno.id != turno.id)
        if estado == "cancelado":  # Cancelado movido
            ocupado = False
            posicion = (max((t.posicion for t in otros), default=0)) + 1
        else:
            en_uso = otros.filter(Turno.estado != "cancelado")
            ocupado = en_uso.count() > 0
            if ocupado and form.get("es_contraturno") != "on":
                raise ValueError('El horario seleccionado ya posee un turno. Para guardarlo, marcá "Es contra-turno".')
            # Próxima posición
            posicion = (max((t.posicion for t in en_uso), default=0)) + 1
            # Liberar posición
            liberar = otros.filter(Turno.estado == "cancelado", Turno.posicion == posicion).first()

    if paciente is None:
        paciente = Paciente(dni=dni, nombre=nombre, apellido=apellido, telefono=telefono)
        db.session.add(paciente)
    else:
        paciente.nombre, paciente.telefono = nombre, telefono  # Actualizar paciente
    if liberar is not None:
        ultima = db.session.query(db.func.max(Turno.posicion)).filter(
            Turno.profesional_id == profesional.id, Turno.fecha == fecha, Turno.hora == hora).scalar()
        liberar.posicion = max(ultima, turno.posicion if turno is not None and turno.posicion else 0) + 1
        db.session.flush()  # Flush previo
    if turno is None:
        turno = Turno(canal=canal)  # Canal
        db.session.add(turno)
    turno.paciente, turno.profesional, turno.prestacion = paciente, profesional, prestacion
    turno.estado, turno.modalidad = estado, modalidad
    if nuevo_horario or reactivado:
        turno.fecha, turno.hora, turno.posicion, turno.es_contraturno = fecha, hora, posicion, ocupado
    try:
        db.session.commit()
    except IntegrityError:  # Concurrencia
        db.session.rollback()
        raise ValueError("Ese horario o DNI se acaba de registrar desde otra sesión. Revisá y volvé a intentar.") from None
    return turno


def puede_cancelar(turno):
    """RF-11 cancelación."""
    inicio = datetime.combine(turno.fecha, turno.hora)
    return turno.estado in ACTIVOS and inicio - ahora() >= ANTICIPACION_CANCELACION


def cancelar_como_paciente(turno):
    if not puede_cancelar(turno):
        raise ValueError("Este turno ya no se puede cancelar desde la web: comunicate con el consultorio.")
    turno.estado = "cancelado"  # Horario liberado
    db.session.commit()


# Prestaciones de ejemplo
PRESTACIONES = [
    dict(nombre="Médico de familia", tipo="consulta", precio=15000, admite_videoconsulta=True, icono="🩺",
         color="#0f766e", descripcion="Control general, recetas, certificados y seguimiento de tu salud. "
                                      "Si no sabés a qué especialista ir, empezá por acá."),
    dict(nombre="Pediatría", tipo="consulta", precio=18000, admite_videoconsulta=True, icono="👶", color="#0284c7",
         descripcion="Control y atención de bebés, niños y adolescentes hasta los 18 años."),
    dict(nombre="Alergia e Inmunología", tipo="consulta", precio=20000, admite_videoconsulta=True, icono="🤧",
         color="#65a30d", descripcion="Estudio y tratamiento de alergias: rinitis, asma, urticaria y reacciones "
                                      "a alimentos o medicamentos."),
    dict(nombre="Ecografías", tipo="estudio", precio=25000, icono="📡", color="#7c3aed",
         descripcion="Estudio por imágenes para ver los órganos por dentro. No duele y no usa radiación."),
    dict(nombre="Electrocardiograma", tipo="estudio", precio=12000, icono="🫀", color="#dc2626",
         descripcion="Registra la actividad eléctrica del corazón. Dura pocos minutos, no duele y no necesita "
                     "preparación."),
    dict(nombre="Espirometría", tipo="estudio", precio=16000, icono="🫁", color="#0891b2",
         descripcion="Mide cuánto aire podés soplar. Sirve para evaluar asma, EPOC y otros problemas para respirar."),
    dict(nombre="Psicología", tipo="consulta", precio=22000, admite_videoconsulta=True, icono="💬", color="#8b5cf6",
         descripcion="Espacio de escucha y acompañamiento con una profesional de salud mental."),
]

# Realiza (bases viejas)
REALIZA = {
    "Clínica médica": ["Consulta clínica", "Ecografía abdominal", "Electrocardiograma"],
    "Pediatría": ["Consulta pediátrica"],
    "Psicología": ["Sesión de psicología"],
}


def cargar_datos_iniciales():
    """Datos de ejemplo."""
    if not Profesional.query.first():
        prestaciones = [Prestacion(**datos) for datos in PRESTACIONES]
        dra = Profesional(titulo="Dra.", nombre="Fernanda", apellido="Modarelli", especialidad="Medicina general",
                          frase="Atención cercana para toda la familia, con estudios en el mismo consultorio.")
        # Placeholder
        lic = Profesional(titulo="Lic.", nombre="Apellido", apellido="Nombre", especialidad="Psicología")
        dra.prestaciones = [p for p in prestaciones if p.nombre != "Psicología"]
        lic.prestaciones = [p for p in prestaciones if p.nombre == "Psicología"]
        # Lunes a viernes
        dra.franjas = [Franja(dia_semana=dia, hora_desde=time(desde), hora_hasta=time(hasta), duracion=20)
                       for dia in range(5) for desde, hasta in ((9, 13), (16, 20))]
        # Psicología: martes, jueves
        lic.franjas = [Franja(dia_semana=dia, hora_desde=time(14), hora_hasta=time(18), duracion=50, intervalo=10)
                       for dia in (1, 3)]
        db.session.add_all([*prestaciones, dra, lic])
        db.session.flush()
    # Bases viejas
    if not db.session.query(profesional_prestacion).first():
        por_nombre = {p.nombre: p for p in Prestacion.query}
        for profesional in Profesional.query:
            nombres = REALIZA.get(profesional.especialidad)
            profesional.prestaciones = (
                [por_nombre[n] for n in nombres if n in por_nombre] if nombres else list(por_nombre.values())
            )
    db.session.commit()
