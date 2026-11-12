"""Motor de conciliación conservador, rastreable y sin coincidencias forzadas."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
import re

import pandas as pd

from lectores import limpiar_texto

CATEGORIAS_GASTOS = (
    "SIRCREB / IIBB", "Comisiones bancarias", "IVA bancario", "Percepciones IVA",
    "Impuesto débitos/créditos", "Impuesto de sellos", "Intereses / cargos"
)


def categoria_gasto(descripcion: str) -> str:
    desc = limpiar_texto(descripcion)
    if "ING BRUTOS S CRED" in desc or "SIRCREB" in desc:
        return "SIRCREB / IIBB"
    if desc.startswith(("COM ", "COMISION ", "COMISIONES ", "GASTO BANCARIO", "GASTOS BANCARIOS")):
        return "Comisiones bancarias"
    if desc in ("IVA", "IVA SERVICIO", "IVA COMISION"):
        return "IVA bancario"
    if desc.startswith(("PERCEP IVA", "PERCEPCION IVA")):
        return "Percepciones IVA"
    if "LEY 25413" in desc or "IMP CRED" in desc or "IMP DEB" in desc:
        return "Impuesto débitos/créditos"
    if "IMPUESTO DE SELLOS" in desc or desc.startswith("IMP SELLOS"):
        return "Impuesto de sellos"
    if desc.startswith(("INTERESES BANC", "INTERES BANC", "CARGO BANC")):
        return "Intereses / cargos"
    return ""


def sugerido_como_pase(m: pd.Series) -> bool:
    """Nunca toma todos los comprobantes GAST ni todos los DEPO como cargos."""
    texto = limpiar_texto(str(m.get("concepto", "")) + " " + str(m.get("observacion", "")))
    frases = ("GASTOS BANCARIOS", "GASTOS BANCO GALICIA", "GASTOS BCO GALICIA",
              "GASTOS BCO", "GASTOS BANCO", "GASTOS GALICIA", "COMISIONES BANCARIAS",
              "RETENCIONES SIRCREB", "IMPUESTO DEBITOS Y CREDITOS",
              "IMPUESTO DEB CRED", "PASE GASTOS GALICIA")
    return any(f in texto for f in frases) and int(m["monto"]) < 0


_STOP = set("DE DEL EL LA LAS LOS LO Y E A AL POR PARA TRANSF TRANSFERENCIA TRANSFERENCIAS "
            "BANC BANCO GALICIA DEPOSITO DEP PAGO COBRO CBRQ CCPC CREDITO GASTOS "
            "OCTUBRE OCT NOV SET SEP DIA CLIENTE FACTURA COBRANZA CUENTA".split())


def _tokens(texto: object) -> set[str]:
    return {x for x in limpiar_texto(texto).split() if len(x) >= 4 and x not in _STOP and not x.isdigit()}


def _coincidencia_nombres(a: str, b: str) -> bool:
    izquierda, derecha = _tokens(a), _tokens(b)
    if not izquierda or not derecha:
        return False
    # Al menos dos elementos significativos. Soporta apellido truncado en el banco.
    matches = 0
    usados: set[str] = set()
    for t1 in sorted(izquierda, key=len, reverse=True):
        for t2 in derecha:
            if t2 in usados:
                continue
            if t1 == t2 or (min(len(t1), len(t2)) >= 5 and
                           abs(len(t1) - len(t2)) <= 3 and
                           (t1.startswith(t2) or t2.startswith(t1))):
                matches += 1
                usados.add(t2)
                break
    return matches >= 2


def _evidencia(b: pd.Series, m: pd.Series) -> tuple[bool, str]:
    nombre = str(b.get("nombre_banco", "") or "")
    if not nombre:
        return False, "El banco no aporta ordenante; verificar comprobante."
    asociada = str(m.get("cuenta_nombre", "") or "")
    observ = str(m.get("observacion", "") or "")
    if asociada:
        if _coincidencia_nombres(nombre, asociada):
            return True, "Nombre compatible con la cuenta asociada."
        if _coincidencia_nombres(nombre, observ):
            return False, "Ordenante compatible con observación, pero difiere de la cuenta asociada."
        return False, "Nombre bancario no comprobado contra cuenta asociada."
    if _coincidencia_nombres(nombre, observ):
        return True, "Ordenante compatible con observación (sin cuenta asociada)."
    return False, "Nombre bancario no suficientemente identificado en el mayor."


def _formato_match(b: pd.Series, m: pd.Series, clase: str, motivo: str) -> dict:
    return {
        "Estado": clase,
        "Fila banco": int(b["fila_excel"]),
        "Fecha banco": b["fecha_op"],
        "Ordenante banco": b["nombre_banco"],
        "CUIT/CUIL banco": b["cuit"],
        "Descripción banco": b["descripcion_banco"],
        "Fila mayor": int(m["fila_excel"]),
        "Fecha mayor": m["fecha_op"],
        "Asiento": m.get("Asiento", ""),
        "Comp.": m["comprobante"],
        "Cuenta asociada": m["cuenta_nombre"],
        "Observación mayor": m["observacion"],
        "Importe $": int(b["monto"]) / 100,
        "Motivo": motivo,
        "ID banco": b["id"],
        "ID mayor": m["id"],
    }


def _vista_banco(banco: pd.DataFrame, ids: set[str]) -> pd.DataFrame:
    aux = banco.loc[banco["id"].isin(ids)].copy()
    aux["Importe $"] = aux["monto"] / 100
    return aux[["id", "fila_excel", "fecha_op", "descripcion_banco", "nombre_banco", "cuit", "Importe $", "categoria_gasto"]].rename(
        columns={"id": "ID", "fila_excel": "Fila Excel", "fecha_op": "Fecha",
                 "descripcion_banco": "Descripción", "nombre_banco": "Ordenante",
                 "cuit": "CUIT/CUIL", "categoria_gasto": "Tipo de gasto"})


def _vista_mayor(mayor: pd.DataFrame, ids: set[str]) -> pd.DataFrame:
    aux = mayor.loc[mayor["id"].isin(ids)].copy()
    aux["Importe $"] = aux["monto"] / 100
    return aux[["id", "fila_excel", "fecha_op", "Asiento", "comprobante", "concepto", "observacion", "cuenta_nombre", "Importe $"]].rename(
        columns={"id": "ID", "fila_excel": "Fila Excel", "fecha_op": "Fecha",
                 "comprobante": "Comp.", "concepto": "Concepto", "observacion": "Observación",
                 "cuenta_nombre": "Cuenta asociada"})


def conciliar(mayor: pd.DataFrame, banco: pd.DataFrame, confirmados: list[tuple[str, str]] | None = None,
             ids_pase: set[str] | None = None) -> dict:
    """Conciliación 1:1: fecha+importe+sentido y nombre corroborado.

    Si falta evidencia de identidad, devuelve candidato. Nunca cruza débitos con créditos
    ni reutiliza movimientos aunque existan duplicados del mismo importe.
    """
    mayor, banco = mayor.copy(), banco.copy()
    ids_pase = ids_pase or set()
    mayor_activo = mayor.loc[~mayor["id"].isin(ids_pase)].copy()
    banco["categoria_gasto"] = banco["descripcion_banco"].map(categoria_gasto)
    banco_activo = banco.loc[banco["categoria_gasto"].eq("")].copy()
    m_por_clave = defaultdict(list)
    b_por_clave = defaultdict(list)
    m_por_importe = defaultdict(list)
    b_por_importe = defaultdict(list)
    for _, m in mayor_activo.iterrows():
        m_por_clave[(m["fecha_op"], int(m["monto"]))].append(m)
        m_por_importe[int(m["monto"])].append(m)
    for _, b in banco_activo.iterrows():
        b_por_clave[(b["fecha_op"], int(b["monto"]))].append(b)
        b_por_importe[int(b["monto"])].append(b)

    usados_b, usados_m = set(), set()
    conciliados = []
    for clave, bb in b_por_clave.items():
        mm = m_por_clave.get(clave, [])
        if len(bb) != 1 or len(mm) != 1 or clave[1] == 0:
            continue
        b, m = bb[0], mm[0]
        # Evita asignar un pago de un día a otro asiento con igual monto en días cercanos.
        if (sum(abs((b["fecha_op"] - otro["fecha_op"]).days) <= 2
                for otro in m_por_importe[int(b["monto"])]) != 1
            or sum(abs((m["fecha_op"] - otro["fecha_op"]).days) <= 2
                   for otro in b_por_importe[int(m["monto"])]) != 1):
            continue
        OK, motivo = _evidencia(b, m)
        if OK:
            usados_b.add(b["id"])
            usados_m.add(m["id"])
            conciliados.append(_formato_match(b, m, "Automático verificado", motivo))

    banco_por_id = {b["id"]: b for _, b in banco_activo.iterrows()}
    mayor_por_id = {m["id"]: m for _, m in mayor_activo.iterrows()}
    aprobaciones_aceptadas = []
    for id_b, id_m in confirmados or []:
        if id_b in usados_b or id_m in usados_m or id_b not in banco_por_id or id_m not in mayor_por_id:
            continue
        b, m = banco_por_id[id_b], mayor_por_id[id_m]
        if b["monto"] != m["monto"] or b["monto"] == 0:
            continue
        if abs((b["fecha_op"] - m["fecha_op"]).days) > 2:
            continue
        usados_b.add(id_b)
        usados_m.add(id_m)
        aprobaciones_aceptadas.append((id_b, id_m))
        conciliados.append(_formato_match(b, m, "Validado manualmente", "Vinculación aprobada expresamente en la aplicación."))

    # Candidatos restantes: igualdad exacta de importe y sentido, ventana ±2 días.
    disponibles_m = defaultdict(list)
    for _, m in mayor_activo.iterrows():
        if m["id"] not in usados_m and int(m["monto"]) != 0:
            disponibles_m[int(m["monto"])].append(m)
    candidatos = []
    for _, b in banco_activo.iterrows():
        if b["id"] in usados_b or int(b["monto"]) == 0:
            continue
        for m in disponibles_m.get(int(b["monto"]), []):
            distancia = abs((b["fecha_op"] - m["fecha_op"]).days)
            if distancia <= 2:
                _, motivo = _evidencia(b, m)
                candidatos.append(_formato_match(b, m, "Por revisar", f"{motivo} Distancia de fecha: {distancia} día(s)."))

    n_b = Counter(r["ID banco"] for r in candidatos)
    n_m = Counter(r["ID mayor"] for r in candidatos)
    amb = [r for r in candidatos if n_b[r["ID banco"]] > 1 or n_m[r["ID mayor"]] > 1]
    pos = [r for r in candidatos if n_b[r["ID banco"]] == 1 and n_m[r["ID mayor"]] == 1]
    for r in amb:
        r["Estado"] = "Ambiguo / duplicado"
    ids_con_candidato_b = set(n_b)
    ids_con_candidato_m = set(n_m)
    ids_gastos = set(banco.loc[banco["categoria_gasto"] != "", "id"])
    ids_solo_b = set(banco_activo["id"]) - usados_b - ids_con_candidato_b
    ids_solo_m = set(mayor_activo["id"]) - usados_m - ids_con_candidato_m

    return {
        "conciliados": pd.DataFrame(conciliados),
        "posibles": pd.DataFrame(pos),
        "ambiguos": pd.DataFrame(amb),
        "candidatos": pd.DataFrame(candidatos),
        "solo_banco": _vista_banco(banco, ids_solo_b),
        "solo_mayor": _vista_mayor(mayor, ids_solo_m),
        "gastos_banco": _vista_banco(banco, ids_gastos),
        "usados_mayor": usados_m,
        "usados_banco": usados_b,
        "aprobaciones_aceptadas": aprobaciones_aceptadas,
        "ids_pase": ids_pase,
        "mayor": mayor,
        "banco": banco,
    }


def analizar_gastos(resultado: dict, ids_pase: set[str],
                   categorias_incluidas: set[str] | None = None) -> dict:
    banco = resultado["banco"]
    mayor = resultado["mayor"]
    todos_gastos = banco.loc[banco["categoria_gasto"] != ""].copy()
    categorias_incluidas = set(CATEGORIAS_GASTOS) if categorias_incluidas is None else set(categorias_incluidas)
    gasto_b = todos_gastos.loc[todos_gastos["categoria_gasto"].isin(categorias_incluidas)].copy()
    gasto_m = mayor.loc[mayor["id"].isin(ids_pase)].copy()
    total_b = -int(gasto_b["monto"].sum())  # reversos se descuentan
    total_m = -int(gasto_m["monto"].sum())  # banco en Haber = gasto
    por_categoria = todos_gastos.groupby("categoria_gasto", as_index=False)["monto"].sum()
    por_categoria["Total $ neto"] = -por_categoria["monto"] / 100
    por_categoria = por_categoria.rename(columns={"categoria_gasto": "Categoría"})[["Categoría", "Total $ neto"]]
    por_dia = gasto_b.groupby(["fecha_op", "categoria_gasto"], as_index=False)["monto"].sum()
    por_dia["Total $ neto"] = -por_dia["monto"] / 100
    por_dia = por_dia.rename(columns={"fecha_op": "Fecha", "categoria_gasto": "Categoría"})[["Fecha", "Categoría", "Total $ neto"]]
    return {
        "total_b": total_b,
        "total_m": total_m,
        "diferencia": total_b - total_m,
        "cantidad": len(gasto_b),
        "por_categoria": por_categoria.sort_values("Categoría"),
        "por_dia": por_dia.sort_values(["Fecha", "Categoría"]),
        "detalle_mayor": _vista_mayor(mayor, set(gasto_m["id"])),
        "imputado": len(gasto_m) > 0,
        "categorias_incluidas": sorted(categorias_incluidas),
        "total_todos_cargos": -int(todos_gastos["monto"].sum()),
    }
