"""
Paso 5 (extra) - Agente de preguntas en lenguaje natural sobre el modelo.

Traduce una pregunta en español a una consulta SQL sobre el esquema en
estrella ya cargado en Snowflake (fact_contratos + 4 dimensiones), la
ejecuta, y devuelve una respuesta en lenguaje natural basada solo en el
resultado real de esa consulta.

Se probo primero con Snowflake Cortex/AI SQL (funciones SNOWFLAKE.CORTEX.
COMPLETE y AI_COMPLETE), pero ambas estan bloqueadas en cuentas trial de
Snowflake ("not available for trial accounts"). Por eso el LLM que traduce
la pregunta a SQL y redacta la respuesta corre en local con Ollama
(https://ollama.com) - 100% gratis, sin API key ni tarjeta de credito,
nunca sale de tu equipo. Snowflake se sigue usando solo para EJECUTAR la
SQL generada y leer los datos reales, igual que el resto del proyecto.

Requisitos:
    - Ollama instalado y corriendo (servicio local en http://localhost:11434)
    - Un modelo descargado, ej.: ollama pull llama3.1:8b

Uso:
    python src/05_agent.py "¿Cuantos contratos hubo en 2020?"
    python src/05_agent.py            # modo interactivo (varias preguntas)

Credenciales de Snowflake: igual que src/04_load_snowflake.py, en .env.
"""

import os
import re
import sys
from pathlib import Path

import requests
import snowflake.connector
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent

VARS_REQUERIDAS = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
]

# Se puede cambiar el modelo con OLLAMA_MODEL en .env (ej. "llama3.1:70b" si
# tu equipo lo soporta, o "qwen2.5:7b"). Debe estar descargado antes
# (ollama pull <modelo>).
MODELO_POR_DEFECTO = "llama3.1:8b"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")

# Palabras que no debe contener la SQL generada: el agente solo puede LEER
# datos, nunca modificar el modelo ni la cuenta.
PALABRAS_PROHIBIDAS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "MERGE", "GRANT", "REVOKE", "CALL", "COPY", "PUT", "GET", "EXECUTE",
    "UNLOAD", "REMOVE",
]

