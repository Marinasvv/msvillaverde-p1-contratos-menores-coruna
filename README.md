# Contratos menores — Concello da Coruña

Pipeline de datos (fuente pública → limpieza → Snowflake → SQL → Power BI) sobre los contratos menores publicados por el Concello da Coruña, con foco en comparar la contratación antes, durante y después del COVID (2019-2021). Proyecto del reto práctico de datos descrito en [docs/enunciado.md](docs/enunciado.md).

## Fuente de datos

- **Organismo:** Concello da Coruña – Portal de Transparencia
- **Página:** https://www.coruna.gal/transparencia/es/claridad-en-la-gestion/contratacion/contratos-menores?argIdioma=es
- **Formato:** hoja de cálculo. T1-T3 2019 son `.xlsx`; T4 2019 y todo 2020-2021 son `.ods`. Un fichero por trimestre.
- **Cobertura elegida:** 1 de enero de 2019 a 31 de diciembre de 2021 (3 años completos, 12 trimestres)
- **Por qué este rango:** se eligió para poder comparar un año "normal" (2019) con el año de la pandemia (2020, estado de alarma desde marzo) y el año de recuperación (2021), y así responder si la contratación de emergencia por COVID dejó huella visible en los contratos menores.
- **Base legal:** El RD-ley 3/2020 (BOE 5/02/2020) modificó este artículo dentro de nuestro periodo pero no cambió estas cifras, solo añadió la exigencia de un informe de justificación.
  - ⚠️ **El umbral legal excluye el IVA, pero nuestra columna `importe` lo incluye** (la propia cabecera del origen dice "Precio de adjudicación **con IVA**").

| Fichero                                                | Periodo | Fecha descarga | URL                                                        |
| ------------------------------------------------------ | ------- | -------------- | ---------------------------------------------------------- |
| 201901_Menores_1er_trimestre_2019.xlsx                 | T1 2019 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19396554153 |
| 201902_Menores_2__trimestre_2019.xlsx                  | T2 2019 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19396654144 |
| 201903_Menores_3er_trimestre_2019.xlsx                 | T3 2019 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19396754135 |
| 201904_Menores_4__trimestre_2019_open_document.ods     | T4 2019 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19396854126 |
| 202001_PUBLICACION_MENORES_PRIMER_TRIMESTRE_2020.ods   | T1 2020 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19396954117 |
| 202002_PUBLICACION_MENORES_SEGUNDO_TRIMESTRE_2020.ods  | T2 2020 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19397054108 |
| 202003_PUBLICACION_MENORES_TERCER_TRIMESTRE_2020.ods   | T3 2020 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19397154099 |
| 202004_PUBLICACION_MENORES_CUARTO_TRIMESTRE_2020.ods   | T4 2020 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19397554063 |
| 202101_PUBLICACION_MENORES_PRIMER_TRIMESTRE_2021.ods   | T1 2021 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19398054018 |
| 202102_PUBLICACION_MENORES_SEGUNDO_TRIMESTRE_2021.ods  | T2 2021 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19398154009 |
| 202103_PUBLICACION_MENORES_TERCEIRO_TRIMESTRE_2021.ods | T3 2021 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19400053838 |
| 202104_PUBLICACION_MENORES_CUARTO_TRIMESTRE_2021.ods   | T4 2021 | 20/10/2026     | https://www.coruna.gal/documentos/descarga.jsp?19399653874 |

## Extracción (`src/01_extract.py`)

El portal no usa una plantilla estable entre trimestres. Esto se detectó mirando a mano, fichero a fichero, tanto los `.xlsx` (2019) como los `.ods` (2020-2021) viendo la hoja "en crudo" antes de asumir dónde está la cabecera:

- **"Plano"**: la cabecera ocupa la fila 0 y los datos empiezan en la fila 1. Solo ocurre en **T1 2019**. No tiene columna de tipo de contrato.
- **"Con portada"**: varias filas de título y aviso legal (sobre la omisión del NIF de personas físicas), luego la fila de cabecera real (localizada buscando la celda `"Referencia"`) y una fila de subcabecera que se descarta. Es el formato de **T2, T3 y T4 2019, y de todo 2020 y 2021**.

Dentro del grupo "con portada" el número de columnas también varía de un trimestre a otro, otra vez comprobado abriendo cada fichero a mano:

| Trimestre         | Formato     | Extensión | Nº columnas | Particularidad                                                                                                       |
| ----------------- | ----------- | ---------- | ------------ | -------------------------------------------------------------------------------------------------------------------- |
| T1 2019           | Plano       | .xlsx      | 9            | Sin columna de tipo de contrato; en cambio sí trae "técnico responsable" y "duración", que no existen en el resto |
| T2 2019           | Con portada | .xlsx      | 9            | —                                                                                                                   |
| T3 2019           | Con portada | .xlsx      | 9            | —                                                                                                                   |
| **T4 2019** | Con portada | .ods       | **10** | **Única con columna NACIONALIDAD** (casi siempre vacía)                                                      |
| T1-T4 2020        | Con portada | .ods       | 9            | Columna en blanco al principio de la hoja (desplaza todo una posición)                                              |
| T1-T4 2021        | Con portada | .ods       | 8            | Sin la columna en blanco inicial de 2020                                                                             |

Como ni el número ni el orden de columnas es estable, el script **no mapea por posición sino por el texto de la cabecera** (busca la celda `"Referencia"`, `"Objeto"`, `"NIF"`, etc. y a partir de ahí decide qué columna es cada cosa). Así, la columna NACIONALIDAD de T4 2019 o la columna en blanco de 2020 simplemente no se mapean a nada y se descartan solas, sin romper el resto del esquema.

El script lee los 12 ficheros de `data/raw/`, los normaliza a un esquema común (`referencia`, `tipo_contrato`, `objeto`, `fecha_adjudicacion`, `nif`, `nombre_adjudicatario`, `importe`, `area_tramitadora` + metadatos `fila_origen`/`anio`/`trimestre`/`fichero_origen`) y guarda el resultado consolidado, sin limpiar todavía, en `data/processed/bronze_contratos_menores.csv`. Se puede volver a ejecutar sin duplicar filas: cada ejecución sobrescribe el fichero de salida.

`fila_origen` guarda el número de fila tal como se ve en la hoja de cálculo original (Excel/LibreOffice cuentan desde 1), para poder localizar a mano cualquier registro concreto si hace falta justificarlo. El script también imprime, fichero a fichero, cuántas filas de relleno descarta (ver más abajo): 208 en T3 2019 y 14.151 en T4 2019, el resto con 0 — ningún contrato se pierde, solo huecos vacíos del rango de celdas de la hoja.

