# CONTROL CONCILIACIÓN PASTOR

**Banco Galicia · Conciliación contable de uso interno AIE**  
Developers: Alfonso Alderete

Aplicación web construida con **Python + Streamlit**. Compara el **mayor contable de Banco Galicia** contra el **Excel procesado por la app de resúmenes Galicia**. No requiere el PDF original porque el procesador bancario ya lo transformó en Excel.

## Contenido

- `app.py`: interfaz web, carga de Excel, controles y validación manual.
- `lectores.py`: lectores que reconocen encabezados y estructuras reales de ambos archivos.
- `conciliador.py`: motor conservador de conciliación y clasificación de cargos bancarios.
- `reportes.py`: exportación de un reporte Excel con 12 pestañas.
- `assets/logo_aie.png` y `assets/favicon.ico`: identidad visual incluida.
- `requirements.txt`: dependencias para Streamlit Community Cloud.
- `.streamlit/config.toml`: configuración de apariencia.
- `tests/test_conciliacion.py`: pruebas automáticas con datos ficticios.

## Cómo publicar en GitHub y Streamlit

1. **Descomprimí** el archivo ZIP en tu computadora.
2. Creá un repositorio **privado** en GitHub, por ejemplo `control-conciliacion-pastor`.
3. Subí **todos** los archivos y carpetas del contenido descomprimido, respetando la estructura. `app.py` debe quedar en la raíz del repositorio.
4. En el servicio de despliegue de Streamlit, vinculá el repositorio y configurá como archivo principal **`app.py`**. Elegí una versión actual de Python (3.11 o 3.12).
5. Asegurá un acceso **restringido a usuarios autorizados** antes de subir documentación real. Un repositorio privado no convierte automáticamente en privada a una aplicación desplegada.

### Ejecutar localmente

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Pruebas

```bash
python -m unittest discover -s tests -v
```

## Instrucciones de uso

1. En el panel lateral, subí el **mayor contable** Excel (en el ejemplo, cuenta 1110407) y el **resumen Galicia procesado** Excel.
2. La app valida ambos documentos, su secuencia aritmética y que pertenezcan al **mismo mes**. La fecha final del banco puede ser un día hábil anterior al cierre del mes contable.
3. Expandí **Configurar el pase de gastos bancarios** y elegí los movimientos del mayor que efectivamente corresponden al/los asiento/s de gastos, impuestos o retenciones. **No se seleccionan automáticamente** todos los comprobantes `GAST`, porque en el mayor de ejemplo incluyen gastos operativos.
4. Indicá qué **categorías** integran el pase (por ejemplo, si el asiento no incluye SIRCREB, desmarcá esa categoría). El detalle del banco siempre conserva las categorías originales.
5. Presioná **Procesar / actualizar conciliación**.
6. Consultá las pestañas: conciliados 1 a 1; candidatos y ambigüedades; gastos agrupados; control de saldos; y Excel descargable.
7. En **Revisión manual** podés confirmar expresamente un candidato o deshacer la última aprobación, sin modificar ninguno de los Excel originales.

## Reglas esenciales de conciliación

- **Debe bancario de la cuenta contable** aumenta el saldo; **Haber** lo disminuye. En el extracto, **crédito** aumenta y **débito** disminuye. Ambos se expresan como un único **importe con signo**.
- Solo se marca **automáticamente** como conciliado cuando la fecha y el importe en centavos coinciden, el sentido es igual, hay **exactamente un movimiento candidato por origen** y el nombre bancario se comprueba con al menos dos palabras significativas del mayor.
- Cuando el nombre está abreviado, el sistema intenta comparar sus componentes; **no atribuye automáticamente un CUIT del banco a una cuenta del mayor**.
- Cuando el ordenante coincide con la observación pero **no** con la cuenta asociada, se deja para revisión.
- El resto pasa a **por revisar**, **ambiguo/duplicado** o **solo banco / solo mayor**. Los candidatos admiten como máximo **±2 días de diferencia**, pero **no se concilian automáticamente**.
- **SIRCREB, Ley 25.413, comisiones, IVA, percepciones e impuesto de sellos** se muestran por separado y pueden sumarse según las categorías seleccionadas. Los reversos o devoluciones reducen la suma neta.
- Los asientos del mayor elegidos como **pase de gastos** quedan reservados y no se cuentan también como conciliación 1 a 1.
- Cada registro conserva la **fila Excel** de procedencia.
- El módulo de saldos distingue la **diferencia inicial**, la **diferencia final** y su **variación durante el período**.

## Límites importantes de la versión 1

- No se realiza conciliación **muchos a uno** automática fuera del **control de gastos por sumas**.
- No se infiere que la diferencia final de saldos sea un error: puede haber partidas pendientes de períodos anteriores.
- Un mismo nombre y un importe coincidente no demuestran por sí mismos identidad, y el CUIT no figura en el mayor.
- Las **validaciones manuales son temporales** (solo la sesión actual); descargá el Excel para conservar el registro de revisión. No hay base de datos.
- Los totales de la categoría de gastos dependen del criterio de clasificación y del contenido real del pase; revisá el desglose y ajustá las categorías incluidas.
- No se modifica el procesador Galicia que ya tenés funcionando.
- Los archivos de bancos, clientes y reportes **no se incluyen** en el código ni deben subirse a GitHub. `.gitignore` excluye `.xlsx`, `.pdf` y `.csv`.

## Confidencialidad

El código no envía documentos a terceros ni guarda archivos de entrada deliberadamente en disco o base de datos, pero **Streamlit procesa los documentos en el servidor donde se despliega**. Para datos reales, utilizar hosting con acceso restringido y políticas de seguridad apropiadas. No exponer una instancia pública sin autenticación.

---

*Herramienta para uso interno AIE - Developers Alfonso Alderete -*
