"""RF-05 disponibilidad."""
from datetime import datetime, timedelta

from .models import Profesional, Turno
from .services import ANTICIPACION_MINIMA, VENTANA_MAXIMA, ahora


def _espacios(franjas, fecha):
    for franja in franjas:
        if franja.dia_semana != fecha.weekday():
            continue
        inicio = datetime.combine(fecha, franja.hora_desde)
        fin = datetime.combine(fecha, franja.hora_hasta)
        while inicio + timedelta(minutes=franja.duracion) <= fin:
            yield inicio
            inicio += timedelta(minutes=franja.duracion + franja.intervalo)


def libres_por_dia(profesional, desde, hasta):
    """Libres por día."""
    minimo, maximo = ahora() + ANTICIPACION_MINIMA, ahora() + VENTANA_MAXIMA
    # Simplificación: hora exacta
    tomados = {
        (t.fecha, t.hora) for t in Turno.query.filter(
            Turno.profesional_id == profesional.id, Turno.fecha.between(desde, hasta), Turno.estado != "cancelado")
    }
    dias, fecha = {}, desde
    while fecha <= hasta:
        dias[fecha] = [e for e in _espacios(profesional.franjas, fecha)
                       if minimo <= e <= maximo and (fecha, e.time()) not in tomados]
        fecha += timedelta(days=1)
    return dias


def profesionales_para(prestacion):
    """Profesionales con franjas."""
    return [p for p in Profesional.query.order_by(Profesional.id) if prestacion in p.prestaciones and p.franjas]
