from flask import Blueprint, current_app, flash, render_template, request

from ..auth.models import solo_personal
from ..turnos.indicadores import AUSENTISMO_INICIAL, META_AUSENTISMO, ausentismo_registrado

bp = Blueprint("prediccion", __name__, url_prefix="/panel/prediccion")
bp.before_request(solo_personal)


@bp.route("/", methods=["GET", "POST"])
def ausentismo():
    probabilidad = None
    if request.method == "POST":
        try:
            dias = int(request.form.get("dias_anticipacion", ""))
            previas = int(request.form.get("ausencias_previas", ""))
        except ValueError:
            dias = previas = -1
        if not (0 <= dias <= 60 and 0 <= previas <= 50):
            flash("Días de anticipación: de 0 a 60. Ausencias previas: de 0 a 50.", "error")
        else:
            video = int(request.form.get("es_videoconsulta") == "on")
            pago = int(request.form.get("pago_online") == "on")
            # Orden de columnas
            modelo = current_app.extensions["modelo_ausentismo"]
            probabilidad = modelo.predict_proba([[dias, video, pago, previas]])[0][1]
    registrado, cerrados = ausentismo_registrado()
    return render_template(
        "prediccion/form.html",
        probabilidad=probabilidad,
        promedio=AUSENTISMO_INICIAL,
        meta=META_AUSENTISMO,
        registrado=registrado,
        cerrados=cerrados,
        datos=request.form,
    )