Nota: el bronce no pretende ser un facsímil visual del fichero original — por ejemplo, un importe puede aparecer como `"800"` o `"800.0"` según el fichero, según cómo pandas interprete esa celda en cada motor de lectura. No se ha dedicado esfuerzo a homogeneizar eso, porque es puramente cosmético: el paso de limpieza (`02_clean.py`) convierte ambas formas al mismo número y no cambia el resultado del análisis.

## Limpieza y transformación (`src/02_clean.py`)

Lee `data/processed/bronze_contratos_menores.csv` y escribe `data/processed/contratos_menores_limpio.csv`, con los campos pedidos ya tipados: `expediente`, `fecha_adjudicacion`, `area_departamento`, `objeto`, `nif`, `empresa_adjudicataria`, `importe`, `tipo_contrato` (+ `anio`/`trimestre`). Se puede volver a ejecutar sin duplicar filas.

### 1. Cambios de tipos y formatos

- **`fecha_adjudicacion` → fecha**: casi todos los ficheros traen la fecha como `"2019-03-01 00:00:00"`, pero en **T1 y T3 de 2019** algunas filas la traen como texto `"30/01/2019"` (día/mes/año). Si se usa solo el formato estándar, 41 filas se quedaban sin fecha. El script intenta primero el formato estándar y, para lo que falla, reintenta interpretando el día primero. Queda un caso más concreto: el expediente `231/2019/290` tiene `"08/082019"` en el origen — se puede reconstruir con confianza: solo falta un carácter (la barra entre mes y año, `082019` = `08`+`2019` pegados) y solo hay una lectura razonable (`08/08/2019`), así que el script detecta ese patrón concreto y lo recupera en vez de dejarlo vacío.
- **`importe` → número**: el origen mezcla `"1234.56"` (punto decimal, sin símbolo) con formato español `"1.234,56 €"` (punto de millares, coma decimal, símbolo de euro). El script quita el símbolo `€`, y si el valor tiene coma y punto a la vez asume que el punto es de millares; si solo tiene coma, la trata como decimal. Caso puntual: el expediente `AD0/2021/130` tiene `"9.399.28 €"` (dos puntos, sin ninguna coma). La agrupación en grupos de 3 dígitos + 2 decimales finales (`9` + `.399` + `.28`) coincide exactamente con el formato español de moneda, y el único error es que el separador decimal es un punto en vez de una coma — un solo carácter mal tecleado, igual que el caso de la fecha. Además, la lectura alternativa (ignorar la puntuación y leer `939.928 €`) superaría varias veces el umbral legal de 15.000 € para servicios (ver más abajo), por lo que ni siquiera podría estar legalmente publicado como contrato menor — el contexto confirma la lectura correcta. Se reconstruye a `9399.28`. Solo queda **1 importe** que de verdad no existe en el origen (expediente `GA2/2019/49`, T4 2019): esa fila no tiene ningún valor de importe en la hoja de cálculo, no es un error de formato, y se deja vacío.
- **`tipo_contrato` → categoría unificada**: 2019-2020 usan letras (`A`, `E`, `C`, `Z`) y 2021 usa palabras (`Obras`, `Servicios`, `Suministro`/`Suministros`, `Privado`), con espacios sueltos en algunos valores (`"Servicios "`) y una categoría rara que solo aparece una vez (`"Concesión obras públicas"`). El script traduce las letras a su significado real (`A`→Obras, `E`→Servicios, `C`→Suministros, `Z`→Otros, según la propia leyenda que trae cada fichero en la subcabecera) y unifica mayúsculas/espacios para que 2019, 2020 y 2021 se puedan comparar en el mismo gráfico.
- **`empresa_adjudicataria` y `objeto` → espacios normalizados**: se encontró, al preparar el modelo de Snowflake, que **1.795 filas** de `empresa_adjudicataria` y **1.154 de `objeto`** tienen espacios dobles o un espacio suelto antes de una coma (ej. `"ANTELO LAVANDEIRA , CLAUDIO"` en vez de `"ANTELO LAVANDEIRA, CLAUDIO"`). No es un error de una fila concreta, es ruido de formato extendido por todo el dataset: antes de corregirlo, el mismo NIF `34889996P` (una sola persona con 3 contratos distintos y legítimos) aparecía con 2 variantes de nombre, y los nombres únicos de `empresa_adjudicataria` bajaban de 2.535 a 2.519 solo con normalizar esto — es decir, 16 "personas distintas" eran en realidad la misma persona partida en dos por un espacio. Se corrige con una regla general (colapsar espacios, quitar el espacio antes de coma), no con parches por fila.
  - **Segunda vuelta, encontrada después, al construir el ranking de empresas en Power BI**: la regla de arriba solo comprobaba el espacio **antes** de la coma, no si faltaba **después**. El expediente `541/2019/1868` (NIF `"*"`) tenía `"VILLAZALA ROCA,OCTAVIO"` (sin espacio tras la coma) mientras sus otros 8 contratos tenían `"VILLAZALA ROCA, OCTAVIO"` — como ese contrato está anonimizado, la clave híbrida de `dim_empresa` lo separó en una entidad aparte. Afectaba a **65 filas** en total. Se amplió la regla para también insertar el espacio que falte justo después de una coma.

### 2. Tratamiento de nulos

Se distinguen dos situaciones que **no son lo mismo**, aunque las dos parezcan "un hueco":

- **El dato no existe en el origen** → se marca como `no disponible`. Pasa con `tipo_contrato` en **todo T1 2019** (807 filas: ese trimestre no publicó esa columna), con 2 NIF realmente vacíos, y con los `expediente`/`objeto`/`area_departamento`/`empresa_adjudicataria` si llegaran vacíos (no ha pasado ningún caso real, pero queda cubierto).
- **El dato está intencionadamente anonimizado por la propia fuente** → el NIF aparece marcado con asteriscos en **1.144 filas**. El propio fichero lo explica en su nota legal: se omite el NIF de las personas físicas adjudicatarias por protección de datos. Esto **no** se convierte en `no disponible`. **Hallazgo (encontrado al construir `dim_empresa` en Snowflake, no en la limpieza inicial)**: la fuente no usa siempre el mismo marcador — la mayoría de trimestres usan `"*"` (953 filas), pero **T4 2021 usa `"*****"`** (5 asteriscos, 191 filas). Sin normalizarlo, esas 191 filas se trataban como "NIF real" en el modelado y se fundían **todas en una sola empresa falsa** bajo el nombre que saliera primero por casualidad — se corrigió tratando cualquier NIF compuesto solo de asteriscos (de cualquier longitud) como el mismo marcador `"*"`.
- El único campo numérico que falta de verdad (1 importe, expediente `GA2/2019/49`, ver punto anterior) se deja vacío (`NaN`/nulo) en vez de con el texto `no disponible`, porque mezclar texto en una columna numérica rompería los cálculos en SQL/Power BI más adelante; se documenta aquí el recuento en vez de maquillarlo en la propia columna. (La única fecha que faltaba, expediente `231/2019/290`, se recuperó — ver punto 1.)

