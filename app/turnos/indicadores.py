"""Indicadores O1."""
from .models import Turno

AUSENTISMO_INICIAL = 0.22  # O1 inicial
META_AUSENTISMO = 0.12  # O1 meta


def ausentismo_registrado():
    """Ausentismo registrado."""
    cerrados = Turno.query.filter(Turno.estado.in_(("atendido", "ausente"))).count()
    if not cerrados:
        return None, 0
    ausentes = Turno.query.filter_by(estado="ausente").count()
    return ausentes / cerrados, cerrados
