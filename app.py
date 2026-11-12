"""CONTROL CONCILIACIÓN PASTOR · Herramienta interna AIE."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

from conciliador import CATEGORIAS_GASTOS, analizar_gastos, conciliar, sugerido_como_pase
from lectores import ArchivoInvalido, leer_banco, leer_mayor, validar_periodo
from reportes import generar_excel

BASE = Path(__file__).resolve().parent
LOGO = BASE / "assets" / "logo_aie.png"
FAVICON = BASE / "assets" / "favicon.ico"

st.set_page_config(
    page_title="CONTROL CONCILIACIÓN PASTOR",
    page_icon=Image.open(FAVICON),
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { max-width: 1480px; padding-top: 1.6rem; padding-bottom: 2.5rem; }
    h1, h2, h3 { color: #1A2A44; }
    div[data-testid="stMetric"] { border: 1px solid #DBE4F0; padding: 14px 16px;
        background: #F8FAFD; border-radius: 12px; min-height: 112px; }
    div[data-testid="stMetricLabel"] {font-weight: 600;}
    div[data-testid="stMetricValue"] {font-size: 1.6rem;}
    section[data-testid="stSidebar"] { background: #F4F7FB; }
    .aie-muted {color: #66748B; font-size: 0.90rem;}
    .aie-footer {border-top: 1px solid #DFE6EF; margin-top: 2.5rem; padding-top: 1.2rem;
      text-align: center; color: #5D6B80; font-size: .89rem;}
</style>
""", unsafe_allow_html=True)


def moneda(cent: int | float) -> str:
    neg = cent < 0
    n = abs(int(cent)) / 100
    entero, dec = f"{n:,.2f}".split(".")
    s = entero.replace(",", ".") + "," + dec
    return f"{'−' if neg else ''}$ {s}"


def ver_tabla(df: pd.DataFrame, mensaje: str) -> None:
    if df is None or df.empty:
        st.info(mensaje)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True, height=min(490, max(160, 42 * (len(df) + 1))))


with st.container():
    c_logo, c_texto = st.columns([1, 7], vertical_alignment="center")
    with c_logo:
        st.image(str(LOGO), width=125)
    with c_texto:
        st.title("CONTROL CONCILIACIÓN PASTOR")
        st.markdown("**Banco Galicia** · Comparación entre mayor contable y resumen bancario procesado")
        st.caption("AIE · Control de movimientos, partidas pendientes y gastos bancarios agrupados")

with st.sidebar:
    st.image(str(LOGO), width=105)
    st.subheader("Archivos de trabajo")
    archivo_mayor = st.file_uploader("1. Mayor contable (Excel)", type=["xlsx"], key="mayor_uploader")
    archivo_banco = st.file_uploader("2. Resumen Galicia procesado (Excel)", type=["xlsx"], key="banco_uploader")
    st.caption("Cargá el Excel generado por tu procesador Galicia; no hace falta subir el PDF.")
    st.divider()
    st.markdown("**Reglas de seguridad contable**")
    st.caption("No se concilia por monto solamente. Las coincidencias ambiguas quedan pendientes de validación.")
    st.caption("Los archivos se procesan en la sesión; la app no utiliza una base de datos ni escribe los Excel al disco.")

if not archivo_mayor or not archivo_banco:
    st.info("Cargá los dos archivos Excel en el panel lateral para comenzar.")
    st.markdown("""
**Qué revisa esta primera versión:** coincidencias 1 a 1 por fecha, importe y sentido; coincidencias
que requieren revisión; movimientos sin correspondencia; cargos bancarios por tipo y por día;
control de saldos y exportación a Excel. Los asientos de pase de gastos se seleccionan manualmente.
""")
    st.markdown('<div class="aie-footer">Herramienta para uso interno AIE - Developers Alfonso Alderete -</div>', unsafe_allow_html=True)
    st.stop()