### 3. Duplicados

**Regla 1 (duplicado exacto dentro del mismo trimestre)**: se considera duplicado si una fila es **idéntica en todas las columnas de negocio** (expediente, fecha, NIF, empresa, objeto, importe, área, tipo, año, trimestre). Con esa regla se eliminan **2 filas**:

- Expediente `631/2020/64`: repetida exactamente igual dos veces (duplicado exacto, sin más).
- Expediente `105/2020/1266` (T1 2020, filas 555 y 557 del `.ods` original): misma fecha, mismo NIF, mismo importe (5.487,56 €) y la misma factura (`"2019/25"`) citada en el objeto — solo cambiaba el nombre de la empresa en una letra (`"SERVICIO"` vs. `"SERVICIOS"` DE HOSTELERIA OLLOMOL S.L.). Revisado a mano antes de decidir: es un alta duplicada por error de tecleo en el nombre, no dos pagos distintos. Se normaliza ese nombre concreto (`NOMBRE_EMPRESA_CORRECCIONES` en el script) y la regla de "fila idéntica" hace el resto. No es una regla genérica de "nombres parecidos" — habría sido arriesgado aplicar coincidencia difusa al resto del dataset — es una corrección puntual para este caso ya verificado.

**Regla 2 (republicación entre trimestres)**: hallazgo posterior, al construir el modelo de Snowflake y comprobar duplicados en `fact_contratos` sin año/trimestre. **7 contratos de 2019** aparecen tal cual (mismo expediente, fecha, NIF, empresa, importe, objeto y área) en el fichero de un trimestre **y otra vez en el fichero del trimestre siguiente** (ej. `230/2019/224`, publicado en T2 y de nuevo en T3). No lo detectaba la regla 1 porque esa regla incluye año/trimestre a propósito — aquí es precisamente lo que hay que ignorar para verlo. Se elimina la copia más tardía y se conserva la primera publicación (ordenando por año/trimestre antes de aplicar la regla). Caso particular dentro de este grupo: el expediente `230/2019/158` se publicó en T1 2019 (sin `tipo_contrato`, como todo ese trimestre) y se repitió en T2 2019 (ya con `tipo_contrato = "Suministros"`) — por eso esta segunda regla **no** usa `tipo_contrato` como parte de la comparación, o se habría tratado como "distinto" solo por ese hueco estructural de T1 2019, no por ser un contrato diferente.

**Regla 3 (misma transacción en dos fases administrativas)**: hallazgo al revisar a mano los 304 resultados de la consulta SQL del patrón "cerca del umbral legal" (punto 4). Mismo `expediente` + `nif` + `importe` + `empresa_adjudicataria`, pero con fecha semanas o meses posterior y el objeto de la segunda fila añadiendo el prefijo `"ADO - FRA. ..."` (Autorización-Disposición-Obligación + nº de factura, terminología de contabilidad pública) — es la misma compra pasando de fase de adjudicación a fase de aprobación de factura, no un gasto nuevo. **20 filas eliminadas**, ejemplo: expediente `861/2021/199` (TRADESEGUR), 18.089,50 € adjudicado en julio de 2021 y la misma cifra exacta reaparece en octubre con `"ADO - FRA. F21E-00574"` añadido al objeto. Se conserva la fecha más temprana (la adjudicación original).

Dos casos de este grupo se dejaron **sin fusionar a propósito**, por ambigüedad real:
- `GEY/2020/54` y `GEY/2020/64`: el objeto cita dos fechas de elección **reales y distintas** ("12 de xullo" y "5 de abril") — las elecciones autonómicas gallegas de 2020 estaban convocadas para el 5 de abril y se aplazaron al 12 de julio por el COVID. Podría ser un servicio prestado de verdad en la fecha aplazada, no una duplicación administrativa, y no hay forma de comprobarlo con este dato.
- `10C/2021/8`: mismo importe y empresa, pero el objeto cita matrículas de vehículo **distintas** (`"1620 DYK"` vs `"0162 DYK"`, los mismos dígitos en otro orden) — podría ser un typo del mismo vehículo o dos compras reales para dos coches distintos al mismo precio de catálogo.

**Por qué NO se usa el expediente como clave única de duplicado**: un mismo número de expediente puede repartirse legítimamente en varias líneas distintas, y no son duplicados:

- El expediente `238/2019/118` tiene 6 líneas con el mismo expediente pero 6 empresas y conceptos distintos (alojamiento, catering, material, diseño...) — es un evento con varios proveedores bajo un mismo expediente.
- El expediente `106/2020/72` tiene **27 líneas** con el mismo importe (9.075,00 €) y el mismo objeto, pero cada una a nombre de una persona distinta — es una reparación de un edificio repercutida a cada vecino de la comunidad de propietarios, no una fila repetida 27 veces por error.

Si se hubiera usado "mismo expediente + mismo importe + mismo NIF" como regla de duplicado, este segundo caso se habría borrado por error (los 27 vecinos comparten NIF `"*"` al estar anonimizados), perdiendo información real de transparencia — **esto no es solo una advertencia teórica: pasó de verdad al escribir la regla 3**. La primera versión de esa regla usaba exactamente `expediente + nif + importe`, sin el nombre, y fusionó por error a los 27 vecinos de `106/2020/72` en una sola fila (detectado revisando el resultado antes de darlo por bueno, no automáticamente). Se corrigió añadiendo `empresa_adjudicataria` a la clave. Por la misma razón, **no se usa una comparación "difusa" de nombres de empresa** como regla general (dar por duplicado todo lo que se parezca mucho habría arriesgado falsos positivos en otras filas) — el caso `105/2020/1266` de arriba se resolvió a mano, revisando el `.ods` original, no con una heurística automática de similitud de texto.

## Carga y modelo en Snowflake (`src/03_build_gold.py` + `sql/ddl_gold.sql` + `src/04_load_snowflake.py`)

### Grano del hecho

Un expediente puede repartirse en varias líneas legítimas (`238/2019/118` tiene 6, `106/2020/72` tiene 27). **El grano declarado es una fila por línea de contrato publicada** (expediente + adjudicatario + importe) — la misma granularidad que ya tenía `contratos_menores_limpio.csv`.

### Esquema en estrella

