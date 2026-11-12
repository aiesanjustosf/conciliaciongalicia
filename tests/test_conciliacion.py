"""Pruebas reproducibles sin incluir información bancaria de clientes."""
import unittest
from datetime import date
import pandas as pd

from lectores import centavos, ArchivoInvalido, validar_periodo
from conciliador import categoria_gasto, conciliar, analizar_gastos, sugerido_como_pase


def banco(fila, nombre, monto, fecha=date(2026, 10, 1), desc="TRANSFERENCIA DE TERCEROS"):
    return {"id": f"B{fila}", "fila_excel": fila, "fecha_op": fecha, "monto": monto,
            "descripcion_banco": desc, "nombre_banco": nombre, "cuit": "", "categoria_procesador": ""}


def mayor(fila, nombre, monto, fecha=date(2026, 10, 1), obs="Cobro"):
    return {"id": f"M{fila}", "fila_excel": fila, "fecha_op": fecha, "monto": monto,
            "cuenta_nombre": nombre, "observacion": obs, "concepto": "", "texto": obs,
            "comprobante": "CBRQ", "Asiento": fila}


class ConciliacionTest(unittest.TestCase):
    def test_importes_decimales(self):
        self.assertEqual(centavos("1.234.567,89"), 123456789)
        self.assertEqual(centavos("-1.250,70"), -125070)
        self.assertEqual(centavos(19.12), 1912)

    def test_auto_mismo_nombre_y_signo(self):
        b = pd.DataFrame([banco(4, "Walter Adalberto Cia", 51433355)])
        m = pd.DataFrame([mayor(8, "CIAN WALTER ADALBERTO", 51433355)])
        r = conciliar(m, b)
        self.assertEqual(len(r["conciliados"]), 1)
        self.assertEqual(len(r["solo_banco"]), 0)

    def test_no_cruzar_sentido_opuesto(self):
        b = pd.DataFrame([banco(4, "Carlos Perez Lopez", 10000)])
        m = pd.DataFrame([mayor(8, "CARLOS PEREZ LOPEZ", -10000)])
        r = conciliar(m, b)
        self.assertEqual(len(r["conciliados"]), 0)
        self.assertEqual(len(r["solo_banco"]), 1)
        self.assertEqual(len(r["solo_mayor"]), 1)

    def test_no_autoconciliar_duplicados(self):
        b = pd.DataFrame([banco(4, "Carlos Perez Lopez", 10000)])
        m = pd.DataFrame([mayor(8, "Carlos Perez Lopez", 10000), mayor(9, "Carlos Perez Lopez", 10000)])
        r = conciliar(m, b)
        self.assertEqual(len(r["conciliados"]), 0)
        self.assertEqual(len(r["ambiguos"]), 2)

    def test_diferencia_cuenta_asociada(self):
        b = pd.DataFrame([banco(4, "Valentina Luna Solis", 10000)])
        m = pd.DataFrame([mayor(8, "PUJATO CELESTINA", 10000, obs="Valentina Luna Solis")])
        r = conciliar(m, b)
        self.assertEqual(len(r["conciliados"]), 0)
        self.assertEqual(len(r["posibles"]), 1)

    def test_confirmacion_manual(self):
        b = pd.DataFrame([banco(4, "Cliente sin datos", 10000)])
        m = pd.DataFrame([mayor(8, "OTRA PERSONA", 10000)])
        r = conciliar(m, b, confirmados=[("B4", "M8")])
        self.assertEqual(len(r["conciliados"]), 1)
        self.assertEqual(r["conciliados"].iloc[0]["Estado"], "Validado manualmente")

    def test_no_gast_operativo(self):
        m = pd.Series(mayor(8, "", -4000, obs="TRANSF FIANT"))
        m["comprobante"] = "GAST"
        m["concepto"] = "Viaticos"
        self.assertFalse(sugerido_como_pase(m))

    def test_cargos_agrupados_y_reverso(self):
        b = pd.DataFrame([
            banco(4, "", -1200, desc="ING. BRUTOS S/ CRED"),
            banco(5, "", -5000, desc="COM. DEPOSITO DE CHEQUE"),
            banco(6, "", +300, desc="DEV.IMP.CRED.LEY 25413"),
            banco(7, "Juan Perez Lopez", 100000),
        ])
        m = pd.DataFrame([mayor(8, "", -5900, obs="Gastos Banco Galicia")])
        r = conciliar(m, b, ids_pase={"M8"})
        g = analizar_gastos(r, {"M8"})
        self.assertEqual(g["total_b"], 5900)
        self.assertEqual(g["total_m"], 5900)
        self.assertEqual(g["diferencia"], 0)
        self.assertEqual(len(r["gastos_banco"]), 3)
        self.assertEqual(len(r["solo_mayor"]), 0)

    def test_no_aceptar_periodos_distintos(self):
        mayor_df = pd.DataFrame({"fecha_op": [date(2026, 9, 30)]})
        banco_df = pd.DataFrame({"fecha_op": [date(2026, 10, 1)]})
        with self.assertRaises(ArchivoInvalido):
            validar_periodo(mayor_df, banco_df)

    def test_clasificacion(self):
        self.assertEqual(categoria_gasto("IMP. CRE. LEY 25413"), "Impuesto débitos/créditos")
        self.assertEqual(categoria_gasto("TRF INMED PROVEED"), "")
        self.assertEqual(categoria_gasto("IVA"), "IVA bancario")


if __name__ == "__main__":
    unittest.main()
