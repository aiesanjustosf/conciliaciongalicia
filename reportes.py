"""Reporte descargable en memoria con trazabilidad por fila de origen."""
from __future__ import annotations
from io import BytesIO
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


def _exportable(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame({"Información": ["Sin movimientos en esta categoría"]})
    return df.copy()


def generar_excel(result: dict, gastos: dict, saldos_m: dict, saldos_b: dict, periodo: str) -> bytes:
    diferencia_saldos = (saldos_m["final"] - saldos_b["final"]) / 100
    inicial = (saldos_m["inicial"] - saldos_b["inicial"]) / 100
    variacion = diferencia_saldos - inicial
    resumen = pd.DataFrame([
        ("Período", periodo),
        ("Conciliaciones automáticas y aprobadas", len(result["conciliados"])),
        ("Candidatos por revisar", len(result["posibles"])),
        ("Cruces ambiguos", len(result["ambiguos"])),
        ("Solo banco (sin cargos identificados)", len(result["solo_banco"])),
        ("Solo mayor (sin asientos de gastos asignados)", len(result["solo_mayor"])),
        ("Movimientos clasificados como cargos/retenciones bancarias", gastos["cantidad"]),
        ("Cargos y retenciones banco (categorías seleccionadas), neto $", gastos["total_b"] / 100),
        ("Todas las categorías de cargos banco, neto $", gastos["total_todos_cargos"] / 100),
        ("Categorías incluidas en el pase", ", ".join(gastos["categorias_incluidas"])),
        ("Asientos de pase seleccionados, neto $", gastos["total_m"] / 100),
        ("Diferencia cargos vs pase, neto $", gastos["diferencia"] / 100 if gastos["imputado"] else "Sin pases seleccionados"),
        ("Diferencia de saldos iniciales, mayor menos banco $", inicial),
        ("Diferencia de saldos finales, mayor menos banco $", diferencia_saldos),
        ("Variación de la diferencia durante el período $", variacion),
        ("Control aritmético banco, centavos", saldos_b["control"]),
        ("Control aritmético mayor, centavos", saldos_m["control"]),
    ], columns=["Indicador", "Valor"])
    saldos = pd.DataFrame([
        ("Banco Galicia", saldos_b["inicial"] / 100, saldos_b["movimientos"] / 100,
         saldos_b["final"] / 100, saldos_b["control"] / 100),
        ("Mayor contable", saldos_m["inicial"] / 100, saldos_m["movimientos"] / 100,
         saldos_m["final"] / 100, saldos_m["control"] / 100),
    ], columns=["Origen", "Saldo inicial $", "Movimientos netos $", "Saldo final $", "Error secuencia $"])
    reglas = pd.DataFrame({"Criterio y alcance": [
        "Cruce automático conservador: fecha exacta, importe exacto en centavos y mismo sentido.",
        "Para conciliar automáticamente se exige un único candidato en cada origen y nombre compatible.",
        "Nombres del banco pueden estar truncados. Se requieren al menos dos tokens significativos coincidentes.",
        "Si cuenta asociada y ordenante difieren, se marca para revisión aunque coincida observación.",
        "Candidatos: importe y sentido exactos, fechas con distancia hasta dos días, sin conciliación automática.",
        "Los cargos bancarios se apartan del cruce 1:1 y se controlan por suma de categorías.",
        "SIRCREB y Ley 25.413 son retenciones/impuestos; no deben confundirse con una comisión comercial.",
        "Los asientos de pase son seleccionados explícitamente por el operador; no se presupone el pase.",
        "El control de saldos no elimina partidas conciliatorias de meses anteriores.",
        "Los datos originales del banco y mayor no se modifican. La fila Excel permite auditoría.",
        "El reporte es una propuesta de conciliación para revisión contable, no una registración automática.",
    ]})
    datos = {
        "Resumen": resumen,
        "Saldos": saldos,
        "Conciliados": result["conciliados"],
        "Posibles": result["posibles"],
        "Ambiguos": result["ambiguos"],
        "Solo Banco": result["solo_banco"],
        "Solo Mayor": result["solo_mayor"],
        "Cargos Banco": result["gastos_banco"],
        "Cargos x Tipo": gastos["por_categoria"],
        "Cargos x Fecha": gastos["por_dia"],
        "Pase Mayor": gastos["detalle_mayor"],
        "Reglas": reglas,
    }
    destino = BytesIO()
    with pd.ExcelWriter(destino, engine="openpyxl", datetime_format="DD/MM/YYYY", date_format="DD/MM/YYYY") as writer:
        for hoja, df in datos.items():
            _exportable(df).to_excel(writer, sheet_name=hoja, index=False)
            ws = writer.sheets[hoja]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            ws.row_dimensions[1].height = 27
            for cell in ws[1]:
                cell.fill = PatternFill("solid", fgColor="1A2A44")
                cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            for idx, columna in enumerate(ws.columns, start=1):
                letras = get_column_letter(idx)
                nombres = [str(c.value or "") for c in list(columna)[:250] if c.value is not None]
                ancho = max((len(c) for c in nombres), default=12) + 2
                ws.column_dimensions[letras].width = min(max(ancho, 13), 46)
            for fila in ws.iter_rows(min_row=2):
                for c in fila:
                    if c.data_type == "n":
                        c.number_format = '#,##0.00;[Red](#,##0.00)'
                    if c.data_type == "d":
                        c.number_format = 'DD/MM/YYYY'
    return destino.getvalue()