```
                    dim_fecha
                        │
dim_tipo_contrato ──  fact_contratos  ── dim_area
                        │
                    dim_empresa
```

- **`dim_fecha`**: un día natural por fila, generada para todo 2019-01-01 a 2021-12-31 (no solo los días con contrato), con `periodo_covid` (Pre-COVID / Estado de alarma / Post-estado de alarma). `fecha_key` es una clave "inteligente" (`20200315`), calculada con la misma fórmula en el hecho y en la dimensión.
- **`dim_empresa`**: ver más abajo, es la dimensión con la decisión de diseño más importante.
- **`dim_area`**: una fila por `area_departamento` distinto (43 áreas).
- **`dim_tipo_contrato`**: una fila por categoría, con el **umbral legal sin IVA** (40.000 €/15.000 €) como atributo — así el umbral vive en el modelo, no hay que escribirlo a mano en cada consulta SQL del punto 4.
- Todas las dimensiones tienen una fila `clave = -1`, `"no disponible"` (convención Kimball): así ninguna clave foránea del hecho es nunca `NULL` — los 807 contratos de T1 2019 sin `tipo_contrato` apuntan a `tipo_contrato_key = -1`, no a un hueco.

### `dim_empresa`: por qué la clave es híbrida

El NIF `"*"` (persona física anonimizada por la propia fuente, ya unificado el marcador — ver sección de limpieza) aparece en 1.144 filas, pero **no identifica a nadie**: son 509 personas distintas compartiendo ese mismo valor. Si se usara solo el NIF como clave, esas 509 personas colapsarían en una única fila de dimensión.

Pero usar NIF+nombre tampoco vale para los NIF reales: hay **254 NIFs reales con más de un nombre distinto** en el dataset — typos (`"VILLAR ROSENDE, JSE ANTONIO"` vs `"...JOSE ANTONIO"`), nombres recortados (`"...ROSA MARIA"` vs `"...ROSA"`), problemas de codificación de tildes, e incluso un caso donde el propio NIF se coló dentro del campo nombre por error de tecleo (`"SAEZ PEREZ, RAMON 32839349H"`). Si se usara NIF+nombre siempre, esas 255 personas se partirían en varias filas de dimensión sin motivo real.

**Regla aplicada** (clave híbrida, construida en `build_dim_empresa`):
- `nif != "*"` → identidad = `nif` solo (el NIF es más fiable que el texto del nombre).
- `nif == "*"` → identidad = `nif + nombre` (el NIF no distingue a nadie; el nombre, ya normalizado en la limpieza, es la única información que sí lo hace).


`dim_empresa` también guarda `tipo_persona` (Persona jurídica / Persona física identificada / Persona física anonimizada) y `forma_juridica` (deducida de la primera letra del NIF — A=Sociedad Anónima, B=Sociedad Limitada, G=Asociación, H=Comunidad de Propietarios...). Se descubrió, de paso, que el Ayuntamiento fue anonimizando cada vez más estrictamente a las personas físicas con el tiempo: en 2019 el 70% de las personas físicas llevaba su DNI visible y el 30% ya anonimizado; en 2021 esa proporción es casi del 100% anonimizado.

### Hechos (medidas en `fact_contratos`)

- `importe_con_iva`: el dato publicado tal cual.
- `importe_sin_iva_estimado` = `importe_con_iva / 1.21`: **supuesto documentado**.
- `supera_umbral` / `cerca_umbral` (≥90% del umbral sin superarlo, mutuamente excluyentes)
- Degeneradas (trazabilidad): `expediente`, `objeto`, `anio_publicacion`, `trimestre_publicacion`, `fila_origen`, `fichero_origen`. Se usa `anio_publicacion`/`trimestre_publicacion` (del fichero) y no el año/trimestre de `fecha_adjudicacion` para estos dos campos, a propósito: hay **15 filas** donde la fecha de adjudicación cae en un trimestre distinto al de publicación (ej. expediente `GEY/2019/18`, fecha `2018-01-15`, publicado en el fichero de T1 2019) — para la evolución temporal se usa la fecha real; para la trazabilidad, el trimestre en el que se publicó.

### Hallazgo de duplicados al construir el modelo (ver también la sección de limpieza, regla 2)

Al comprobar duplicados en `fact_contratos` sin año/trimestre, aparecieron **7 contratos de 2019 republicados tal cual en el trimestre siguiente** (mismo expediente, fecha, NIF, importe, objeto y área).

### Hallazgo al cargar en Snowflake: fecha fuera del periodo declarado

El control de integridad referencial (`fecha_key` de `fact_contratos` sin fila en `dim_fecha`) detectó un caso: el expediente `GEY/2019/18` tiene `fecha_adjudicacion = 2018-01-15`, **un año antes** de que empiece nuestro periodo (2019-2021), aunque se publicó igualmente en el fichero de T1 2019. No se amplió `dim_fecha` a 2018 por un único caso: se trata como `fecha_key = -1` ("no disponible"), igual que una fecha ausente. El `anio_publicacion`/`trimestre_publicacion` (2019/T1) se conservan correctos para trazabilidad; solo se pierde la fecha exacta para el eje temporal de Power BI, que de todas formas quedaría fuera de nuestro periodo de análisis.

### Controles ejecutados

`src/03_build_gold.py` imprime, cada vez que se ejecuta: la justificación numérica de la clave híbrida, conteo de filas por tabla, nulos en las 4 claves foráneas (deben ser 0), duplicados exactos en el hecho (deben ser 0) y **integridad referencial** (filas de `fact_contratos` sin fila correspondiente en cada dimensión — deben ser 0; así se detectó el caso de arriba). `src/04_load_snowflake.py` repite los cuatro controles **ya en Snowflake** (vía SQL), para comprobar que la carga real coincide con lo calculado en local.

### Credenciales

`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA` se leen de `.env` (plantilla en `.env.example`, nunca versionado — ver `.gitignore`). El script falla con un mensaje claro si falta alguna.

## SQL y análisis (`sql/analisis.sql`)

6 consultas + 1 de control de calidad. Para "por año"/"por mes" se usa siempre la **fecha de adjudicación real** (`dim_fecha`), no el trimestre de publicación del fichero — ya vimos que no siempre coinciden.

Ver explicación detallada de cada consulta en el propio archivo

## Power BI

### Hallazgo: un contrato publicado con importe 0 € — y un matiz técnico de DAX

Al construir la medida `Nº Contratos Exactos al Umbral` (punto de investigación del fraccionamiento), el resultado daba **33** en vez de los **32** ya verificados por SQL. La fila de más era el expediente `541/2019/536` (`SERYE INGENIEROS SL`, "realización de pruebas con un vehículo para transporte de personas con movilidad reducida", T1 2019) — un contrato publicado con **importe literal de 0 €**, no un hueco de dato.

