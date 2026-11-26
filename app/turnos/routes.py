from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..auth.models import solo_personal
from ..extensions import db
from .indicadores import META_AUSENTISMO, ausentismo_registrado
from .models import Paciente, Prestacion, Profesional, Turno
from .services import ACTIVOS, ESTADOS, MODALIDADES, ahora, guardar_turno

bp = Blueprint("turnos", __name__, url_prefix="/panel/turnos")
bp.before_request(solo_personal)  # Solo personal

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


@bp.app_template_filter("fecha_larga")
def fecha_larga(fecha):
    return f"{DIAS[fecha.weekday()]} {fecha.strftime('%d/%m')}"


def _volver(turno=None):
    """Volver a agenda."""
    destino = request.form.get("volver", "")
    if destino.startswith("/panel/turnos/"):  # Redirección interna
        return redirect(destino, 303)
    if turno is not None:
        return redirect(url_for("turnos.lista", vista="dia", fecha=turno.fecha.isoformat(), resaltar=turno.id), 303)
    return redirect(url_for("turnos.lista"), 303)


def _formulario(datos, turno=None, status=200):
    hoy = ahora().date()
    # Horarios ocupados
    ocupados = Turno.query.filter(Turno.estado != "cancelado", Turno.fecha >= hoy)
    if turno is not None:
        ocupados = ocupados.filter(Turno.id != turno.id)
    ocupados = [
        {
            "profesional": t.profesional_id,
            "fecha": t.fecha.isoformat(),
            "hora": t.hora.strftime("%H:%M"),
            "paciente": f"{t.paciente.apellido}, {t.paciente.nombre}",
            "prestacion": t.prestacion.nombre,
            "contraturno": t.es_contraturno,
        }
        for t in ocupados.order_by(Turno.hora, Turno.posicion)
    ]
    # RF-07 pacientes
    pacientes = {
        p.dni: {"nombre": p.nombre, "apellido": p.apellido, "telefono": p.telefono or ""} for p in Paciente.query
    }
    profesionales = Profesional.query.order_by(Profesional.apellido).all()
    prestaciones = Prestacion.query.order_by(Prestacion.tipo, Prestacion.nombre).all()
    return render_template(
        "turnos/form.html",
        datos=datos,
        turno=turno,
        profesionales=profesionales,
        prestaciones=prestaciones,
        # Compatibilidades
        realiza={p.id: [x.id for x in p.prestaciones] for p in profesionales},
        admite_video={p.id: p.admite_videoconsulta for p in prestaciones},
        estados=ESTADOS,
        modalidades=MODALIDADES,
        ocupados=ocupados,
        pacientes=pacientes,
        hoy=hoy,
    ), status


@bp.get("/")
def lista():
    hoy = ahora().date()
    vista = "dia" if request.args.get("vista") == "dia" else "todos"
    try:
        fecha = date.fromisoformat(request.args.get("fecha", ""))
    except ValueError:
        fecha = hoy
    profesional = request.args.get("profesional", "")

    consulta = Turno.query
    if profesional.isdigit():
        consulta = consulta.filter_by(profesional_id=int(profesional))
    proximo = None
    if vista == "dia":
        turnos = consulta.filter_by(fecha=fecha).order_by(Turno.hora, Turno.posicion).all()
        if not turnos:
            proximo = consulta.filter(Turno.fecha > fecha).order_by(Turno.fecha).first()
    else:
        turnos = consulta.order_by(Turno.fecha, Turno.hora, Turno.posicion).all()

    ausentismo, cerrados = ausentismo_registrado()
    return render_template(
        "turnos/lista.html",
        turnos=turnos,
        vista=vista,
        fecha=fecha,
        hoy=hoy,
        dia_anterior=date.fromordinal(fecha.toordinal() - 1),
        dia_siguiente=date.fromordinal(fecha.toordinal() + 1),
        profesional=profesional,
        profesionales=Profesional.query.order_by(Profesional.apellido).all(),
        proximo=proximo,
        activos=ACTIVOS,
        resaltar=request.args.get("resaltar", type=int),
        a_cerrar=sum(1 for t in turnos if t.estado in ACTIVOS and t.fecha < hoy),
        ausentismo=ausentismo,
        cerrados=cerrados,
        meta=META_AUSENTISMO,
    )


@bp.get("/nuevo")
def nuevo():
    # Precarga
    datos = {k: v for k, v in request.args.items()
             if k in ("fecha", "hora", "profesional_id", "prestacion_id", "es_contraturno")}
    return _formulario(datos)


@bp.post("/")
def crear():
    try:
        turno = guardar_turno(request.form)
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
        return _formulario(request.form, status=400)
    flash("Turno creado.", "ok")
    return _volver(turno)


@bp.get("/<int:id>/editar")
def editar(id):
    turno = db.get_or_404(Turno, id)
    datos = {
        "dni": turno.paciente.dni,
        "nombre": turno.paciente.nombre,
        "apellido": turno.paciente.apellido,
        "telefono": turno.paciente.telefono or "",
        "profesional_id": str(turno.profesional_id),
        "prestacion_id": str(turno.prestacion_id),
        "fecha": turno.fecha.isoformat(),
        "hora": turno.hora.strftime("%H:%M"),
        "modalidad": turno.modalidad,
        "estado": turno.estado,
        "es_contraturno": "on" if turno.es_contraturno else "",
    }
    return _formulario(datos, turno)


@bp.put("/<int:id>")
def actualizar(id):
    turno = db.get_or_404(Turno, id)
    estado_anterior = turno.estado
    try:
        guardar_turno(request.form, turno)
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
        return _formulario(request.form, turno, status=400)
    if turno.estado != estado_anterior:
        flash(f"Turno de {turno.paciente.apellido} marcado como «{turno.estado}».", "ok")
    else:
        flash("Turno actualizado.", "ok")
    return _volver(turno)


@bp.delete("/<int:id>")
def eliminar(id):
    db.session.delete(db.get_or_404(Turno, id))
    db.session.commit()
    flash("Turno eliminado.", "ok")
    return _volver()
