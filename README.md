# ConsultorioSetFe

Sistema web de gestión de turnos para el Consultorio SetFe. Es el prototipo del Parcial 2 de Análisis y
Metodología de Sistemas, desarrollado a partir del SRS del Parcial 1.

**Aplicación en línea:** https://consultorio-setfe.onrender.com

**Autores:** Santiago Sluka · Leonel Peralta

## Qué hace

**Para los pacientes**

- Ver las prestaciones del consultorio y los profesionales que atienden.
- Crear una cuenta con DNI, nombre, apellido, teléfono y email.
- Sacar turno en 3 pasos: prestación, día y horario, y confirmación.
- Consultar sus turnos, ver el comprobante y cancelar hasta 4 horas antes.

**Para el consultorio (panel de administración y recepción)**

- Agenda del día y general, con filtro por profesional.
- Alta manual de turnos, contra-turnos, reprogramación y cambios de estado
  (pendiente, confirmado, atendido, ausente, cancelado).
- Indicador de ausentismo y estimación del riesgo de ausencia de un turno con inteligencia artificial.

## Reglas del negocio

Tomadas del SRS y aplicadas por igual a los turnos de la web y del panel:

- Los turnos se dan con al menos 2 horas de anticipación y hasta 60 días hacia adelante.
- Cada paciente puede tener como máximo 2 turnos activos.
- Un horario no se asigna dos veces, salvo como contra-turno.
- Cada profesional atiende solo sus prestaciones, y los estudios son presenciales.

## Inteligencia artificial

Un modelo de regresión logística estima la probabilidad de que un turno termine en ausencia, según los días de
anticipación de la reserva, la modalidad, el pago anticipado y las ausencias previas del paciente. Responde al
objetivo O1 del SRS: bajar el ausentismo del 22 % al 12 %. Como el consultorio no tenía historial digital, se
entrenó con datos sintéticos generados a partir de los supuestos del SRS.

## Tecnologías

Python · Flask · SQLAlchemy · PostgreSQL · Jinja2 · Bcrypt · scikit-learn · Render