contenido_m = archivo_mayor.getvalue()
contenido_b = archivo_banco.getvalue()
llave = hashlib.sha256(contenido_m + b":" + contenido_b).hexdigest()[:20]

try:
    mayor, saldos_m = leer_mayor(contenido_m)
    banco, saldos_b = leer_banco(contenido_b)
    periodo = validar_periodo(mayor, banco)
except ArchivoInvalido as err:
    st.error(str(err))
    st.stop()
except Exception as err:
    st.error(f"No se pudieron preparar los archivos. Revisá su estructura: {err}")
    st.stop()

if saldos_m["control"] != 0 or saldos_b["control"] != 0:
    st.error("Inconsistencia aritmética: los saldos de los archivos no coinciden con sus movimientos. "
             f"Banco: {moneda(saldos_b['control'])}; mayor: {moneda(saldos_m['control'])}. "
             "Se interrumpió la conciliación para evitar resultados engañosos.")
    st.stop()

if st.session_state.get("llave_archivos") != llave:
    st.session_state["llave_archivos"] = llave
    st.session_state["aprobaciones_manuales"] = []
    st.session_state["pase_mayor"] = [m["id"] for _, m in mayor.iterrows() if sugerido_como_pase(m)]
    st.session_state["categorias_pase"] = list(CATEGORIAS_GASTOS)
    st.session_state["procesado"] = False

st.success(f"Archivos validados · Período **{periodo}** · Banco: {len(banco):,} movimientos · Mayor: {len(mayor):,} movimientos".replace(",", "."))

with st.expander("Configurar el pase de gastos bancarios del mayor", expanded=False):
    st.markdown("En algunos sistemas, las comisiones, percepciones, SIRCREB e impuestos se registran "
                "mediante **uno o varios asientos globales**. Seleccioná las líneas del mayor que integran ese pase.")
    st.warning("No seleccionar comprobantes `GAST` por el solo hecho de llamarse así: pueden ser viáticos, proveedores u otros gastos ajenos al banco.")
    candidatos_credito = mayor.loc[mayor["monto"] < 0].copy()
    etiquetas = {}
    for _, m in candidatos_credito.iterrows():
        etiquetas[m["id"]] = (f"Fila {int(m['fila_excel'])} · {m['fecha_op'].strftime('%d/%m')} · "
                              f"{moneda(-int(m['monto']))} · {m['comprobante']} · "
                              f"{(m['concepto'] + ' ' + m['observacion'])[:90]}")
    st.multiselect(
        "Asientos del mayor correspondientes a gastos, impuestos y retenciones bancarias",
        options=list(etiquetas), format_func=lambda id_: etiquetas[id_],
        key="pase_mayor", help="Solo líneas de Haber; se toma su importe neto (con signo).",
        placeholder="Buscá por número de fila, fecha, importe o descripción",
    )
    st.caption(f"Asientos seleccionados: {len(st.session_state['pase_mayor'])}. "
               "Si no aparecen asientos de pase identificables, dejá la selección vacía.")
    st.multiselect(
        "Conceptos bancarios que integran ese pase",
        options=list(CATEGORIAS_GASTOS), key="categorias_pase",
        help="Podés excluir SIRCREB o impuestos si el estudio los contabiliza mediante otro asiento. "
             "La tabla de detalle bancario siempre conserva todos los conceptos.",
    )

if st.button("Procesar / actualizar conciliación", type="primary", icon="🔎"):
    st.session_state["procesado"] = True

if not st.session_state.get("procesado"):
    st.markdown("Verificá los conceptos del pase (si corresponde) y seleccioná **Procesar / actualizar conciliación**.")
    st.markdown('<div class="aie-footer">Herramienta para uso interno AIE - Developers Alfonso Alderete -</div>', unsafe_allow_html=True)
    st.stop()

resultado = conciliar(
    mayor, banco,
    confirmados=st.session_state["aprobaciones_manuales"],
    ids_pase=set(st.session_state["pase_mayor"]),
)
gastos = analizar_gastos(resultado, set(st.session_state["pase_mayor"]), set(st.session_state["categorias_pase"]))

