"""Sitio de pacientes."""
import calendar
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..turnos.disponibilidad import libres_por_dia, profesionales_para
from ..turnos.models import DIAS, MESES, Prestacion, Profesional, Turno
from ..turnos.services import (ACTIVOS, VENTANA_MAXIMA, _buscar, ahora, cancelar_como_paciente, guardar_turno,
                               puede_cancelar)

bp = Blueprint("publico", __name__)

# Datos del consultorio
CONSULTORIO = {
    "nombre": "Consultorio SetFe",
    "lema": "Atención cercana y estudios en el día. Sacá tu turno por internet en 3 pasos y sin esperar en el teléfono.",
    "direccion": "Belisario Roldán, B1856 Glew, Provincia de Buenos Aires",
    "telefono": "+54 9 11 0000-0000",
    "whatsapp": "+54 9 11 0000-0000",
    "email": "turnos@consultoriosetfe.com.ar",
    "indicaciones": "Presentate 5 minutos antes con tu DNI.",
}


@bp.app_context_processor
def datos_del_consultorio():
    return {"consultorio": CONSULTORIO, "anio": ahora().year}


@bp.app_template_filter("fecha_completa")
def fecha_completa(fecha):
    return f"{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]}"


@bp.app_template_filter("pesos")
def pesos(importe):
    return "$" + f"{int(importe):,}".replace(",", ".")


@bp.get("/")
def inicio():
    return render_template(
        "publico/inicio.html",
        prestaciones=Prestacion.query.order_by(Prestacion.id).all(),
        profesionales=Profesional.query.order_by(Profesional.id).all(),
    )


def _mes(valor, hoy, limite):
    """Mes del calendario."""
    try:
        mes = datetime.strptime(valor or "", "%Y-%m").date()
    except ValueError:
        mes = hoy
    return min(max(mes.replace(day=1), hoy.replace(day=1)), limite.replace(day=1))


def _horas(espacios):
    return [e.strftime("%H:%M") for e in espacios]


@bp.get("/reservar")
def reservar():
    prestacion = _buscar(Prestacion, request.args.get("prestacion"))
    if prestacion is None:  # Paso 1
        return render_template("publico/reservar_prestacion.html",
                               prestaciones=Prestacion.query.order_by(Prestacion.id).all())

    profesionales = profesionales_para(prestacion)
    if not profesionales:
        return render_template("publico/reservar_calendario.html", prestacion=prestacion, profesional=None)
    profesional = next((p for p in profesionales if str(p.id) == request.args.get("profesional")), profesionales[0])

    hoy, limite = ahora().date(), (ahora() + VENTANA_MAXIMA).date()
    mes = _mes(request.args.get("mes"), hoy, limite)
    fin_de_mes = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
    libres = libres_por_dia(profesional, max(mes, hoy), min(fin_de_mes, limite))
    try:
        fecha = date.fromisoformat(request.args.get("fecha", ""))
    except ValueError:
        fecha = None
    if fecha not in libres:
        fecha = None
    hora = request.args.get("hora")
    base = {"prestacion": prestacion.id, "profesional": profesional.id}

    if fecha and hora in _horas(libres[fecha]):  # Paso 3
        if not current_user.is_authenticated:
            flash("Ingresá o creá tu cuenta para confirmar el turno. Te guardamos lo que elegiste.", "info")
            return redirect(url_for("auth.login", next=request.full_path))
        if current_user.es_personal:  # Personal al panel
            return redirect(url_for("turnos.nuevo", fecha=fecha.isoformat(), hora=hora, profesional_id=profesional.id,
                                    prestacion_id=prestacion.id))
        return render_template(
            "publico/reservar_confirmar.html", prestacion=prestacion, profesional=profesional, fecha=fecha, hora=hora,
            paciente=current_user.paciente,
            volver=url_for(".reservar", **base, mes=mes.strftime("%Y-%m"), fecha=fecha.isoformat()),
        )

    anterior = (mes - timedelta(days=1)).replace(day=1)
    siguiente = fin_de_mes + timedelta(days=1)
    return render_template(  # Paso 2
        "publico/reservar_calendario.html",
        prestacion=prestacion, profesional=profesional, profesionales=profesionales, base=base,
        mes=mes, nombre_mes=f"{MESES[mes.month - 1].capitalize()} de {mes.year}",
        semanas=calendar.Calendar().monthdatescalendar(mes.year, mes.month), libres=libres, hoy=hoy,
        mes_anterior=anterior.strftime("%Y-%m") if anterior >= hoy.replace(day=1) else None,
        mes_siguiente=siguiente.strftime("%Y-%m") if siguiente <= limite else None,
        fecha=fecha, horas=_horas(libres[fecha]) if fecha else [],
        hay_libres=any(libres.values()),
    )


