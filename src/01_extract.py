"""
Paso 1 - Extraccion.

Lee los ficheros trimestrales de "contratos menores" del Concello da Coruna
(2019-2021, periodo elegido para comparar antes/durante/despues del COVID)
desde data/raw/ y los consolida en una unica tabla "bronce" (sin tipado ni
limpieza todavia) en data/processed/bronze_contratos_menores.csv.

Se puede ejecutar varias veces: cada ejecucion sobrescribe el fichero de
salida en vez de acumular filas duplicadas.

Decision de formato (ver README para el detalle): el portal no usa una
plantilla estable. Hay dos layouts que se alternan sin relacion con la
extension del fichero (.xlsx u .ods):

  - "plano": la cabecera ocupa la fila 0 y los datos empiezan en la fila 1
    (ej. 2019 T1). No tiene columna de tipo de contrato.
  - "con portada": varias filas de titulo/aviso legal, luego la fila de
    cabecera real (localizada buscando la celda "Referencia") y una fila
    de subcabecera que se descarta (ej. 2019 T2-T4 y todo 2020-2021).
    El numero de columnas y su orden cambian de un trimestre a otro, asi
    que el mapeo se hace por el texto de la cabecera, no por posicion fija.
"""

from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
OUT_FILE = OUT_DIR / "bronze_contratos_menores.csv"

# (fichero, anio, trimestre)
MANIFEST = [
    ("201901_Menores_1er_trimestre_2019.xlsx", 2019, 1),
    ("201902_Menores_2__trimestre_2019.xlsx", 2019, 2),
    ("201903_Menores_3er_trimestre_2019.xlsx", 2019, 3),
    ("201904_Menores_4__trimestre_2019_open_document.ods", 2019, 4),
    ("202001_PUBLICACION_MENORES_PRIMER_TRIMESTRE_2020.ods", 2020, 1),
    ("202002_PUBLICACION_MENORES_SEGUNDO_TRIMESTRE_2020.ods", 2020, 2),
    ("202003_PUBLICACION_MENORES_TERCER_TRIMESTRE_2020.ods", 2020, 3),
    ("202004_PUBLICACION_MENORES_CUARTO_TRIMESTRE_2020.ods", 2020, 4),
    ("202101_PUBLICACION_MENORES_PRIMER_TRIMESTRE_2021.ods", 2021, 1),
    ("202102_PUBLICACION_MENORES_SEGUNDO_TRIMESTRE_2021.ods", 2021, 2),
    ("202103_PUBLICACION_MENORES_TERCEIRO_TRIMESTRE_2021.ods", 2021, 3),
    ("202104_PUBLICACION_MENORES_CUARTO_TRIMESTRE_2021.ods", 2021, 4),
]

CANONICAL_COLUMNS = [
    "referencia",
    "tipo_contrato",
    "objeto",
    "fecha_adjudicacion",
    "nif",
    "nombre_adjudicatario",
    "importe",
    "area_tramitadora",
]

# Mapeo por posicion para el layout "plano" (cabecera en fila 0, ej. 2019 T1).
FLAT_HEADER_POSITIONS = {
    0: "referencia",
    1: "nif",
    2: "nombre_adjudicatario",
    3: "area_tramitadora",
    4: "objeto",
    5: "fecha_adjudicacion",
    6: "importe",
    # columnas 7 y 8 (tecnico responsable, duracion) no forman parte del
    # esquema comun: no existen en el resto de trimestres.
}


def _read_raw(path: Path) -> pd.DataFrame:
    engine = "odf" if path.suffix == ".ods" else None
    return pd.read_excel(path, engine=engine, header=None)


def _is_flat_header(raw: pd.DataFrame) -> bool:
    first_cell = raw.iloc[0, 0]
    return isinstance(first_cell, str) and first_cell.strip().lower() == "expediente."


def _find_header_row(raw: pd.DataFrame) -> int:
    for i in range(min(15, len(raw))):
        row = raw.iloc[i]
        for v in row:
            if isinstance(v, str) and v.strip().lower() == "referencia":
                return i
    raise ValueError("No se encontro la fila de cabecera (celda 'Referencia')")


def _map_header(header_row: pd.Series) -> dict:
    mapping = {}
    for idx, val in header_row.items():
        if not isinstance(val, str):
            continue
        v = val.strip().lower()
        if v == "referencia":
            mapping[idx] = "referencia"
        elif "tipo" in v and "contrato" in v:
            mapping[idx] = "tipo_contrato"
        elif v == "objeto":
            mapping[idx] = "objeto"
        elif v.startswith("fecha adj"):
            mapping[idx] = "fecha_adjudicacion"
        elif v == "nif":
            mapping[idx] = "nif"
        elif "nombre adjudicatario" in v:
            mapping[idx] = "nombre_adjudicatario"
        elif "precio adjudicaci" in v:
            mapping[idx] = "importe"
        elif v == "negociado":
            mapping[idx] = "area_tramitadora"
    return mapping


def _read_one(path: Path) -> pd.DataFrame:
    raw = _read_raw(path)

    if _is_flat_header(raw):
        data = raw.iloc[1:].copy()
        # Fila tal como se ve en la hoja de calculo (Excel/LibreOffice
        # empiezan a contar en 1): sirve para localizar el registro
        data["fila_origen"] = data.index + 1
        data = data.rename(columns=FLAT_HEADER_POSITIONS)
        data = data[[c for c in FLAT_HEADER_POSITIONS.values()] + ["fila_origen"]]
        data["tipo_contrato"] = pd.NA
    else:
        header_row_idx = _find_header_row(raw)
        mapping = _map_header(raw.iloc[header_row_idx])
        data = raw.iloc[header_row_idx + 2 :].copy()
        data["fila_origen"] = data.index + 1
        data = data.rename(columns=mapping)
        data = data[[c for c in mapping.values()] + ["fila_origen"]]

    total_antes = len(data)
    # Descarta filas de relleno sin referencia (huecos al final del rango
    # de celdas de la hoja, frecuentes en los .ods).
    data = data[data["referencia"].notna() & (data["referencia"].astype(str).str.strip() != "")]
    descartadas = total_antes - len(data)
    print(f"  {path.name}: {descartadas} filas de relleno descartadas (de {total_antes})")
    return data


def extract() -> pd.DataFrame:
    frames = []
    for filename, year, quarter in MANIFEST:
        path = RAW_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Falta el fichero de origen: {path}")
        df = _read_one(path)
        for col in CANONICAL_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        df = df[CANONICAL_COLUMNS + ["fila_origen"]].copy()
        df["anio"] = year
        df["trimestre"] = quarter
        df["fichero_origen"] = filename
        frames.append(df)

    full = pd.concat(frames, ignore_index=True)
    return full


def main():
    df = extract()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False, encoding="utf-8")
    print(f"Filas extraidas: {len(df)}")
    print(df.groupby(["anio", "trimestre"]).size())
    print(f"Guardado en: {OUT_FILE}")


if __name__ == "__main__":
    main()