ESQUEMA_CONTEXTO = """
Eres un analista de datos. Tienes acceso de SOLO LECTURA a un esquema en
estrella en Snowflake sobre contratos menores publicados por el Concello
da Coruña (2019-2021). NUNCA generes SQL que modifique datos (solo SELECT).

Tablas y columnas:

FACT_CONTRATOS (una fila por linea de contrato publicada)
  - EXPEDIENTE (texto, identificador del contrato, no unico: un mismo
    expediente puede repartirse en varias lineas/adjudicatarios)
  - OBJETO (texto, descripcion del contrato)
  - FECHA_KEY (entero, formato YYYYMMDD, -1 = fecha no disponible/fuera de
    rango; se une con DIM_FECHA.FECHA_KEY)
  - EMPRESA_KEY, AREA_KEY, TIPO_CONTRATO_KEY (enteros, -1 = "no disponible";
    se unen con las dimensiones correspondientes)
  - IMPORTE_CON_IVA (numero, el importe publicado tal cual)
  - IMPORTE_SIN_IVA_ESTIMADO (numero, = IMPORTE_CON_IVA / 1.21)
  - SUPERA_UMBRAL, CERCA_UMBRAL (booleanos YA CALCULADOS, respecto al
    umbral legal de DIM_TIPO_CONTRATO.UMBRAL_SIN_IVA; mutuamente
    excluyentes). Para cualquier pregunta sobre contratos que superan,
    estan cerca de, o se comparan con el umbral legal, usa DIRECTAMENTE
    estas 2 columnas (ej. WHERE SUPERA_UMBRAL = TRUE) - NUNCA recalcules
    la comparacion tu mismo con una subconsulta a DIM_TIPO_CONTRATO
    correlacionada con FACT_CONTRATOS en el WHERE (ese patron suele dar
    error "Unsupported subquery type" en Snowflake). Si necesitas el
    propio umbral en el resultado (no solo filtrar), entonces si haz JOIN
    normal con DIM_TIPO_CONTRATO.
  - ANIO_PUBLICACION, TRIMESTRE_PUBLICACION (trimestre del fichero de origen,
    puede diferir del trimestre de la fecha de adjudicacion real)

DIM_FECHA (un dia natural por fila, 2019-01-01 a 2021-12-31)
  - FECHA_KEY, FECHA, ANIO, MES, NOMBRE_MES, DIA_SEMANA
  - PERIODO_COVID: 'Pre-COVID' (hasta 2020-03-13), 'Estado de alarma'
    (2020-03-14 a 2021-05-09), 'Post-estado de alarma' (resto), o
    'no disponible' (fila -1)

DIM_EMPRESA (una fila por adjudicatario)
  - EMPRESA_KEY, NIF, NOMBRE_NORMALIZADO (texto EN MAYUSCULAS, formato
    variable: empresas llevan su forma juridica al final, ej.
    "CONSTRUCCIONES LOPEZ CAO S.L."; personas fisicas van como "APELLIDOS,
    NOMBRE", ej. "VILLAZALA ROCA, OCTAVIO". NUNCA compares con = exacto
    contra el nombre tal como lo escriba el usuario (puede venir sin
    mayusculas, sin coma, sin "S.L.", con o sin tildes) - usa siempre
    ILIKE '%palabra_clave%' con una palabra clave del nombre, ej. para
    "Construcciones Lopez Cao" o "Villazala Roca" usa
    NOMBRE_NORMALIZADO ILIKE '%LOPEZ CAO%' o ILIKE '%VILLAZALA%'.
  - TIPO_PERSONA: 'Persona juridica' / 'Persona fisica identificada' /
    'Persona fisica anonimizada' / 'no disponible'. "Personas fisicas" (sin
    mas detalle) significa TIPO_PERSONA IN ('Persona fisica identificada',
    'Persona fisica anonimizada') - las DOS categorias juntas. Usa solo
    una de las dos UNICAMENTE si la pregunta dice "identificadas" o
    "anonimizadas" explicitamente.
  - FORMA_JURIDICA (ej. 'Sociedad Limitada', deducida del NIF; solo aplica
    a personas juridicas)

DIM_AREA (una fila por area/departamento municipal)
  - AREA_KEY, AREA_DEPARTAMENTO (texto, formato "NOMBRE EN MAYUSCULAS
    CODIGO", ej. "GESTION DE DEPORTES DJ1000", "SERVICIOS GENERALES DE
    INFRAESTRUCTURAS IE3000" - el nombre no es exacto/corto, compara
    siempre con ILIKE '%palabras clave%', nunca con = exacto)

DIM_TIPO_CONTRATO (una fila por tipo de contrato)
  - TIPO_CONTRATO_KEY, TIPO_CONTRATO ('Obras'/'Servicios'/'Suministros'/
    'Privado'/'Otros'/'no disponible')
  - UMBRAL_SIN_IVA (numero o NULL: 40000 para Obras, 15000 para
    Servicios/Suministros/Otros, NULL si no aplica umbral legal)

Reglas importantes:
  - Para "cuantos contratos" usa SIEMPRE COUNT(*), nunca COUNT(de una
    columna como EXPEDIENTE) ni COUNT(DISTINCT EXPEDIENTE): una fila de
    FACT_CONTRATOS ya es una linea de contrato publicada (el grano del
    modelo), y COUNT(columna) descarta filas si esa columna es NULL en
    alguna, dando un numero mas bajo que el real sin motivo. Un mismo
    EXPEDIENTE puede ademas repartirse legitimamente en varias lineas
    distintas (varios adjudicatarios), asi que COUNT(DISTINCT EXPEDIENTE)
    tambien infracuenta el numero real de contratos. Usa COUNT(DISTINCT
    EXPEDIENTE) solo si la pregunta pide explicitamente el numero de
    expedientes distintos, no el numero de contratos/lineas.
    REGLA DE ORO, repetida porque es el error mas comun: para contar
    contratos, la unica forma correcta es "COUNT(*)". Mal: COUNT(EXPEDIENTE),
    COUNT(DISTINCT EXPEDIENTE), COUNT(FECHA_KEY). Bien: COUNT(*).
  - Para evolucion temporal ("por año", "por mes", "en estado de alarma")
    usa siempre DIM_FECHA (fecha de adjudicacion real), no
    ANIO_PUBLICACION/TRIMESTRE_PUBLICACION de FACT_CONTRATOS. Si usas una
    columna de DIM_FECHA (o de cualquier dimension), SIEMPRE incluye su
    JOIN correspondiente en el FROM - nunca references DIM_FECHA.columna,
    DIM_EMPRESA.columna, etc. sin haber unido esa tabla antes.
  - "¿Que mes/año tuvo mas gasto/contratos?": "gasto" significa
    SUM(IMPORTE_CON_IVA) (el total sumado), NUNCA MAX(IMPORTE_CON_IVA) (eso
    seria "el contrato individual mas caro", una pregunta distinta).
    NUNCA incluyas FECHA_KEY (el dia exacto) en el GROUP BY de este tipo
    de pregunta - eso agrupa por DIA, no por mes, y da un resultado sin
    sentido. Agrupa SOLO por DIM_FECHA.ANIO, DIM_FECHA.MES (asi obtienes
    el mes-año concreto con mas gasto, ej. "noviembre de 2020" - la
    interpretacion por defecto, mas informativa). Si la pregunta dice
    explicitamente "en que mes DEL AÑO" o "estacionalidad" (sin importar
    el año), agrupa SOLO por DIM_FECHA.MES (sumando los 3 años).
    IMPORTANTE sobre GROUP BY en Snowflake (modo estricto): toda columna
    del SELECT que no este dentro de una funcion de agregacion (SUM,
    COUNT, MAX...) tiene que estar TAMBIEN en el GROUP BY - incluye ahi
    tambien columnas descriptivas como NOMBRE_MES, no solo ANIO/MES.
    En la respuesta final, menciona siempre el NOMBRE_MES ademas del
    numero, y el año si lo agrupaste.
  - Si la pregunta implica comparar con el umbral legal, usa
    DIM_TIPO_CONTRATO.UMBRAL_SIN_IVA y FACT_CONTRATOS.IMPORTE_SIN_IVA_ESTIMADO,
    nunca el importe con IVA.
  - "El area de X" / "el area X" significa SIEMPRE un JOIN con DIM_AREA y
    filtrar AREA_DEPARTAMENTO ILIKE '%X%' - NUNCA busques "X" en OBJETO ni
    en DIM_EMPRESA.NOMBRE_NORMALIZADO, un area no es una empresa ni texto
    libre del objeto.
  - Las claves -1 / 'no disponible' representan datos ausentes EN ESA
    DIMENSION CONCRETA. Excluyelas con un WHERE SOLO si la pregunta usa esa
    dimension concreta (filtra, agrupa o muestra ESA dimension en el
    resultado). Regla practica: por cada dimension que uses en el WHERE
    != -1, pregunate "¿la pregunta del usuario menciona o usa esta
    dimension?" - si la respuesta es no, no añadas ese filtro. Ejemplos:
      * "cuantos contratos hubo en 2019" -> solo usa fecha, NO filtres por
        EMPRESA_KEY, TIPO_CONTRATO_KEY ni AREA_KEY.
      * "que area tiene mas contratos" -> solo usa area (agrupa por area),
        NO filtres por EMPRESA_KEY ni TIPO_CONTRATO_KEY, solo AREA_KEY!=-1.
      * "gasto de la empresa X" -> solo usa empresa, NO filtres por area
        ni tipo_contrato.
    Añadir filtros "por si acaso" sobre dimensiones que la pregunta no usa
    produce un resultado mas bajo que el real y es un error, no una
    precaucion.
  - Al hacer GROUP BY para encontrar "el X con mas/menos Y" (ej. "el mes
    con mas gasto", "la empresa con mas contratos"): la columna que mides
    (gasto, nº contratos...) va SIEMPRE dentro de una funcion de
    agregacion en el SELECT y en el ORDER BY (SUM(...), COUNT(...)),
    NUNCA suelta en el GROUP BY - meter la columna a medir en el GROUP BY
    agrupa fila a fila (sin agregar nada) y da un resultado sin sentido.
  - Al ordenar DESC por una columna numerica que puede tener NULL (ej.
    IMPORTE_CON_IVA, o cualquier SUM/AVG de ella), añade siempre
    "NULLS LAST" al ORDER BY - en Snowflake, por defecto, NULL se ordena
    PRIMERO en DESC, asi que sin NULLS LAST una fila sin importe puede
    salir como si fuera "la mayor".
  - Para calcular un PORCENTAJE (ej. "que % son de X"), NUNCA uses una
    subconsulta separada para el denominador con el mismo WHERE que el
    numerador (eso da 100% siempre, es un error logico grave: numerador y
    denominador quedan filtrados igual). Usa en su lugar, en una sola
    consulta sin WHERE que reduzca el total:
    ROUND(100.0 * COUNT(CASE WHEN <condicion> THEN 1 END) / COUNT(*), 2)
    donde COUNT(*) es el total SIN filtrar (todas las filas relevantes) y
    COUNT(CASE WHEN...) solo cuenta las que cumplen la condicion.
  - Prefiere la consulta mas simple posible: un JOIN directo en vez de
    subconsultas/IFF anidados cuando un JOIN simple ya responde la pregunta.
  - Si el FROM tiene mas de una tabla (por un JOIN), usa SIEMPRE un alias
    corto para cada tabla (ej. FACT_CONTRATOS F, DIM_AREA A) y cualifica
    con ese alias TODAS las columnas en SELECT/WHERE/GROUP BY/ORDER BY
    (ej. F.AREA_KEY, no AREA_KEY a secas) - una columna sin cualificar que
    existe en mas de una tabla del FROM da error "ambiguous column name".
  - Si la pregunta no se puede responder con este esquema, genera una
    consulta que devuelva un unico mensaje de texto explicandolo (ej.
    SELECT 'La pregunta no se puede responder con este esquema' AS aviso).
"""


