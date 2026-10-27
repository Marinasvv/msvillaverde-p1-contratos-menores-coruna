"""
Paso 2 - Limpieza y transformación.

Lee la tabla "bronce" (data/processed/bronze_contratos_menores.csv, generada
por src/01_extract.py) y produce una tabla limpia y tipada en
data/processed/contratos_menores_limpio.csv, con una fila por línea de
contrato menor (expediente + adjudicatario + importe).

Se puede ejecutar varias veces: cada ejecución sobrescribe el fichero de
salida en vez de acumular filas duplicadas.

Las tres decisiones de limpieza (ver README para el detalle con ejemplos
reales de los datos):
  1. Cambios de tipos y formatos: fecha a datetime, importe a numerico
     (el origen mezcla "1234.56" y "1.234,56 e"), tipo_contrato unificado
     (letras A/E/C/Z en 2019-2020 vs. palabras en 2021).
  2. Tratamiento de nulos: se distingue entre "no disponible" (el dato no
     existe en el origen) y NIF "*" (persona fisica anonimizada a proposito
     por la propia fuente, no es un hueco).
  3. Duplicados: solo se elimina una fila si es idéntica en TODAS las
     columnas de negocio. No se usa el expediente como clave unica porque
     un mismo expediente puede repartirse en varias lineas legitimas con
     distintos adjudicatarios (p. ej. varios vecinos de una comunidad
     facturados por el mismo importe en el expediente 106/2020/72).
"""

import re
from pathlib import Path

import pandas as pd

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
IN_FILE = PROCESSED_DIR / "bronze_contratos_menores.csv"
OUT_FILE = PROCESSED_DIR / "contratos_menores_limpio.csv"

NO_DISPONIBLE = "no disponible"

# A partir de la subcabecera de los .ods ("A Obras, E Servicios, C
# Suministros, Z Otros") y de las palabras usadas tal cual en 2021.
TIPO_CONTRATO_MAP = {
    "a": "Obras",
    "e": "Servicios",
    "c": "Suministros",
    "z": "Otros",
    "obras": "Obras",
    "servicios": "Servicios",
    "suministro": "Suministros",
    "suministros": "Suministros",
    "otros": "Otros",
    "privado": "Privado",
    "concesion obras publicas": "Concesion de obras publicas",
}

BUSINESS_COLUMNS = [
    "expediente",
    "fecha_adjudicacion",
    "area_departamento",
    "objeto",
    "nif",
    "empresa_adjudicataria",
    "importe",
    "tipo_contrato",
    "anio",
    "trimestre",
]


# Correccion puntual de un alta duplicada por error de tecleo (revisado a
# mano: expediente 105/2020/1266, T1 2020, filas 555 y 557 del .ods
# original -> misma fecha, mismo NIF, mismo importe y la misma factura
# "2019/25" en el objeto; solo cambia "SERVICIO" por "SERVICIOS"). 
NOMBRE_EMPRESA_CORRECCIONES = {
    "SERVICIO DE HOSTELERIA OLLOMOL S.L.": "SERVICIOS DE HOSTELERIA OLLOMOL S.L.",
}

# Correcciones puntuales de area_departamento (revisado a mano, consulta de
# apoyo en sql/analisis.sql): el mismo area aparece partida en dos filas por
# un problema de codificacion del acento ("o"/"u" en vez de "o"/"u" con
# tilde/dieresis) en algunos trimestres. 
AREA_DEPARTAMENTO_CORRECCIONES = {
    "REHABILITACIoN Y VIVENDA RV1000": "REHABILITACIÓN Y VIVENDA RV1000",
    "NORMALIZACION LINGuISTICA GA2000": "NORMALIZACION LINGÜISTICA GA2000",
}

# Caso puntual (expediente GA2/2021/36, T3 2021, fila 448 del .ods): el area
# llegaba como "NORMALIZACION LINGÜISTICAA2:L615 GA2000" - un rango de celda
# de Excel ("A2:L615") colado dentro del texto por error de quien compilo el
# fichero origen. Se quita cualquier patron con esa forma (letra(s)+numero
# : letra(s)+numero) antes de aplicar las correcciones de arriba.
_PATRON_RANGO_EXCEL = re.compile(r"[A-Z]{1,2}\d+:[A-Z]{1,2}\d+")

_PATRON_MILES_SIN_COMA = re.compile(r"^\d{1,3}(\.\d{3})+\.\d{2}$")


def _parse_importe(valor):
    """Normaliza importes que llegan como '1234.56' o '1.234,56 €'."""
    if pd.isna(valor):
        return pd.NA
    s = str(valor).strip()
    s = s.replace("€", "").replace("EUR", "").strip()
    s = s.replace(" ", "")
    if "," in s and "." in s:
        # formato espanol: el punto es separador de miles, la coma es decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif _PATRON_MILES_SIN_COMA.match(s):
        # Caso puntual (expediente AD0/2021/130): "9.399.28" sin ninguna
        # coma. Se reconstruye uniendo los grupos de miles y usando
        # los 2 ultimos digitos como decimales.
        grupos = s.split(".")
        s = "".join(grupos[:-1]) + "." + grupos[-1]
    try:
        return float(s)
    except ValueError:
        return pd.NA


