import os
import sqlite3
import tempfile
import unittest
from datetime import timedelta

os.environ.setdefault("SECRET_KEY", "clave-de-test")
ADMIN = {"email": "admin@test.com", "contrasena": "clave-admin-123"}
os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"] = ADMIN["email"], ADMIN["contrasena"]

from app import create_app  # noqa: E402
from app.auth.models import Usuario  # noqa: E402
from app.extensions import db  # noqa: E402
from app.turnos.disponibilidad import libres_por_dia  # noqa: E402
from app.turnos.models import Paciente, Prestacion, Profesional, Turno  # noqa: E402
from app.turnos.services import ahora, guardar_turno  # noqa: E402

PACIENTE = {"dni": "35111222", "nombre": "Lucía", "apellido": "Sosa", "telefono": "1155551234",
            "email": "lucia@test.com", "contrasena": "secreta123"}


class Base(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite://"})
        self.client = self.app.test_client()
        self.client.post("/login", data=ADMIN)  # Login admin

    def tearDown(self):
        with self.app.app_context():
            db.engine.dispose()

    def datos_turno(self, **cambios):
        manana = (ahora() + timedelta(days=1)).date().isoformat()
        datos = {
            "dni": "30111222", "nombre": "Juan", "apellido": "Pérez", "telefono": "",
            "profesional_id": "1", "prestacion_id": "1", "fecha": manana, "hora": "10:00",
            "modalidad": "presencial", "estado": "pendiente",
        }
        return {**datos, **cambios}

    def turno(self, id):
        with self.app.app_context():
            return db.session.get(Turno, id)

    def registrar_paciente(self, **cambios):
        self.client.post("/logout")
        return self.client.post("/registro", data={**PACIENTE, **cambios})

    def primer_libre(self, profesional_id=1):
        with self.app.app_context():
            hoy = ahora().date()
            libres = libres_por_dia(db.session.get(Profesional, profesional_id), hoy, hoy + timedelta(days=14))
            fecha = next(f for f, espacios in libres.items() if espacios)
            return fecha.isoformat(), libres[fecha][0].strftime("%H:%M")


class PanelTest(Base):
    def test_contrasena_guardada_con_bcrypt(self):
        with self.app.app_context():
            usuario = Usuario.query.filter_by(email=ADMIN["email"]).one()
            self.assertEqual(usuario.rol, "administrador")
            self.assertTrue(usuario.contrasena.startswith("$2b$"))
            self.assertTrue(usuario.verificar_contrasena(ADMIN["contrasena"]))
            self.assertFalse(usuario.verificar_contrasena("otra-clave"))

    def test_login_y_rutas_protegidas(self):
        self.client.post("/logout")
        respuesta = self.client.get("/panel/turnos/")
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("/login", respuesta.location)
        self.assertIn(b"incorrectos", self.client.post("/login", data={**ADMIN, "contrasena": "mal"}).data)
        self.assertEqual(self.client.post("/login", data=ADMIN).status_code, 302)
        self.assertEqual(self.client.get("/panel/turnos/").status_code, 200)

    def test_crud_completo(self):
        self.assertEqual(self.client.post("/panel/turnos/", data=self.datos_turno()).status_code, 303)
        lista = self.client.get("/panel/turnos/").data
        self.assertIn(b"30111222", lista)
        # Verbo en URL
        self.assertIn(b'action="/panel/turnos/1?_method=DELETE"', lista)
        self.assertIn(b'action="/panel/turnos/1?_method=PUT"', self.client.get("/panel/turnos/1/editar").data)
        self.assertEqual(self.client.put("/panel/turnos/1", data=self.datos_turno(estado="confirmado")).status_code, 303)
        self.assertEqual(self.turno(1).estado, "confirmado")
        # Formulario HTML
        self.client.post("/panel/turnos/1?_method=PUT", data=self.datos_turno(hora="11:30"))
        self.assertEqual(self.turno(1).hora.strftime("%H:%M"), "11:30")
        self.assertEqual(self.client.delete("/panel/turnos/1").status_code, 303)
        self.assertIsNone(self.turno(1))

    def test_reglas_de_reserva(self):
        pronto = ahora() + timedelta(hours=1)
        lejos = ahora() + timedelta(days=61)
        for datos in (
            self.datos_turno(fecha=pronto.date().isoformat(), hora=pronto.strftime("%H:%M")),  # < 2 h
            self.datos_turno(fecha=lejos.date().isoformat()),  # > 60 días
            self.datos_turno(dni="123"),  # DNI inválido
        ):
            self.assertEqual(self.client.post("/panel/turnos/", data=datos).status_code, 400)

        # Tope activos
        self.client.post("/panel/turnos/", data=self.datos_turno(hora="10:00"))
        self.client.post("/panel/turnos/", data=self.datos_turno(hora="11:00"))
        self.assertEqual(self.client.post("/panel/turnos/", data=self.datos_turno(hora="12:00")).status_code, 400)

        # Contra-turno
        otro = {"dni": "40999888", "apellido": "López"}
        self.assertEqual(self.client.post("/panel/turnos/", data=self.datos_turno(**otro)).status_code, 400)
        respuesta = self.client.post("/panel/turnos/", data=self.datos_turno(**otro, es_contraturno="on"))
        self.assertEqual(respuesta.status_code, 303)
        self.assertEqual((self.turno(3).posicion, self.turno(3).es_contraturno), (2, True))

        # Apellido distinto
        datos = self.datos_turno(apellido="Otro", hora="15:00")
        self.assertEqual(self.client.post("/panel/turnos/", data=datos).status_code, 400)

    def test_prediccion(self):
        respuesta = self.client.post("/panel/prediccion/", data={"dias_anticipacion": "30", "ausencias_previas": "2"})
        self.assertIn("Probabilidad de ausencia".encode(), respuesta.data)
        bajo = self.app.extensions["modelo_ausentismo"].predict_proba([[1, 0, 1, 0]])[0][1]
        alto = self.app.extensions["modelo_ausentismo"].predict_proba([[60, 1, 0, 4]])[0][1]
        self.assertLess(bajo, alto)
        respuesta = self.client.post("/panel/prediccion/", data={"dias_anticipacion": "500", "ausencias_previas": "0"})
        self.assertIn(b"de 0 a 60", respuesta.data)

    def test_editar_corrige_datos_del_paciente(self):
        self.client.post("/panel/turnos/", data=self.datos_turno())
        self.client.put("/panel/turnos/1", data=self.datos_turno(nombre="Juan Carlos", telefono="1155551234"))
        with self.app.app_context():
            paciente = Paciente.query.one()
            self.assertEqual((paciente.nombre, paciente.telefono), ("Juan Carlos", "1155551234"))

    def test_turno_cancelado_libera_su_posicion(self):
        self.client.post("/panel/turnos/", data=self.datos_turno())
        self.client.put("/panel/turnos/1", data=self.datos_turno(estado="cancelado"))
        otro = {"dni": "40999888", "apellido": "López"}
        self.assertEqual(self.client.post("/panel/turnos/", data=self.datos_turno(**otro)).status_code, 303)
        self.assertEqual((self.turno(2).posicion, self.turno(2).es_contraturno), (1, False))
        # Reactivar cancelado
        self.assertEqual(self.client.put("/panel/turnos/1", data=self.datos_turno()).status_code, 400)
        self.client.put("/panel/turnos/1", data=self.datos_turno(es_contraturno="on"))
        self.assertEqual((self.turno(1).posicion, self.turno(1).es_contraturno), (2, True))

    def test_prestacion_del_profesional_y_modalidad(self):
        # Prestación incompatible
        datos = self.datos_turno(profesional_id="2", prestacion_id="4")
        self.assertEqual(self.client.post("/panel/turnos/", data=datos).status_code, 400)
        datos = self.datos_turno(prestacion_id="4", modalidad="videoconsulta")
        self.assertEqual(self.client.post("/panel/turnos/", data=datos).status_code, 400)
        datos = self.datos_turno(modalidad="videoconsulta")
        self.assertEqual(self.client.post("/panel/turnos/", data=datos).status_code, 303)

    def test_campos_del_diccionario(self):
        self.client.post("/panel/turnos/", data=self.datos_turno())
        self.assertEqual(self.turno(1).canal, "panel")
        self.assertRegex(self.turno(1).token_comprobante, r"^[0-9a-f]{32}$")
        self.registrar_paciente()
        with self.app.app_context():
            self.assertEqual([u.rol for u in Usuario.query.order_by(Usuario.id)], ["administrador", "paciente"])

    def test_login_y_registro_con_sesion_vuelven_al_panel(self):
        self.assertIn("/panel/turnos/", self.client.get("/login").location)
        self.assertIn("/panel/turnos/", self.client.get("/registro").location)

    def test_login_vuelve_a_la_pagina_pedida(self):
        self.client.post("/logout")
        respuesta = self.client.post("/login?next=%2Fpanel%2Fprediccion%2F", data=ADMIN)
        self.assertEqual(respuesta.location, "/panel/prediccion/")
        self.client.post("/logout")
        # Next externo
        self.assertEqual(self.client.post("/login?next=https%3A%2F%2Fotro.com", data=ADMIN).location, "/panel/turnos/")

    def test_pantallas_de_error(self):
        respuesta = self.client.get("/panel/turnos/999/editar")
        self.assertEqual(respuesta.status_code, 404)
        self.assertIn("No encontramos ese turno".encode(), respuesta.data)
        self.assertIn(b"app.css", respuesta.data)  # Diseño panel
        self.assertIn("Esta página no existe".encode(), self.client.get("/no-existe").data)
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.client.post("/logout")
        respuesta = self.client.get("/no-existe")
        self.assertIn("Volver al inicio".encode(), respuesta.data)
        self.assertIn(b"publico.css", respuesta.data)


class SitioPublicoTest(Base):
    def test_portada(self):
        self.client.post("/logout")
        pagina = self.client.get("/").data.decode()
        for texto in ("Qué atendemos", "Médico de familia", "Psicología", "Dra. Modarelli Fernanda",
                      "Sacar un turno es fácil", "Dónde estamos", "Acceso del consultorio"):
            self.assertIn(texto, pagina)

    def test_paciente_se_registra_reserva_y_cancela(self):
        self.client.post("/logout")
        self.assertIn("¿Qué necesitás?", self.client.get("/reservar").data.decode())
        self.assertIn("Elegí el día", self.client.get("/reservar?prestacion=1").data.decode())
        fecha, hora = self.primer_libre()
        paso3 = f"/reservar?prestacion=1&profesional=1&fecha={fecha}&hora={hora}"
        respuesta = self.client.get(paso3)  # Requiere cuenta
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("/login", respuesta.location)

        self.assertEqual(self.registrar_paciente().status_code, 302)
        self.assertIn("Confirmar mi turno", self.client.get(paso3).data.decode())
        respuesta = self.client.post("/reservar", data={"prestacion_id": "1", "profesional_id": "1", "fecha": fecha,
                                                        "hora": hora, "modalidad": "videoconsulta"})
        self.assertEqual(respuesta.status_code, 303)
        comprobante = respuesta.location
        self.assertTrue(comprobante.startswith("/mis-turnos/"))
        self.assertIn("Médico de familia", self.client.get(comprobante).data.decode())
        with self.app.app_context():
            turno = Turno.query.one()
            self.assertEqual((turno.canal, turno.modalidad, turno.paciente.usuario.email),
                             ("web", "videoconsulta", PACIENTE["email"]))
        self.assertIn(turno.token_comprobante[:8].upper(), self.client.get("/mis-turnos").data.decode())
        self.assertNotIn(hora, self.client.get(paso3.split("&hora=")[0]).data.decode().split("Horarios del")[1])

        self.assertEqual(self.client.patch(comprobante).status_code, 303)  # cancelar (RF-11)
        self.assertEqual(self.turno(turno.id).estado, "cancelado")

    def test_solo_se_reservan_horarios_que_ofrece_la_agenda(self):
        self.registrar_paciente()
        fecha, hora = self.primer_libre()
        for datos in (
            {"prestacion_id": "1", "profesional_id": "1", "fecha": fecha, "hora": "03:00"},  # fuera de franja
            {"prestacion_id": "1", "profesional_id": "2", "fecha": fecha, "hora": hora},  # No la realiza
        ):
            self.assertEqual(self.client.post("/reservar", data=datos).status_code, 303)
        with self.app.app_context():
            self.assertEqual(Turno.query.count(), 0)

    def test_registro_exige_telefono(self):
        for telefono in ("", "123", "01155551234"):
            respuesta = self.registrar_paciente(telefono=telefono)
            self.assertEqual(respuesta.status_code, 400)
            self.assertIn("teléfono", respuesta.data.decode())
        with self.app.app_context():
            self.assertIsNone(Usuario.query.filter_by(email=PACIENTE["email"]).first())

    def test_el_paciente_no_entra_al_panel(self):
        self.registrar_paciente()
        for ruta in ("/panel/turnos/", "/panel/prediccion/", "/panel/turnos/nuevo"):
            respuesta = self.client.get(ruta)
            self.assertEqual(respuesta.status_code, 403)
            self.assertIn("personal del consultorio", respuesta.data.decode())

    def test_registro_vincula_al_paciente_cargado_por_el_panel(self):
        self.client.post("/panel/turnos/", data=self.datos_turno())  # Pérez, 30111222
        respuesta = self.registrar_paciente(dni="30111222", apellido="Pérez", email="juan@test.com")
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("Médico de familia", self.client.get("/mis-turnos").data.decode())
        # Duplicados
        self.assertEqual(self.registrar_paciente(dni="30111222", apellido="Pérez", email="otro@test.com").status_code, 400)
        self.client.post("/login", data=ADMIN)
        self.client.post("/panel/turnos/", data=self.datos_turno(dni="40999888", apellido="López", hora="11:00"))
        respuesta = self.registrar_paciente(dni="40999888", apellido="Otro", email="otro@test.com")
        self.assertIn("otro apellido", respuesta.data.decode())

    def test_no_se_cancela_con_menos_de_4_horas(self):
        self.registrar_paciente()
        pronto = ahora() + timedelta(hours=3)
        with self.app.app_context():
            turno = guardar_turno({**self.datos_turno(dni=PACIENTE["dni"], apellido=PACIENTE["apellido"]),
                                   "fecha": pronto.date().isoformat(), "hora": pronto.strftime("%H:%M")})
            token, id_turno = turno.token_comprobante, turno.id
        self.assertNotIn("Cancelar mi turno", self.client.get(f"/mis-turnos/{token}").data.decode())
        self.client.patch(f"/mis-turnos/{token}")
        self.assertEqual(self.turno(id_turno).estado, "pendiente")

    def test_comprobante_ajeno_no_se_ve(self):
        self.client.post("/panel/turnos/", data=self.datos_turno())
        token = self.turno(1).token_comprobante
        self.registrar_paciente()
        self.assertEqual(self.client.get(f"/mis-turnos/{token}").status_code, 404)
        self.assertEqual(self.client.patch(f"/mis-turnos/{token}").status_code, 404)

    def test_disponibilidad_respeta_las_franjas(self):
        with self.app.app_context():
            hoy = ahora().date()
            martes = hoy + timedelta(days=7 + (1 - hoy.weekday()) % 7)
            psicologa, dra = db.session.get(Profesional, 2), db.session.get(Profesional, 1)
            horas = lambda p: [e.strftime("%H:%M") for e in libres_por_dia(p, martes, martes)[martes]]  # noqa: E731
            self.assertEqual(horas(psicologa), ["14:00", "15:00", "16:00", "17:00"])  # Sesiones de 50
            self.assertEqual(len(horas(dra)), 24)  # Grilla 20 min
            self.assertEqual((horas(dra)[0], horas(dra)[-1]), ("09:00", "19:40"))
            self.assertEqual(libres_por_dia(dra, martes + timedelta(days=4), martes + timedelta(days=4)),
                             {martes + timedelta(days=4): []})  # sábado: sin franjas


class BaseAnteriorTest(unittest.TestCase):
    """Base vieja."""

    def test_agrega_columnas_sin_perder_datos(self):
        carpeta = tempfile.mkdtemp()
        ruta = os.path.join(carpeta, "vieja.db")
        con = sqlite3.connect(ruta)
        con.executescript("""
            CREATE TABLE usuario (id INTEGER PRIMARY KEY, nombre VARCHAR(60) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE,
                                  contrasena VARCHAR(60) NOT NULL);
            CREATE TABLE paciente (id INTEGER PRIMARY KEY, dni VARCHAR(8) NOT NULL UNIQUE, nombre VARCHAR(60) NOT NULL,
                                   apellido VARCHAR(60) NOT NULL, telefono VARCHAR(10));
            CREATE TABLE profesional (id INTEGER PRIMARY KEY, nombre VARCHAR(60) NOT NULL, apellido VARCHAR(60) NOT NULL,
                                      especialidad VARCHAR(60) NOT NULL);
            CREATE TABLE prestacion (id INTEGER PRIMARY KEY, nombre VARCHAR(60) NOT NULL, tipo VARCHAR(8) NOT NULL,
                                     precio NUMERIC(11, 2) NOT NULL);
            CREATE TABLE turno (id INTEGER PRIMARY KEY, paciente_id INTEGER NOT NULL, profesional_id INTEGER NOT NULL,
                                prestacion_id INTEGER NOT NULL, fecha DATE NOT NULL, hora TIME NOT NULL, posicion INTEGER NOT NULL,
                                es_contraturno BOOLEAN NOT NULL, estado VARCHAR(10) NOT NULL, modalidad VARCHAR(13) NOT NULL,
                                UNIQUE (profesional_id, fecha, hora, posicion));
            INSERT INTO usuario VALUES (1, 'Demo', 'demo@test.com', 'x'), (2, 'Otro', 'otro@test.com', 'x');
            INSERT INTO paciente VALUES (1, '30111222', 'Juan', 'Pérez', NULL);
            INSERT INTO profesional VALUES (1, 'Laura', 'Gómez', 'Clínica médica'), (2, 'Martín', 'Ruiz', 'Pediatría');
            INSERT INTO prestacion VALUES (1, 'Consulta clínica', 'consulta', 20000), (2, 'Ecografía abdominal', 'estudio', 35000);
            INSERT INTO turno VALUES (1, 1, 1, 2, '2026-01-10', '10:30:00.000000', 1, 0, 'confirmado', 'videoconsulta');
        """)
        con.close()
        app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{ruta}"})
        with app.app_context():
            turno = db.session.get(Turno, 1)
            self.assertEqual((turno.canal, turno.estado, len(turno.token_comprobante)), ("panel", "confirmado", 32))
            self.assertIsNone(turno.paciente.usuario)
            # Admin al final
            self.assertEqual([u.rol for u in Usuario.query.order_by(Usuario.id)],
                             ["administrador", "recepcion", "administrador"])
            gomez, ruiz = Profesional.query.order_by(Profesional.id)
            self.assertEqual([p.nombre for p in gomez.prestaciones], ["Consulta clínica", "Ecografía abdominal"])
            self.assertEqual(ruiz.prestaciones, [])
            self.assertEqual([p.admite_videoconsulta for p in Prestacion.query.order_by(Prestacion.id)], [True, False])
            db.session.remove()
            db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