def _conectar():
    load_dotenv(ROOT_DIR / ".env")
    faltan = [v for v in VARS_REQUERIDAS if not os.environ.get(v)]
    if faltan:
        print(f"Faltan variables de entorno en .env: {', '.join(faltan)}")
        sys.exit(1)

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
    )


def _llm_completar(prompt: str, modelo: str) -> str:
    """Llama al modelo local de Ollama (gratis, corre en el propio equipo)."""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": modelo, "prompt": prompt, "stream": False},
            # 240s: la primera llamada tras 5 min de inactividad obliga a
            # Ollama a recargar el modelo (~5GB) desde disco a memoria, lo
            # que en un equipo sin GPU puede superar los 120s por si solo,
            # antes incluso de empezar a generar.
            timeout=240,
        )
        resp.raise_for_status()
    except requests.exceptions.ReadTimeout:
        print(
            "\nOllama tardo demasiado en responder (mas de 240s).\n"
            "Es normal la primera vez tras un rato sin usarlo (recarga el "
            "modelo en memoria) - vuelve a intentar la misma pregunta, "
            "deberia ir mas rapido ya con el modelo cargado.\n"
        )
        raise
    except requests.exceptions.ConnectionError:
        print(
            "\nNo se pudo conectar con Ollama en http://localhost:11434.\n"
            "Asegurate de que la aplicacion/servicio Ollama esta corriendo "
            "(se inicia solo tras instalarlo, o ejecuta 'ollama serve').\n"
        )
        raise
    except requests.exceptions.HTTPError as e:
        print(
            f"\nOllama devolvio un error para el modelo '{modelo}'.\n"
            f"Puede que falte descargarlo: ejecuta 'ollama pull {modelo}' y "
            "reintenta, o cambia OLLAMA_MODEL en .env a otro ya descargado.\n"
        )
        raise e
    return resp.json()["response"]