st.subheader("Resumen de conciliación")
r1, r2, r3, r4, r5 = st.columns(5)
r1.metric("Conciliados 1:1", len(resultado["conciliados"]))
r2.metric("Candidatos por revisar", len(resultado["posibles"]))
r3.metric("Cruces ambiguos", len(resultado["ambiguos"]))
r4.metric("Solo banco (sin cargos)", len(resultado["solo_banco"]))
r5.metric("Solo mayor (sin pase)", len(resultado["solo_mayor"]))
st.caption("Los cruces ambiguos cuentan relaciones candidatas, no operaciones definitivas. "
           "Los cargos bancarios se tratan por separado y no se marcan automáticamente como conciliados.")

p1, p2, p3, p4, p5 = st.tabs([
    "Conciliación 1 a 1", "Revisión manual", "Gastos bancarios", "Control de saldos", "Exportación"
])

with p1:
    st.markdown("#### Conciliados automáticamente o aprobados")
    ver_tabla(resultado["conciliados"], "No hay coincidencias verificadas con los criterios estrictos.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Solo banco")
        ver_tabla(resultado["solo_banco"], "No hay movimientos sin candidato en el banco.")
    with c2:
        st.markdown("#### Solo mayor")
        ver_tabla(resultado["solo_mayor"], "No hay movimientos sin candidato en el mayor.")
    st.info("Los movimientos de cargos y retenciones bancarias se muestran en la pestaña Gastos bancarios; "
            "no se confunden con operaciones de proveedores o cobros.")

with p2:
    st.markdown("#### Candidatos de conciliación")
    st.caption("Los importes y signos coinciden, con fechas iguales o dentro de ±2 días. "
               "No se dan por conciliados sin verificación.")
    st.markdown("**Coincidencias pendientes con un único candidato**")
    ver_tabla(resultado["posibles"], "No hay candidatos individuales pendientes.")
    st.markdown("**Coincidencias ambiguas o importes repetidos**")
    ver_tabla(resultado["ambiguos"], "No hay relaciones ambiguas detectadas.")
    candidatos = resultado["candidatos"]
    if not candidatos.empty:
        st.divider()
        st.markdown("#### Aprobar una coincidencia después de revisarla")
        # Distintas relaciones posibles, sin descartar coincidencias ambiguas.
        opciones = list(candidatos.index)
        def describir_candidato(i: int) -> str:
            r = candidatos.loc[i]
            return (f"Banco fila {r['Fila banco']} → Mayor fila {r['Fila mayor']} | "
                    f"{moneda(int(round(float(r['Importe $']) * 100)))} | "
                    f"{str(r['Ordenante banco'])[:30]}")
        fila_elegida = st.selectbox("Operación para validar", options=opciones, format_func=describir_candidato)
        registro = candidatos.loc[fila_elegida]
        st.caption(f"**Motivo de revisión:** {registro['Motivo']}")
        if st.button("Confirmar vinculación manual", icon="✅"):
            pareja = (registro["ID banco"], registro["ID mayor"])
            st.session_state["aprobaciones_manuales"].append(pareja)
            st.rerun()
    if st.session_state["aprobaciones_manuales"]:
        st.caption(f"Vinculaciones manuales registradas en esta sesión: {len(resultado['aprobaciones_aceptadas'])} válidas.")
        if st.button("Deshacer la última confirmación", icon="↩️"):
            st.session_state["aprobaciones_manuales"].pop()
            st.rerun()