@bp.post("/reservar")
@login_required
def confirmar():
    paciente = None if current_user.es_personal else current_user.paciente
    if paciente is None:
        abort(403)
    prestacion = _buscar(Prestacion, request.form.get("prestacion_id"))
    profesional = _buscar(Profesional, request.form.get("profesional_id"))
    try:
        fecha = date.fromisoformat(request.form.get("fecha", ""))
    except ValueError:
        fecha = None
    hora = request.form.get("hora", "")
    # Horario ofrecido
    ofrecido = (prestacion and profesional and fecha and profesional in profesionales_para(prestacion)
                and hora in _horas(libres_por_dia(profesional, fecha, fecha)[fecha]))
    if not ofrecido:
        flash("Ese horario ya no está disponible. Elegí otro.", "error")
        return redirect(url_for(".reservar", prestacion=prestacion.id if prestacion else None), 303)
    datos = {
        "dni": paciente.dni, "nombre": paciente.nombre, "apellido": paciente.apellido,
        "telefono": paciente.telefono or "", "profesional_id": str(profesional.id),
        "prestacion_id": str(prestacion.id), "fecha": fecha.isoformat(), "hora": hora,
        "modalidad": "videoconsulta" if request.form.get("modalidad") == "videoconsulta" else "presencial",
        "estado": "pendiente",
    }
    try:
        turno = guardar_turno(datos, canal="web")
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
        return redirect(url_for(".reservar", prestacion=prestacion.id, profesional=profesional.id,
                                mes=fecha.strftime("%Y-%m"), fecha=fecha.isoformat()), 303)
    flash("¡Listo! Tu turno quedó reservado.", "ok")
    return redirect(url_for(".comprobante", token=turno.token_comprobante), 303)


@bp.get("/mis-turnos")
@login_required
def mis_turnos():
    if current_user.es_personal:
        return redirect(url_for("turnos.lista"))
    paciente = current_user.paciente
    turnos = Turno.query.filter_by(paciente_id=paciente.id).order_by(Turno.fecha, Turno.hora).all() if paciente else []
    hoy = ahora().date()
    proximos = [t for t in turnos if t.fecha >= hoy and t.estado in ACTIVOS]
    anteriores = [t for t in reversed(turnos) if t not in proximos]
    return render_template("publico/mis_turnos.html", proximos=proximos, anteriores=anteriores)


def _turno_visible(token):
    """Control de acceso."""
    turno = Turno.query.filter_by(token_comprobante=token).first()
    propio = turno is not None and current_user.paciente is not None and turno.paciente_id == current_user.paciente.id
    if turno is None or not (propio or current_user.es_personal):
        abort(404)
    return turno


def _google_calendar(turno):
    inicio = datetime.combine(turno.fecha, turno.hora)
    fin = inicio + timedelta(minutes=turno.duracion)
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE",
        "text": f"Turno: {turno.prestacion.nombre} · {CONSULTORIO['nombre']}",
        "dates": f"{inicio:%Y%m%dT%H%M%S}/{fin:%Y%m%dT%H%M%S}",
        "ctz": "America/Argentina/Buenos_Aires",
        "details": f"Con {turno.profesional.nombre_publico}. Código {turno.token_comprobante[:8].upper()}.",
        "location": CONSULTORIO["direccion"],
    })


@bp.get("/mis-turnos/<token>")
@login_required
def comprobante(token):
    turno = _turno_visible(token)
    return render_template("publico/comprobante.html", turno=turno, puede_cancelar=puede_cancelar(turno),
                           google=_google_calendar(turno))


@bp.patch("/mis-turnos/<token>")
@login_required
def cancelar(token):
    turno = _turno_visible(token)
    try:
        cancelar_como_paciente(turno)
    except ValueError as error:
        flash(str(error), "error")
    else:
        flash("Tu turno fue cancelado. ¡Gracias por avisar!", "ok")
    return redirect(url_for(".comprobante", token=token), 303)