def _extraer_sql(texto_modelo: str) -> str:
    """El modelo a veces envuelve la SQL en ```sql ... ``` o añade texto
    alrededor; nos quedamos solo con la consulta."""
    m = re.search(r"```(?:sql)?\s*(.*?)```", texto_modelo, re.DOTALL | re.IGNORECASE)
    sql = m.group(1) if m else texto_modelo
    sql = sql.strip().rstrip(";").strip()
    return sql


def _validar_sql(sql: str) -> None:
    primera_palabra = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
    if primera_palabra not in ("SELECT", "WITH"):
        raise ValueError(f"La consulta generada no empieza por SELECT/WITH:\n{sql}")
    for palabra in PALABRAS_PROHIBIDAS:
        if re.search(rf"\b{palabra}\b", sql, re.IGNORECASE):
            raise ValueError(f"La consulta generada contiene '{palabra}', no permitido:\n{sql}")


def _con_limite(sql: str, limite: int = 200) -> str:
    if re.search(r"\blimit\b", sql, re.IGNORECASE):
        return sql
    return f"{sql}\nLIMIT {limite}"


def _ejecutar(conn, sql: str):
    cur = conn.cursor()
    try:
        cur.execute(sql)
        columnas = [c[0] for c in cur.description]
        filas = cur.fetchall()
        return columnas, filas
    finally:
        cur.close()


def _formatear_resultado(columnas, filas, max_filas: int = 30) -> str:
    if not filas:
        return "(sin filas)"
    lineas = [" | ".join(columnas)]
    for fila in filas[:max_filas]:
        lineas.append(" | ".join(str(v) for v in fila))
    if len(filas) > max_filas:
        lineas.append(f"... ({len(filas) - max_filas} filas mas, no mostradas)")
    return "\n".join(lineas)


MAX_REINTENTOS_SQL = 3