with p3:
    st.markdown("#### Comparación del pase global de gastos y retenciones")
    e1, e2, e3 = st.columns(3)
    e1.metric("Banco (conceptos incluidos)", moneda(gastos["total_b"]))
    e2.metric("Mayor (pases seleccionados)", moneda(gastos["total_m"]))
    e3.metric("Diferencia", moneda(gastos["diferencia"]) if gastos["imputado"] else "Sin pase elegido")
    if not gastos["imputado"]:
        st.warning("No se seleccionaron asientos del mayor para este control. "
                   "El total del banco está calculado, pero no corresponde interpretar aún una diferencia como error.")
    else:
        if gastos["diferencia"] == 0:
            st.success("La suma de conceptos seleccionados coincide exactamente con los pases del mayor.")
        else:
            st.warning("El pase no coincide con los conceptos bancarios seleccionados. "
                       "Revisá qué categorías integran el asiento y si existen otros pases.")
    st.caption(f"Total neto de todas las categorías bancarias identificadas: {moneda(gastos['total_todos_cargos'])}. "
               "Devoluciones o ajustes positivos reducen el importe neto.")
    st.markdown("#### Desglose por tipo de cargo")
    ver_tabla(gastos["por_categoria"], "No se detectaron conceptos bancarios de gastos o retenciones.")
    st.markdown("#### Desglose diario de los conceptos incluidos")
    ver_tabla(gastos["por_dia"], "No hay datos con las categorías seleccionadas.")
    st.markdown("#### Asientos del mayor elegidos para el pase")
    ver_tabla(gastos["detalle_mayor"], "No se seleccionaron asientos de pase.")
    with st.expander("Ver cada movimiento bancario clasificado como cargo, impuesto o retención"):
        ver_tabla(resultado["gastos_banco"], "No hay cargos clasificados.")
    st.caption("SIRCREB, impuesto a los débitos/créditos y percepciones pueden corresponder a "
               "cuentas contables distintas. El total agrupado es un control, no una asignación automática.")

with p4:
    st.markdown("#### Evolución de saldos")
    tabla_saldos = pd.DataFrame([
        {"Origen": "Banco Galicia", "Saldo inicial $": saldos_b["inicial"] / 100,
         "Movimiento neto $": saldos_b["movimientos"] / 100, "Saldo final $": saldos_b["final"] / 100,
         "Error de cálculo $": saldos_b["control"] / 100},
        {"Origen": "Mayor contable", "Saldo inicial $": saldos_m["inicial"] / 100,
         "Movimiento neto $": saldos_m["movimientos"] / 100, "Saldo final $": saldos_m["final"] / 100,
         "Error de cálculo $": saldos_m["control"] / 100},
    ])
    ver_tabla(tabla_saldos, "No hay saldos disponibles.")
    d_ini = saldos_m["inicial"] - saldos_b["inicial"]
    d_fin = saldos_m["final"] - saldos_b["final"]
    t1, t2, t3 = st.columns(3)
    t1.metric("Diferencia inicial (mayor − banco)", moneda(d_ini))
    t2.metric("Diferencia final (mayor − banco)", moneda(d_fin))
    t3.metric("Variación durante el período", moneda(d_fin - d_ini))
    st.info("La diferencia final no es por sí sola un error: puede incluir cheques, depósitos en tránsito "
            "y partidas pendientes de meses anteriores. Los saldos se verifican aritméticamente, "
            "pero el módulo 1 a 1 no cierra automáticamente todas las partidas conciliatorias.")

with p5:
    st.markdown("#### Descargar archivo Excel de control")
    st.markdown("Incluye resumen, saldos, conciliados, posibles, ambiguos, solo banco, solo mayor, "
                "cargos bancarios, desglose por categoría y por fecha, pase contable y reglas usadas.")
    archivo_resultados = generar_excel(resultado, gastos, saldos_m, saldos_b, periodo)
    st.download_button(
        "Descargar conciliación en Excel", archivo_resultados,
        file_name=f"Control_Conciliacion_Pastor_Galicia_{periodo.replace('/', '-')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary", icon="📥",
    )
    st.caption("La exportación incluye las filas de origen para verificar cada movimiento contra ambos Excel.")

st.markdown('<div class="aie-footer">Herramienta para uso interno AIE - Developers Alfonso Alderete -</div>', unsafe_allow_html=True)