def _parse_fecha(serie: pd.Series) -> pd.Series:
    """La mayoría de ficheros guardan la fecha como 'YYYY-MM-DD HH:MM:SS',
    pero algunas filas de 2019 (T1 y T3) la traen como texto 'DD/MM/YYYY'.
    Se intenta primero el formato habitual y, para lo que quede sin
    convertir, se reintenta interpretando el día primero.
    """
    fecha = pd.to_datetime(serie, errors="coerce")
    pendientes = fecha.isna() & serie.notna()
    if pendientes.any():
        fecha_dayfirst = pd.to_datetime(serie[pendientes], errors="coerce", dayfirst=True)
        fecha.loc[pendientes] = fecha_dayfirst

    # Caso puntual (expediente 231/2019/290): "08/082019" en vez de
    # "08/08/2019".
    pendientes = fecha.isna() & serie.notna()
    if pendientes.any():
        reconstruida = serie[pendientes].str.replace(
            r"^(\d{2})/(\d{2})(\d{4})$", r"\1/\2/\3", regex=True
        )
        fecha.loc[pendientes] = pd.to_datetime(reconstruida, errors="coerce", dayfirst=True)
    return fecha


def _normalize_tipo_contrato(valor):
    if pd.isna(valor):
        return NO_DISPONIBLE
    v = str(valor).strip().lower()
    # quita acentos sueltos que llegaron mal codificados en el origen
    v = v.replace("ó", "o").replace("ú", "u")
    return TIPO_CONTRATO_MAP.get(v, str(valor).strip())


def _normalize_espacios(serie: pd.Series) -> pd.Series:
    """Colapsa espacios dobles/sueltos, quita el espacio antes de una coma y
    asegura que haya exactamente un espacio despues (ej. 'ROCA,OCTAVIO' ->
    'ROCA, OCTAVIO'). Encontrado con 65 filas afectadas al revisar el
    ranking de empresas en Power BI: el expediente 541/2019/1868 (NIF "*")
    quedaba separado del resto de contratos de la misma persona porque a
    "VILLAZALA ROCA,OCTAVIO" le faltaba el espacio tras la coma - la regla
    anterior solo comprobaba el espacio ANTES de la coma, no despues.
    """
    s = serie.str.strip()
    s = s.str.replace(r"\s+", " ", regex=True)
    s = s.str.replace(r"\s+,", ",", regex=True)
    s = s.str.replace(r",(?=\S)", ", ", regex=True)
    return s


_PATRON_NIF_ANONIMIZADO = re.compile(r"^\*+$")


def _normalize_nif(valor):
    if pd.isna(valor):
        return NO_DISPONIBLE
    v = str(valor).strip()
    if _PATRON_NIF_ANONIMIZADO.match(v):
        # La fuente no usa siempre el mismo marcador de anonimizacion: la
        # mayoria de trimestres usan "*", pero T4 2021 usa "*****" (191
        # filas).
        return "*"
    return v  # "*" se deja tal cual: es una anonimizacion deliberada de la fuente, no un hueco


