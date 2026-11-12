"""Lectores específicos para los dos Excel de Pastor (sin procesar el PDF)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
import re
import unicodedata

import pandas as pd


class ArchivoInvalido(ValueError):
    """Error de formato o de datos que impide conciliar de forma segura."""


def limpiar_texto(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return ""
    texto = unicodedata.normalize("NFKD", str(valor).upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", texto).split())


def centavos(valor: object, *, campo: str = "importe") -> int:
    """Convierte ARS a centavos enteros: nunca concilia usando floats."""
    if valor is None or (not isinstance(valor, (list, tuple, dict)) and pd.isna(valor)):
        return 0
    if isinstance(valor, str):
        texto = valor.strip().replace("$", "").replace(" ", "")
        if not texto or texto in ("-", "—"):
            return 0
        negativo = texto.startswith("(") and texto.endswith(")")
        texto = texto.strip("()")
        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".") if texto.rfind(",") > texto.rfind(".") else texto.replace(",", "")
        elif "," in texto:
            texto = texto.replace(",", ".")
        elif texto.count(".") > 1:
            texto = texto.replace(".", "")
        if negativo:
            texto = "-" + texto
        valor = texto
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite():
            raise ValueError("valor no finito")
        return int((numero * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ArchivoInvalido(f"Importe inválido en {campo}: {valor!r}") from exc


def convertir_fecha(valor: object) -> date | None:
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)):
        # Excel almacena las fechas como números seriales. Redondear evita
        # problemas en fechas con 23:59:59.9999.
        return date(1899, 12, 30) + timedelta(days=int(round(float(valor))))
    texto = str(valor).strip()
    if re.fullmatch(r"\d+(\.\d+)?", texto):
        return date(1899, 12, 30) + timedelta(days=int(round(float(texto))))
    dt = pd.to_datetime(texto, errors="coerce", dayfirst=True)
    return None if pd.isna(dt) else dt.date()


def _abrir_tabla(datos: bytes, requerido: set[str], nombre: str) -> tuple[pd.DataFrame, int]:
    try:
        excel = pd.ExcelFile(BytesIO(datos), engine="openpyxl")
        for hoja in excel.sheet_names:
            raw = pd.read_excel(excel, sheet_name=hoja, header=None, dtype=object)
            # Busca encabezado: el mayor lo tiene en la tercera fila.
            for idx in range(min(18, len(raw))):
                columnas = [str(x).strip().lower() if pd.notna(x) else "" for x in raw.iloc[idx]]
                if requerido.issubset(set(columnas)):
                    tabla = raw.iloc[idx + 1:].copy()
                    tabla.columns = [str(x).strip() if pd.notna(x) else f"col_{n}" for n, x in enumerate(raw.iloc[idx])]
                    tabla = tabla.dropna(how="all")
                    # El índice original refleja la fila real, incluso si había filas vacías.
                    tabla["fila_excel"] = tabla.index + 1
                    tabla = tabla.reset_index(drop=True)
                    return tabla, idx
    except Exception as exc:
        raise ArchivoInvalido(f"No se pudo leer {nombre}: {exc}") from exc
    raise ArchivoInvalido(
        f"{nombre}: no se encontraron las columnas requeridas: {', '.join(sorted(requerido))}. "
        "Subí la exportación original correspondiente."
    )


def _numeros_y_fechas(tabla: pd.DataFrame, fecha: str, columnas: list[str], nombre: str) -> None:
    tabla["fecha_op"] = tabla[fecha].map(convertir_fecha)
    invalidas = tabla[tabla["fecha_op"].isna()]
    if not invalidas.empty:
        raise ArchivoInvalido(f"{nombre}: fechas vacías o incorrectas en filas {invalidas['fila_excel'].head(5).tolist()}")
    for col in columnas:
        tabla[f"cent_{col.lower()}"] = [centavos(v, campo=f"{nombre}, fila {f}, {col}")
                                             for v, f in zip(tabla[col], tabla["fila_excel"])]


def leer_mayor(datos: bytes) -> tuple[pd.DataFrame, dict]:
    df, _ = _abrir_tabla(datos, {"asiento", "fecha", "debe", "haber", "saldo"}, "Mayor contable")
    iniciales = df[df.get("Concepto", pd.Series("", index=df.index)).fillna("").astype(str).str.contains("saldo anterior", case=False)]
    if len(iniciales) != 1:
        raise ArchivoInvalido("Mayor: se esperaba una única fila 'Saldo anterior'.")
    saldo_inicial = centavos(iniciales.iloc[0]["Saldo"])
    df = df.drop(index=iniciales.index).copy().reset_index(drop=True)
    _numeros_y_fechas(df, "Fecha", ["Debe", "Haber", "Saldo"], "Mayor")
    df["monto"] = df["cent_debe"] - df["cent_haber"]
    df["id"] = "M" + df["fila_excel"].astype(str)
    df["cuenta_nombre"] = df.get("Cuenta Asociada", pd.Series("", index=df.index)).fillna("").astype(str).map(lambda s: re.sub(r"^\s*\d+[- ]+", "", s).strip())
    df["observacion"] = df.get("Observacion", pd.Series("", index=df.index)).fillna("").astype(str)
    df["concepto"] = df.get("Concepto", pd.Series("", index=df.index)).fillna("").astype(str)
    df["texto"] = (df["concepto"] + " " + df["observacion"]).map(limpiar_texto)
    df["comprobante"] = df.get("Comp.", pd.Series("", index=df.index)).fillna("").astype(str)
    if df.empty:
        raise ArchivoInvalido("El mayor no contiene movimientos.")
    saldo_final = df.iloc[-1]["cent_saldo"]
    total = int(df["monto"].sum())
    return df, {"inicial": saldo_inicial, "final": saldo_final, "movimientos": total,
                "control": saldo_inicial + total - saldo_final, "fuente": "mayor"}


def leer_banco(datos: bytes) -> tuple[pd.DataFrame, dict]:
    df, _ = _abrir_tabla(datos, {"fecha", "descripcion", "debito", "credito", "saldo"}, "Resumen Galicia")
    saldos = df["descripcion"].fillna("").astype(str).str.contains(r"^\s*SALDO ANTERIOR\s*$", case=False, regex=True)
    if saldos.sum() != 1:
        raise ArchivoInvalido("Resumen Galicia: se esperaba una única fila 'SALDO ANTERIOR'.")
    saldo_inicial = centavos(df.loc[saldos, "saldo"].iloc[0])
    df = df.loc[~saldos].copy().reset_index(drop=True)
    _numeros_y_fechas(df, "fecha", ["debito", "credito", "saldo"], "Banco")
    df["monto"] = df["cent_credito"] - df["cent_debito"]
    df["id"] = "B" + df["fila_excel"].astype(str)
    df["descripcion_banco"] = df["descripcion"].fillna("").astype(str)
    df["nombre_banco"] = df.get("Ordenante / referencia", pd.Series("", index=df.index)).fillna("").astype(str)
    df["cuit"] = df.get("CUIT / CUIL", pd.Series("", index=df.index)).fillna("").astype(str).map(lambda s: re.sub(r"[^0-9]", "", s))
    df["categoria_procesador"] = df.get("Clasificación", pd.Series("", index=df.index)).fillna("").astype(str)
    if df.empty:
        raise ArchivoInvalido("El resumen no contiene movimientos.")
    if "importe" in df.columns:
        muestras = [(centavos(v), int(m)) for v, m in zip(df["importe"], df["monto"]) if pd.notna(v)]
        if any(a != b for a, b in muestras):
            raise ArchivoInvalido("Resumen: la columna 'importe' no coincide con crédito - débito.")
    saldo_final = int(df.iloc[-1]["cent_saldo"])
    total = int(df["monto"].sum())
    return df, {"inicial": saldo_inicial, "final": saldo_final, "movimientos": total,
                "control": saldo_inicial + total - saldo_final, "fuente": "banco"}


def validar_periodo(mayor: pd.DataFrame, banco: pd.DataFrame) -> str:
    meses_mayor = {(d.year, d.month) for d in mayor["fecha_op"]}
    meses_banco = {(d.year, d.month) for d in banco["fecha_op"]}
    if len(meses_mayor) != 1 or len(meses_banco) != 1 or meses_mayor != meses_banco:
        raise ArchivoInvalido(
            f"Los períodos no coinciden o contienen más de un mes. Mayor: {sorted(meses_mayor)}; "
            f"Banco: {sorted(meses_banco)}. No se efectuó la conciliación."
        )
    year, month = next(iter(meses_banco))
    return f"{month:02d}/{year}"
