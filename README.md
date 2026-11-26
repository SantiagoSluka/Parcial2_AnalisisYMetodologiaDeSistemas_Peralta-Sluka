# ConsultorioSetFe — Prototipo (Parcial 2)

Versión mínima del sistema de gestión de turnos especificado en el SRS del Parcial 1
(Sluka · Peralta). Flask + SQLAlchemy + Jinja2, login con Bcrypt y un modelo de
regresión logística (scikit-learn) que estima el riesgo de ausencia de un turno.

**Aplicación en producción (Render + PostgreSQL):** https://consultorio-setfe.onrender.com

> Está en el plan gratuito de Render: si estuvo un rato sin visitas, la primera carga puede tardar unos 50 segundos.

Tiene dos partes:

- **Sitio público (pacientes)**: portada del consultorio, reserva en 3 pasos (prestación → día y horario →
  confirmar), cuenta del paciente y «Mis turnos» con comprobante y cancelación. Diseño tomado de la versión
  Laravel del consultorio.
- **Panel (`/panel`)**: agenda con alta manual, contra-turnos, reprogramación, cambios de estado y riesgo de
  ausencia con IA. Solo entra el personal (administrador o recepción); un paciente recibe un 403.

## Rutas principales

| Ruta | Quién | Qué hace |
|---|---|---|
| `/` | todos | Portada: qué atendemos, profesionales, cómo sacar turno, dónde estamos |
| `/reservar` | todos (confirmar pide cuenta) | Paso 1 prestación · paso 2 calendario con horarios libres · paso 3 confirmar |
| `/registro`, `/login`, `/logout` | todos | Cuenta del paciente (DNI, nombre, apellido, teléfono, email, contraseña) |
| `/mis-turnos`, `/mis-turnos/<token>` | paciente | Sus turnos, comprobante, Google Calendar y cancelación (PATCH) |
| `/panel/turnos/` | personal | CRUD de turnos: POST, GET, PUT, DELETE |
| `/panel/prediccion/` | personal | Predicción en tiempo real con el modelo `.joblib` |

## Trazabilidad con el SRS

| SRS | Dónde está en el código |
|---|---|
| D7 Turnos (canal, token_comprobante), D6 Pacientes, D3 Profesionales, D1 Prestaciones, D4 Franjas horarias | `app/turnos/models.py` |
| RF-05 horarios disponibles según franjas y turnos tomados | `app/turnos/disponibilidad.py` |
| RF-06 reserva web en 3 pasos · RF-09 comprobante con enlace privado · RF-10 consultar · RF-11 cancelar (hasta 4 h antes) | `app/publico/routes.py` |
| RF-07 paciente identificado por DNI + apellido (la cuenta se vincula al paciente cargado por el panel) | `app/auth/routes.py` + `app/turnos/services.py` |
| RF-08 / AL-08 anticipación 2 h, ventana 60 días, tope 2 turnos activos: **las mismas reglas para la web y el panel** | `guardar_turno` en `app/turnos/services.py` |
| RF-12 alta manual · RF-13 reprogramación · RF-14 cambio de estado | `app/turnos/routes.py` |
| RNF-03 un horario no se asigna dos veces · contra-turno (CU-08 4.a) | restricción única en `Turno` + `services.py` |
| D10 Usuarios con rol (administrador, recepción, paciente) · RNF-01 contraseñas con hash | `app/auth/` (Bcrypt) |
| O1 reducir el ausentismo del 22 % al 12 % | `ml/entrenar.py` + `app/prediccion/routes.py` |

**Fuera de este recorte:** variantes de estudios, Mercado Pago, Google Meet, WhatsApp, API con token, 2FA,
bitácora y el ABM de prestaciones, profesionales y franjas (se cargan de ejemplo al iniciar, en
`cargar_datos_iniciales`). Los datos del consultorio (dirección, teléfono, textos) están en `CONSULTORIO`,
en `app/publico/routes.py`.

## Cuentas

- **Pacientes**: se registran solos en `/registro`.
- **Administrador**: no hay registro público de personal. Al iniciar, la app crea el administrador con
  `ADMIN_EMAIL` y `ADMIN_PASSWORD` del `.env` si todavía no existe. Entra por «Acceso del consultorio» (pie de
  página) o por `/login`.

## Estructura

```
app/
  __init__.py      App Factory: config desde .env, Blueprints, carga del modelo, administrador inicial
  extensions.py    SQLAlchemy y Flask-Login
  auth/            Blueprint de login y registro (Usuario + Bcrypt, roles)
  publico/         Blueprint del sitio de los pacientes
  turnos/          Blueprint del panel: models, services (reglas del SRS), disponibilidad, routes
  prediccion/      Blueprint que usa el modelo .joblib
  templates/       Jinja2 (publico/ para el sitio, el resto para el panel)
  static/css/      publico.css (sitio) y app.css (panel)
ml/entrenar.py     entrena y guarda ml/modelo_ausentismo.joblib
run.py             punto de entrada (gunicorn run:app)
tests/             pruebas con unittest
```

Los formularios HTML solo envían GET y POST: para que el CRUD use PUT, PATCH y DELETE de verdad, los
formularios mandan `POST ...?_method=PUT` y un middleware (`MethodOverride` en `app/__init__.py`)
lo convierte en ese verbo. Con curl o Postman se pueden usar los verbos directamente.

## Correr en local (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Completar en `.env`: `SECRET_KEY` (generarla con `python -c "import secrets; print(secrets.token_hex(32))"`),
`ADMIN_EMAIL` y `ADMIN_PASSWORD`. Si `DATABASE_URL` queda vacío se usa SQLite en `instance/consultorio.db`.

```bash
python run.py
```

Abrir http://localhost:8000.

Tests: `python -m unittest`. Reentrenar el modelo: `python ml/entrenar.py`.

## Modelo de IA

Regresión logística que estima la probabilidad de que un turno termine en «ausente» a partir de:
días entre la reserva y el turno, si es videoconsulta, si pagó online y las ausencias previas del
paciente. Como el consultorio hoy no tiene historial digital (SRS 2.1), se entrena con datos
sintéticos generados con los supuestos del SRS (22 % de ausentismo, 15 % de pago online, quien
paga por adelantado falta la mitad). El modelo ya entrenado está en el repo y la app lo carga
una vez al iniciar.

## Deploy en Render

Desplegado en **https://consultorio-setfe.onrender.com**: Web Service `consultorio-setfe` (Python, `gunicorn run:app`)
y base PostgreSQL `consultorio-setfe-db`, creados desde el `render.yaml` y vinculados a este repositorio (cada push a
`main` se despliega solo).

**Con el Blueprint (`render.yaml`):** en Render, *New → Blueprint*, elegir este repositorio y completar
`ADMIN_EMAIL` y `ADMIN_PASSWORD`. Render crea la base PostgreSQL, el Web Service (`gunicorn run:app`) y genera
la `SECRET_KEY`.

**A mano:**

1. Crear una base **PostgreSQL** en Render y copiar su *Internal Database URL*.
2. Crear un **Web Service** conectado a este repositorio de GitHub:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn run:app`
   - Variables de entorno: `SECRET_KEY` (una clave nueva), `DATABASE_URL` (la URL del paso 1),
     `ADMIN_EMAIL` y `ADMIN_PASSWORD`.
3. Las tablas, los datos de ejemplo y el administrador se crean solos en el primer arranque. Si la base ya
   existía de una versión anterior, al iniciar se le agregan las columnas nuevas sin borrar datos
   (`app/esquema.py`).

La versión de Python la toma de `.python-version`.