Como además es de T1 2019, su `tipo_contrato` es `"no disponible"` y por tanto no tiene umbral legal definido (`UMBRAL_SIN_IVA` en blanco para esa categoría). En DAX, al restar, un valor en blanco se trata como `0` — así que `ABS(0 - BLANK())` da `0`, por debajo del margen de tolerancia, y la medida lo contaba como "exacto al umbral" aunque esa categoría no tenga ningún umbral con el que comparar. Se corrigió añadiendo `NOT ISBLANK(RELATED(DIM_TIPO_CONTRATO[UMBRAL_SIN_IVA]))` al filtro, para excluir explícitamente las filas sin umbral aplicable, no solo las filas sin importe.

### Hallazgo: un mismo proveedor repitiendo el importe exacto al umbral legal

Con la medida ya corregida (32 contratos "exactos al umbral", 3 "por encima"), se construyeron dos tablas de detalle en la página de Investigación para revisar los 35 casos uno a uno, buscando patrones de posible fraccionamiento.

De los 32 contratos con el importe exacto al umbral legal (15.000,00 € en Servicios/Suministros, 40.000,00 € en Obras), **`VILLAZALA ROCA, OCTAVIO` aparece 5 veces** — el proveedor más repetido con diferencia. Las 5 filas son siempre por el mismo objeto ("residencia/gastos de perros y gatos incautados"), en expedientes distintos, repartidos entre enero de 2020 y febrero de 2021 (`541/2020/161`, `541/2020/1730`, `541/2020/2113`, `541/2020/2168`, `541/2021/241`), cada uno facturado exactamente a 15.000,00 € sin IVA, ni un céntimo más ni menos.

Otros proveedores aparecen 2 veces cada uno en la misma tabla (`VAZQUEZ CALATAYUD ARQUITECTOS S.L.`, `CARPINTERIA METALICA DACRI SL`, `LAIROSIDE S L`, `CONSTRUCCIONES LOPEZ CAO S.L.` en Obras a 40.000 €), pero ninguno con la frecuencia ni la coincidencia de objeto de `VILLAZALA ROCA, OCTAVIO`.