def _generar_y_ejecutar_sql(conn, pregunta: str, modelo: str):
    """Pide la SQL al modelo y la ejecuta; si falla (sintaxis, columna
    inexistente...), le devuelve el error al modelo para que la corrija,
    hasta MAX_REINTENTOS_SQL veces. Es la parte "agente" del script: no se
    limita a una sola llamada ciega, repara sus propios fallos con el
    mensaje de error real de Snowflake."""
    prompt = f"""{ESQUEMA_CONTEXTO}

Pregunta del usuario: "{pregunta}"

Genera UNA sola consulta SQL (dialecto Snowflake) que responda a la
pregunta usando exclusivamente las tablas de arriba. Devuelve solo la
consulta SQL, sin explicaciones, dentro de un bloque ```sql ... ```."""

    error_previo = None
    for intento in range(1, MAX_REINTENTOS_SQL + 2):
        if error_previo:
            prompt_actual = f"""{prompt}

Tu intento anterior fue:
```sql
{sql}
```
Snowflake devolvio este error al ejecutarla:
{error_previo}

Corrige la consulta completa (dialecto Snowflake: usa IFF() en vez de
IF(); si usas JOIN con alias para una tabla, ej. "DIM_FECHA D", usa ese
alias en TODAS las referencias a esa tabla en toda la consulta, no dejes
ninguna mezclada con el nombre completo de la tabla). Revisa la consulta
entera antes de responder, no solo la parte que dio el error. Devuelve
solo la consulta SQL corregida completa, dentro de un bloque
```sql ... ```."""
        else:
            prompt_actual = prompt

        etiqueta = "Generando SQL" if intento == 1 else f"Corrigiendo SQL (intento {intento})"
        print(f"\n[{etiqueta} con Ollama (local)...]")
        respuesta_sql = _llm_completar(prompt_actual, modelo)
        sql = _extraer_sql(respuesta_sql)

        try:
            _validar_sql(sql)
        except ValueError as e:
            print(f"\nConsulta generada rechazada por seguridad:\n{e}")
            return None, None, None

        sql_con_limite = _con_limite(sql)
        print(f"\nSQL generada:\n{sql_con_limite}\n")

        try:
            columnas, filas = _ejecutar(conn, sql_con_limite)
            return sql_con_limite, columnas, filas
        except Exception as e:
            error_previo = str(e)
            print(f"Error ejecutando la SQL generada: {error_previo}")
            if intento <= MAX_REINTENTOS_SQL:
                continue
            print("Se agotaron los reintentos de autocorrección.")
            return None, None, None


def preguntar(conn, pregunta: str, modelo: str) -> None:
    sql, columnas, filas = _generar_y_ejecutar_sql(conn, pregunta, modelo)
    if sql is None:
        return

    tabla_resultado = _formatear_resultado(columnas, filas)
    print(f"Resultado ({len(filas)} fila(s)):\n{tabla_resultado}\n")

    prompt_respuesta = f"""Pregunta original del usuario: "{pregunta}"

Resultado real de la consulta SQL ejecutada sobre los datos:
{tabla_resultado}

Responde a la pregunta en español, usando EXCLUSIVAMENTE las cifras de
este resultado (no inventes ni redondees de más). Si hay al menos una
fila en el resultado (aunque haya varias, o esten empatadas), SIEMPRE hay
datos suficientes: responde con esas cifras, no digas que faltan datos.
Di "no hay datos suficientes" UNICAMENTE si el resultado es literalmente
"(sin filas)".

Si el resultado tiene 1 sola fila, responde en 1-2 frases con esa cifra.
Si tiene VARIAS filas (2 o mas), NO resumas solo con el minimo/maximo o
una sola fila: lista cada fila en una linea propia con sus valores
principales (ej. "- 2020-01-22 (541/2020/161): gastos de residencia..."),
y añade una frase final de conclusion si aporta algo. No omitas filas."""

    print("[Generando respuesta...]")
    respuesta = _llm_completar(prompt_respuesta, modelo)
    print(f"\nRespuesta:\n{respuesta.strip()}\n")
    print("-" * 70)


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    modelo = os.environ.get("OLLAMA_MODEL", MODELO_POR_DEFECTO)
    conn = _conectar()
    try:
        if len(sys.argv) > 1:
            pregunta = " ".join(sys.argv[1:])
            preguntar(conn, pregunta, modelo)
        else:
            print("Agente de preguntas sobre contratos menores (Ctrl+C para salir)")
            print(f"Modelo Ollama: {modelo}\n")
            while True:
                try:
                    pregunta = input("Pregunta> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not pregunta:
                    continue
                preguntar(conn, pregunta, modelo)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