def clean() -> pd.DataFrame:
    df = pd.read_csv(IN_FILE, dtype=str)

    df = df.rename(
        columns={
            "referencia": "expediente",
            "area_tramitadora": "area_departamento",
            "nombre_adjudicatario": "empresa_adjudicataria",
        }
    )

    # 1. Tipos y formatos
    df["empresa_adjudicataria"] = _normalize_espacios(df["empresa_adjudicataria"])
    df["empresa_adjudicataria"] = df["empresa_adjudicataria"].replace(NOMBRE_EMPRESA_CORRECCIONES)
    df["objeto"] = _normalize_espacios(df["objeto"])
    df["area_departamento"] = df["area_departamento"].str.replace(_PATRON_RANGO_EXCEL, "", regex=True)
    df["area_departamento"] = _normalize_espacios(df["area_departamento"])
    df["area_departamento"] = df["area_departamento"].replace(AREA_DEPARTAMENTO_CORRECCIONES)
    df["fecha_adjudicacion"] = _parse_fecha(df["fecha_adjudicacion"])
    df["importe"] = df["importe"].apply(_parse_importe)
    df["tipo_contrato"] = df["tipo_contrato"].apply(_normalize_tipo_contrato)
    df["anio"] = df["anio"].astype(int)
    df["trimestre"] = df["trimestre"].astype(int)

    # 2. Nulos: texto -> "no disponible" si realmente falta (no para el NIF
    # marcado con "*", que es una anonimizacion intencionada de la fuente).
    df["nif"] = df["nif"].apply(_normalize_nif)
    for col in ["expediente", "objeto", "area_departamento", "empresa_adjudicataria"]:
        df[col] = df[col].fillna(NO_DISPONIBLE)
    # importe y fecha son numericos/fecha: si faltan se deja nulo (NaN/NaT)
    # y se documenta el recuento en vez de inventar un valor.

    # 3. Duplicados: solo fila idéntica en todas las columnas de negocio.
    before = len(df)
    df = df.drop_duplicates(subset=BUSINESS_COLUMNS, keep="first")
    removed = before - len(df)

    # 3b. Republicacion entre trimestres: el mismo contrato (mismo expediente,
    # fecha, NIF, empresa, importe, objeto y area) aparece tal cual en el
    # fichero del trimestre siguiente. No lo detecta el paso anterior porque
    # BUSINESS_COLUMNS incluye anio/trimestre a proposito (ver comentario de
    # esa lista) y aqui es precisamente lo que hay que ignorar. No se usa
    # tipo_contrato en esta clave: en T1 2019 esa columna no existe nunca
    # ("no disponible"), y un contrato real republicado en T2 con el tipo ya
    # informado no deberia tratarse como "distinto" solo por eso (caso real:
    # expediente 230/2019/158). Se ordena por anio/trimestre antes de
    # eliminar para conservar la primera publicacion, no la mas tardia.
    columnas_republicacion = [
        "expediente",
        "fecha_adjudicacion",
        "nif",
        "empresa_adjudicataria",
        "importe",
        "objeto",
        "area_departamento",
    ]
    df = df.sort_values(["anio", "trimestre"])
    before_republicacion = len(df)
    df = df.drop_duplicates(subset=columnas_republicacion, keep="first")
    removidos_por_republicacion = before_republicacion - len(df)
    removed += removidos_por_republicacion

    # 3c. Misma transaccion en dos fases administrativas distintas: mismo
    # expediente + NIF + importe, pero con fecha semanas/meses posterior y
    # el objeto de la segunda fila añadiendo el prefijo "ADO - FRA. ..."
    #
    # Se excluyen a proposito los expedientes GEY/2020/54 y GEY/2020/64: su
    # objeto cita dos fechas de eleccion REALES distintas (5 de abril,
    # aplazada por el COVID, y 12 de julio, la definitiva).
    # Tambien se incluye empresa_adjudicataria en la clave: el NIF "*" no
    # identifica a nadie (lo vimos al diseñar dim_empresa).
    # 10C/2021/8 tambien se excluye: mismo importe y empresa, pero el
    # objeto cita matriculas de vehiculo DISTINTAS
    EXPEDIENTES_EXCLUIDOS_FASE_ADMINISTRATIVA = {"GEY/2020/54", "GEY/2020/64", "10C/2021/8"}
    columnas_fase_administrativa = ["expediente", "nif", "importe", "empresa_adjudicataria"]

    excluidos = df["expediente"].isin(EXPEDIENTES_EXCLUIDOS_FASE_ADMINISTRATIVA)
    df_depurable = df[~excluidos].sort_values(["fecha_adjudicacion"])
    before_fase = len(df_depurable)
    df_depurable = df_depurable.drop_duplicates(subset=columnas_fase_administrativa, keep="first")
    removidos_por_fase_administrativa = before_fase - len(df_depurable)
    removed += removidos_por_fase_administrativa

    df = pd.concat([df_depurable, df[excluidos]], ignore_index=True)

    df = df.sort_values(["anio", "trimestre", "expediente"]).reset_index(drop=True)
    return df, removed, removidos_por_republicacion, removidos_por_fase_administrativa


def main():
    df, removed, removidos_por_republicacion, removidos_por_fase_administrativa = clean()
    df.to_csv(OUT_FILE, index=False, encoding="utf-8")

    print(f"Filas de entrada (bronce): {removed + len(df)}")
    print(f"Duplicados eliminados (total): {removed}")
    print(f"  De los cuales, republicados en el trimestre siguiente: {removidos_por_republicacion}")
    print(f"  De los cuales, misma transaccion en 2 fases administrativas (adjudicacion + ADO-FRA): {removidos_por_fase_administrativa}")
    print(f"Filas finales: {len(df)}")
    print()
    print("Nulos tras limpieza:")
    print(f"  importe sin valor: {df['importe'].isna().sum()}")
    print(f"  fecha sin valor:   {df['fecha_adjudicacion'].isna().sum()}")
    print(f"  tipo_contrato = '{NO_DISPONIBLE}': {(df['tipo_contrato'] == NO_DISPONIBLE).sum()}")
    print(f"  nif anonimizado ('*'): {(df['nif'] == '*').sum()}")
    print(f"  nif = '{NO_DISPONIBLE}': {(df['nif'] == NO_DISPONIBLE).sum()}")
    print()
    print(f"Guardado en: {OUT_FILE}")


if __name__ == "__main__":
    main()