**`LAIROSIDE S L` es también una clínica veterinaria** (aparece en el directorio de empresas de "Actividades Veterinarias" de A Coruña, vinculada al [Hospital Veterinario Abeiro](https://www.informa.es/directorio-empresas/750_ACTIVIDADES-VETERINARIAS/Provincia_CORUNA.html), en Oleiros), y sus 2 contratos exactos al umbral son por "ESTERILIZACIONES DE ANIMALES" (`541/2020/315`) y "ESTERILIZACIONES ANIMAIS 2021" (`541/2021/212`) — es decir, no es solo `VILLAZALA ROCA, OCTAVIO` el que se repite: **el bloque entero de gestión/bienestar animal del Ayuntamiento** (perrera municipal + esterilizaciones) aparece una y otra vez justo al límite legal, con dos proveedores distintos para dos servicios distintos. Revisando el `area_departamento` de estos 7 expedientes, además, no es siempre la misma área: `GESTION ADMINISTRATIVA MEDIO AMBIENTE MA1000` concentra los de 2020, pero los de 2021 aparecen repartidos en `INTERIOR IT2700` y `SERVICIOS GENERALES DE SEGURIDAD CIUDADANA SA0000` — el servicio de control animal parece haberse reorganizado administrativamente entre áreas sin dejar de trocearse en contratos de 15.000 €. El importe con IVA de los 3 contratos de `VILLAZALA ROCA, OCTAVIO` revisados es, además, **18.150,00 € exactos** (15.000 × 1,21, sin resto), confirmando que el cálculo está hecho justo para quedar en el límite.

Por fecha, los 32 casos se concentran en 2020-2021 (4 de 2019, 15 de 2020, 13 de 2021), coherente con el hallazgo ya documentado de que el importe medio por contrato sube durante el COVID (consulta 5 de `analisis.sql`).

**Lectura, sin poder confirmarlo con certeza**: un mismo servicio recurrente (gestión de animales incautados) facturado repetidamente justo al límite legal, por el mismo adjudicatario, es exactamente el patrón que la normativa de contratación pública busca evitar con el umbral de los 15.000 € (fraccionamiento del objeto del contrato para eludir un procedimiento de licitación mayor). No es una prueba — podría ser también que el servicio real cueste, mes a mes, casi justo eso — pero es el caso más claro que aparece en los datos para investigar con más detalle fuera de este proyecto.

### Hallazgo: cómo es posible que haya 3 contratos "menores" por encima del umbral legal

*(consulta 8 de `sql/analisis.sql`)*

Por definición, un contrato menor que supera el umbral (15.000 €/40.000 € sin IVA) no debería poder tramitarse como tal — es justo el límite que obliga a un procedimiento de licitación mayor. Revisando los 3 casos uno a uno:

| Expediente | Fecha | Empresa | Importe sin IVA | Umbral | % sobre el umbral | Objeto |
|---|---|---|---|---|---|---|
| `851/2019/75` | 2019-06-12 | CABLES Y ESLINGAS S.L.U. | 18.822,59 € | 15.000 € | 125,5% | Suministro e instalación de sistemas de protección y acceso, estación de autobuses |
| `211/2021/735` | 2021-10-13 | ANGEL ROADE S.L. | 15.949,10 € | 15.000 € | 106,3% | Instalación caldera mural piscina de Riazor |
| `831/2019/112` | 2019-12-13 | NOYA VAZQUEZ, JORGE JUAN | 28.921,45 € | 15.000 € | 192,8% | Adecuación de instalaciones anteriormente usadas por Empleo para nuevos usos del SEIS |

Ninguno de los 3 tiene en el `objeto` una palabra clave que lo explique directamente (a diferencia, por ejemplo, de otro contrato de `MONTAJES ELECTRICOS VIZCAINO S.L.` que sí aparece en el dataset con el objeto empezando por "**Recoñecemento extraxudicial factura**...", expediente `211/2019/732` — un mecanismo legal distinto al contrato menor: regulariza contablemente un gasto ya ejecutado, en vez de adjudicar un contrato nuevo, y por eso puede no ajustarse al umbral de adjudicación).

**Explicación más probable, sin poder confirmarla con los datos disponibles**: lo habitual en este tipo de desviación es que el contrato se adjudicara inicialmente por debajo del umbral y después se **modificara o ampliara** durante la ejecución (trabajo adicional imprevisto, típico en obras/instalaciones), de forma que el importe final publicado ya no coincide con el importe de adjudicación original — la LCSP permite modificaciones contractuales dentro de ciertos límites (art. 205-207) sin que eso implique una irregularidad. También es compatible con un simple error de clasificación del `tipo_contrato` en el dato de origen (p. ej. si debería haberse marcado como "no disponible"/otro tipo en vez de Servicios/Suministros). Con solo 3 casos sobre 8.421 filas (0,04%), y sin acceso al expediente administrativo real, no se puede ir más allá de señalar el hecho y las hipótesis más plausibles.

### Hallazgo: un patrón sistemático de "quedarse justo por debajo del umbral" en dos grandes contratistas de obra civil

*(consulta 9 de `sql/analisis.sql`)*

Revisando no solo los importes exactos sino el **porcentaje sobre el umbral** de cada contrato (columna `pct_del_umbral` de la consulta 4 de `analisis.sql`) para los 2 principales contratistas de obra civil del ranking (`CONSTRUCCIONES LOPEZ CAO S.L.` y `ARIAS INFRAESTRUCTURAS S.A.`, ambas presentes en el top 15 en varios periodos), aparece un patrón mucho más fuerte que el de un solo contrato aislado:

- **`CONSTRUCCIONES LOPEZ CAO S.L.`**: de sus 19 contratos de Obras/Servicios/Suministros, **10 están entre el 96,7% y el 100,0% del umbral legal** correspondiente (dos de ellos exactos al 100%, ya documentados arriba). Hasta inicios de 2020 sus contratos tenían importes dispersos (32%, 9%, 0,2% del umbral) — a partir de marzo de 2020 (coincidiendo con el inicio del estado de alarma), prácticamente todos sus contratos de Obras pasan a concentrarse justo por debajo del límite de 40.000 €.
- **`ARIAS INFRAESTRUCTURAS S.A.`**: de sus 11 contratos, **5 están entre el 95,7% y el 100,0% del umbral**, con la misma concentración a partir de la segunda mitad de 2020.

Las dos empresas, además, son las dos con el movimiento de ranking más llamativo entre periodos COVID (ver hallazgo siguiente). No se puede confirmar fraccionamiento intencionado solo con estos datos — pero el patrón (varios contratos del mismo adjudicatario, del mismo tipo, concentrados justo bajo el límite, intensificándose desde el inicio del COVID) es consistente en ambas empresas a la vez, lo que lo hace más llamativo que un caso aislado.

### Hallazgo: un caso concreto que encaja con fraccionamiento real

*(consulta 11 de `sql/analisis.sql`)*

Para ir más allá de "importes cerca del umbral" y buscar fraccionamiento en sentido estricto (un mismo trabajo troceado en varios contratos para evitar la licitación mayor), se cruzaron pares de contratos del mismo `area_departamento` y `tipo_contrato`, publicados con pocos días de diferencia, cada uno por debajo del umbral individualmente pero que **sumados lo superarían**, ordenados por similitud de texto del `objeto` (`EDITDISTANCE` en Snowflake).

El candidato más llamativo: **`ARIAS INFRAESTRUCTURAS S.A.` firmó el mismo día (13 de octubre de 2020) dos contratos de "mejora de pavimento de calzada"** — uno en la Avenida de Glasgow (39.797,00 €) y otro en la Rúa Sinfónica de Galicia (39.793,23 €) — cada uno calculado justo por debajo de los 40.000 €, pero sumados, **79.590,23 €**, muy por encima del umbral de Obras. Mismo adjudicatario, mismo día, mismo tipo de trabajo, cada importe individual a pocos cientos de euros del límite: es el patrón que más encaja de todo el dataset con un fraccionamiento deliberado del objeto del contrato.

**Importante matizar el resto de resultados de la misma consulta**: la mayoría de pares con texto muy parecido (ej. "Dirección de obra" + "Dirección de ejecución de obra" + "Coordinación de seguridad y salud" + "Control arqueológico" de un mismo proyecto, en `111/2021/130`, `131`, `132`, `133`, por ejemplo) **no son fraccionamiento** — son roles profesionales distintos de un mismo proyecto de obra que la normativa de edificación española (LOE) exige adjudicar por separado (el director de obra, el director de ejecución y el coordinador de seguridad y salud no pueden ser, legalmente, el mismo contrato). Hay que leer esta consulta caso a caso, no asumir que toda coincidencia es sospechosa.

Aparte, se encontró una peculiaridad de dato: el expediente `211/2020/389` (`FEDERACION GALLEGA DE ATLETISMO DE LA CORUÑA`) aparece dos veces con el mismo objeto pero importes distintos (14.996,35 € en T3 2020 y 13.996,04 € en T4 2020) — no lo capturan las reglas de deduplicación porque el importe difiere entre ambas filas. Es casi con toda seguridad el mismo contrato facturado en dos fases, no dos expedientes distintos, así que no es fraccionamiento — pero queda anotado por si se revisa el dato de origen más adelante.

### Hallazgo: el pico de noviembre de 2020 y la caída de enero de 2021

Al construir el gráfico de evolución mensual (`DIM_FECHA[FECHA]` expandida a nivel año+mes) apareció un pico muy marcado en **noviembre de 2020** (476 contratos, 2.215.749,70 €, el mes de mayor gasto de toda la serie), seguido de una caída muy brusca en **enero de 2021** (125 contratos, 264.063,83 €, el mes con menos contratos de los 3 años — aunque el mes con menos importe total de todos es agosto de 2019, 224.780,68 €, el parón veraniego habitual).

Se investigó el pico de noviembre de 2020 para descartar que fuera un error de dato (un contrato gigante aislado, un duplicado no detectado...). No lo es: son **476 contratos repartidos**, y los de mayor importe son **todos de tipo "Obras"** (entre 22.000 € y 48.400 €, en áreas muy distintas: Bomberos, Deportes, Infraestructuras, Vivienda, Educación). Encaja con dos hallazgos anteriores:

- El pico de **cierre de ejercicio presupuestario** en octubre-noviembre, visible los 3 años (consulta 6 de `analisis.sql`).
- El **cambio de mezcla hacia más contratos de Obras** durante el estado de alarma (consulta 5) — noviembre de 2020 parece ser el mes donde ese cambio se concentró con más fuerza, y como Obras tiene contratos de mayor importe individual (umbral legal 40.000 € frente a 15.000 € del resto), agrupar muchos en un mismo mes dispara el total de golpe.

**Hipótesis razonable, no confirmada del todo**: el Ayuntamiento pudo concentrar buena parte de la ejecución de obra pública del año COVID en el cierre de 2020, posiblemente aprovechando el menor uso de espacios públicos durante las restricciones — para confirmarlo con certeza haría falta el calendario de obras real del Ayuntamiento, que no forma parte de estos datos.

### Hallazgo: el ranking de empresas tiene un núcleo estable + movimientos puntuales fuertes

Comparando el top 15 de empresas por gasto (`Importe Total` por `DIM_EMPRESA[NOMBRE_NORMALIZADO]`) filtrando por cada uno de los 3 `periodo_covid` por separado, aparecen **4 empresas presentes en los 3 periodos** (cambiando de posición, pero sin desaparecer nunca del top 15):

- `CONSTRUCCIONES LOPEZ CAO S.L.` — #4 Pre-COVID → **#1** Estado de alarma → #2 Post-alarma
- `JARDINERIA ARCE S.L.` — #2 Pre-COVID → #8 Estado de alarma → #3 Post-alarma
- `OBRAS RAMON COTELO, S.L.` — #8 Pre-COVID → #5 Estado de alarma → #12 Post-alarma
- `INSTALACIONES DEPORTIVAS GALLEGAS S L` — #15 Pre-COVID → #6 Estado de alarma → #9 Post-alarma

Y dos movimientos destacados en sentido contrario:
- `MONTAJES ELECTRICOS VIZCAINO S.L.` era el **#1 destacado** Pre-COVID (muy por delante del resto) y **sale del top 15** en Estado de alarma y Post-alarma.
- `ARIAS INFRAESTRUCTURAS S.A.` no aparecía en el top 15 Pre-COVID, y pasa a ser el **#1** en Post-estado de alarma.

**Lectura**: no es ni "todo cambió" ni "nada cambió" con el COVID — hay un grupo reducido de proveedores habituales de obra pública con presencia continuada (probablemente relación contractual o de confianza ya establecida con el Ayuntamiento antes de la pandemia), y a la vez movimientos individuales fuertes de empresas concretas que entran o salen del radar de un periodo a otro.

*(consulta 10 de `sql/analisis.sql`)*

**`MONTAJES ELECTRICOS VIZCAINO S.L.` no desaparece de los datos, solo factura mucho menos**: revisando sus 14 contratos completos (más 2 a través de una UTE con FOROVE, S.L.), la empresa sigue contratando con el Ayuntamiento en los 3 periodos (7 contratos Pre-COVID, 6 en Estado de alarma, 2 Post-alarma — su último contrato en el dataset es de octubre de 2021) — lo que cae de forma muy brusca es el **importe**, no la actividad: 126.587,07 € Pre-COVID → 22.263,23 € en Estado de alarma (−82%) → 50.960,08 € Post-alarma (todavía muy por debajo del nivel Pre-COVID). Una búsqueda pública no encontró ningún aviso de disolución, cierre o concurso de acreedores para la empresa — sigue registrada en el Registro Mercantil de A Coruña (administrador único Carlos Cayetano Vizcaino Martínez, socio único Electricidad Creuceiro SL) — así que la salida del top 15 parece deberse a que dejó de ganar los contratos grandes de obra/instalación eléctrica que tenía antes del COVID (quedándole solo reparaciones puntuales de bombas y mantenimiento, de importe mucho menor), no a un cierre de la empresa.

**`ARIAS INFRAESTRUCTURAS S.A.` creció en volumen y en frecuencia**: 1 contrato Pre-COVID (29.262,10 €) → 4 en Estado de alarma (128.383,60 €) → 6 Post-alarma (205.478,01 €) — más del triple de contratos y más de 7 veces el importe entre el primer y el último periodo. Sus contratos son sobre todo de "Obras" (mejora de pavimento de calzada en varias calles, demolición de pasarela, reparación de bajantes del estadio de Riazor) y, igual que `CONSTRUCCIONES LOPEZ CAO S.L.`, varios de ellos (5 de 11) están entre el 95,7% y el 100% del umbral legal — ver el hallazgo de "quedarse justo por debajo del umbral" más arriba.

**El mismo patrón se repite, más atenuado, entre personas físicas anonimizadas**: repitiendo el ejercicio filtrando solo por `tipo_persona = "Persona física anonimizada"`, **7 personas** aparecen en el top 15 de **2 de los 3 periodos** (ninguna en los 3, a diferencia de las empresas): `ABELENDA HERMIDA, ANA ISABEL`, `PRIETO BLANCO, JESUS MIGUEL`, `FERNANDEZ LISTE, SALOME` y `VILLAZALA ROCA, OCTAVIO` (Pre-COVID + Estado de alarma); `PENA VILLAR, MANUEL`, `RODRIGUEZ ALVAREZ, DAVID` y `RODRIGUEZ CASTRO, ANGEL MARCELO` (Estado de alarma + Post-alarma). No es solo un fenómeno de empresas constructoras — también hay profesionales individuales con relación recurrente con el Ayuntamiento, probablemente técnicos especializados (de `RODRIGUEZ ALVAREZ, DAVID` ya sabemos, por su `objeto`, que es quien restaura el reloj monumental de María Pita — un trabajo muy específico que explica por qué se repite).

### Hallazgo: dos formas distintas de llegar al top 15 — pocos contratos grandes vs. muchos pequeños

Añadiendo `Nº Contratos` e `Importe Medio` a la tabla del top 15 (no solo `Importe Total`), aparecen dos estrategias claramente distintas entre las empresas que llegan al mismo puesto:

- **Pocos contratos, de importe alto**: `CANARGA S.L.` (5 contratos, 42.790,82 € de media), `CONTORNA TÉCNICAS CONSTRUCTIVAS, SL` (5 contratos, 29.228,35 € de media).
- **Muchos contratos, de importe bajo**: `OBRAS RAMON COTELO, S.L.` (52 contratos, solo 4.501,12 € de media), `COMARO NOVE, S.L.U` (35 contratos, 4.792,03 € de media).

El importe total por sí solo (el único dato que muestra el gráfico de barras del ranking) esconde esta diferencia — dos empresas pueden estar en una posición parecida del ranking por motivos opuestos: una gana pocos contratos grandes, puntuales; la otra mantiene una relación continuada con muchos encargos pequeños.

### Hallazgo: la anonimización de personas físicas se completa en el Post-estado de alarma

Ya sabíamos (sección de limpieza, punto 2) que el Ayuntamiento fue anonimizando cada vez más estrictamente a las personas físicas adjudicatarias a lo largo del tiempo. Desglosando por `periodo_covid` (en vez de por año) se ve el momento exacto en que ese cambio se completa:

| Periodo | Persona jurídica | Persona física identificada | Persona física anonimizada |
|---|---|---|---|
| Pre-COVID | 2.810 (79,72%) | 422 (11,97%) | 293 (8,31%) |
| Estado de alarma | 2.290 (77,26%) | 235 (7,93%) | 437 (14,74%) |
| Post-estado de alarma | 1.518 (78,61%) | **0 (0%)** | 413 (21,39%) |

En el **Post-estado de alarma, ninguna persona física aparece ya con su DNI visible** — el 100% de los particulares adjudicatarios de ese periodo están anonimizados. El peso de las personas jurídicas (empresas) se mantiene estable alrededor del 78-80% en los 3 periodos; lo que cambia es solo cómo se trata a las personas físicas, no cuánto gasto reciben en conjunto.

## Agente de preguntas en lenguaje natural (`src/05_agent.py`, extra)

Script que traduce una pregunta en español a una consulta SQL sobre el modelo en estrella de Snowflake, la ejecuta y responde en lenguaje natural con el resultado real — para poder "preguntarle a los datos" sin escribir SQL a mano.

**Se probó primero con Snowflake Cortex/AI SQL** (`SNOWFLAKE.CORTEX.COMPLETE` y su sucesora `AI_COMPLETE`), pero ambas funciones están **bloqueadas en cuentas trial** de Snowflake (`"not available for trial accounts"`). Para no depender de una API de pago, el LLM corre en local con **[Ollama](https://ollama.com)** (modelo `llama3.1:8b`, gratis, sin API key, sin tarjeta de crédito, sin salir del equipo) — Snowflake se sigue usando solo para ejecutar la SQL generada y leer los datos reales.

**Es un agente, no una sola llamada ciega**: si la SQL generada falla al ejecutarse en Snowflake (sintaxis, columna inexistente...), el script le devuelve el mensaje de error real al modelo y le pide que la corrija, hasta 3 veces, antes de rendirse. Ejemplo real encontrado al probarlo: el modelo generó `IF(...)` (sintaxis MySQL) en vez de `IFF(...)` (Snowflake) — el primer intento falló con `Unknown functions IF`, y el reintento con el error adjunto lo corrigió solo.

**Medidas de seguridad**: la SQL generada se valida antes de ejecutarse — debe empezar por `SELECT`/`WITH`, no puede contener palabras de escritura (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`...), y se le añade un `LIMIT` si no lo trae. El agente solo puede leer, nunca modificar el modelo.

**Limitación realista, esperable en un modelo local pequeño y gratuito**: probado con ~20 preguntas variadas durante el desarrollo, corrigiendo el prompt cada vez que fallaba (reglas sobre `COUNT(*)` vs `COUNT(DISTINCT...)`, `ILIKE` para nombres de empresa/área en vez de `=` exacto, usar `SUPERA_UMBRAL`/`CERCA_UMBRAL` en vez de recalcular el umbral a mano, `SUM()` dentro del `GROUP BY` en vez de la columna suelta, `NULLS LAST` en `ORDER BY DESC`...). Con eso, acierta de forma fiable en preguntas de una sola dimensión (año, área, empresa, umbral) incluso con JOIN. Sigue fallando con preguntas que combinan **varias agregaciones anidadas a la vez** (ej. "¿cuál fue el mes con más gasto?", que necesita `SUM` + `GROUP BY` por mes-año + desambiguar "mes concreto" vs "mes del calendario") — se probó ampliar la ventana de contexto de Ollama (el esquema+reglas ya ocupan ~2.400 tokens de los 4.096 por defecto) pero en este equipo, sin GPU, eso lo hizo bastante más lento sin garantizar el acierto, así que se dejó el valor por defecto. En estos casos la SQL generada se sigue imprimiendo siempre en pantalla, así que cualquier respuesta se puede auditar contra la consulta real antes de darla por buena, en vez de confiar a ciegas en el texto final — ese es el diseño que hace al agente fiable de usar, no la perfección del modelo.

Uso:
```bash
# requiere Ollama instalado y corriendo, con el modelo descargado:
#   ollama pull llama3.1:8b
python src/05_agent.py "¿Cuántos contratos hubo en 2020?"
python src/05_agent.py            # modo interactivo
```
### Ejemplos

- `¿Cuántos contratos hubo en 2019?` → 2.974 (agregación simple)
- `¿Cuánto gastó el área de Gestión de Deportes en 2020?` → 981.640,61 € (filtro cruzado área + año, resuelve "área" por `ILIKE` contra `DIM_AREA`, no por el nombre de empresa)
- `¿Cuántos contratos superan el umbral legal?` → 3 (usa la columna `SUPERA_UMBRAL` ya calculada en el modelo, en vez de recalcular el umbral a mano)

## Una limitación de los datos y cómo afecta a las conclusiones

El dataset solo contiene lo que el Ayuntamiento decide publicar en el portal de transparencia — un resumen por línea de contrato (expediente, importe, fecha, adjudicatario, objeto breve) — **no el expediente administrativo completo** (pliego de condiciones, memoria justificativa, posibles modificados o ampliaciones de contrato). Esto afecta directamente a la conclusión más delicada del proyecto: los hallazgos sobre contratos cerca del umbral legal o posible fraccionamiento (`CONSTRUCCIONES LOPEZ CAO S.L.`, `ARIAS INFRAESTRUCTURAS S.A.`, el caso de `VILLAZALA ROCA, OCTAVIO`) son **patrones estadísticos a investigar, no pruebas** — sin el expediente real no se puede confirmar si un importe justo bajo el umbral responde a una intención de evitar la licitación mayor, a una estimación de coste honesta, o a una modificación legítima del contrato durante su ejecución. Cada hallazgo de este tipo se documenta explícitamente con esa reserva.

## Una mejora que haría con más tiempo

Contrastar los casos marcados como "patrón a investigar" (cerca del umbral, posible fraccionamiento) con una fuente externa que sí recoja el expediente administrativo completo — por ejemplo la Plataforma de Contratación del Sector Público o el Registro de Contratos municipal — para poder pasar de "señal estadística" a "confirmado/descartado" en cada caso, en vez de dejarlo como hipótesis razonada. En segundo lugar, automatizaría la descarga trimestral del portal de transparencia (ahora mismo es manual, fichero a fichero) para que el pipeline se pudiera reejecutar y mantener actualizado sin intervención cada vez que el Ayuntamiento publique un trimestre nuevo.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python src/01_extract.py
python src/02_clean.py
python src/03_build_gold.py
# rellenar .env con las credenciales de Snowflake antes de este paso
python src/04_load_snowflake.py
# las consultas de sql/analisis.sql se ejecutan directamente en un
# Worksheet de Snowsight, o con cualquier cliente conectado a la BD/esquema
# del .env

# Opcional: agente de preguntas en lenguaje natural (necesita Ollama)
ollama pull llama3.1:8b
python src/05_agent.py "¿Cuántos contratos hubo en 2020?"
```
