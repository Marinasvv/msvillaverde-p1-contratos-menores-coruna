-- Paso 4 - SQL y analisis.
--
-- Consultas sobre el modelo en estrella cargado en Snowflake
-- (fact_contratos + dim_fecha/dim_empresa/dim_area/dim_tipo_contrato).
--
-- Para "por año"/"por mes" se usa siempre la FECHA DE ADJUDICACION real
-- (dim_fecha), no el trimestre de publicacion del fichero (anio_publicacion/
-- trimestre_publicacion en fact_contratos): refleja cuando se gasto de
-- verdad, no cuando salio el PDF trimestral.
--


-- =====================================================================
-- 1. Contratos e importe total por año (pregunta 1 del objetivo)
-- Agregacion simple. El expediente con fecha fuera del periodo 2019-2021
-- (GEY/2019/18, fecha_key = -1) sale en su propio grupo "no disponible" en
-- vez de desaparecer sin mas.
-- =====================================================================
SELECT
    COALESCE(df.anio::VARCHAR, 'no disponible') AS anio,
    COUNT(*)                                     AS num_contratos,
    SUM(fc.importe_con_iva)                      AS importe_total_con_iva,
    ROUND(AVG(fc.importe_con_iva), 2)            AS importe_medio_con_iva
FROM fact_contratos fc
JOIN dim_fecha df ON fc.fecha_key = df.fecha_key
GROUP BY df.anio
ORDER BY df.anio;

-- Conclusión: el número de contratos se mantiene bastante estable entre los
-- 3 años (2.974 / 2.724 / 2.722), pero el importe total y el importe medio
-- dan un salto claro en 2020 (10,41 M€ / 3.824,72 € de media) frente a 2019
-- (6,09 M€ / 2.051,50 € de media) y se mantienen altos en 2021 (9,21 M€ /
-- 3.386,58 € de media, casi 2.000 € mas que en 2019). Es decir: no se
-- contrataron muchos más contratos durante el COVID, pero cada contrato
-- individual fue, de media, bastante más caro.

-- =====================================================================
-- 2. Ranking de empresas/adjudicatarios por gasto total (pregunta 2)
-- Agregacion + ordenacion (ranking). Incluye tanto personas juridicas como
-- fisicas (identificadas o anonimizadas): la pregunta es "quien concentra
-- mas gasto", no solo "que empresas".
-- Se puede filtrar por tipo_persona si se quiere ver solo empresas.
-- =====================================================================
SELECT
    de.nombre_normalizado,
    de.tipo_persona,
    de.forma_juridica,
    COUNT(*)                     AS num_contratos,
    SUM(fc.importe_con_iva)      AS importe_total_con_iva
FROM fact_contratos fc
JOIN dim_empresa de ON fc.empresa_key = de.empresa_key
WHERE de.empresa_key != -1
GROUP BY de.empresa_key, de.nombre_normalizado, de.tipo_persona, de.forma_juridica
ORDER BY importe_total_con_iva DESC NULLS LAST
LIMIT 20;

-- Conclusión: el top 20 de adjudicatarios por gasto está dominado por
-- Sociedades Limitadas (90%) frente a Sociedades Anónimas (10%), y casi
-- todas pertenecen al sector de obras/infraestructuras/construccion
-- (CONSTRUCCIONES LOPEZ CAO, JARDINERIA ARCE, ARIAS INFRAESTRUCTURAS,
-- INSTALACIONES DEPORTIVAS GALLEGAS, OBRAS RAMON COTELO, CIMBRA
-- CONTRACTS...). El gasto en contratos menores no está repartido de forma
-- uniforme entre sectores: se concentra claramente en empresas de obra
-- civil y mantenimiento de infraestructura municipal.

-- =====================================================================
-- 3. Desglose de gasto por area y por tipo de contrato (pregunta 3)
-- Dos agregaciones distintas unidas en un solo resultado (columna
-- "dimension" indica cual de las dos es cada fila), ordenadas por gasto
-- dentro de cada una.
-- =====================================================================

SELECT 'area' AS dimension, da.area_departamento AS valor,
       COUNT(*) AS num_contratos, SUM(fc.importe_con_iva) AS importe_total_con_iva
FROM fact_contratos fc
JOIN dim_area da ON fc.area_key = da.area_key
GROUP BY da.area_departamento

UNION ALL

SELECT 'tipo_contrato' AS dimension, tc.tipo_contrato AS valor,
       COUNT(*) AS num_contratos, SUM(fc.importe_con_iva) AS importe_total_con_iva
FROM fact_contratos fc
JOIN dim_tipo_contrato tc ON fc.tipo_contrato_key = tc.tipo_contrato_key
GROUP BY tc.tipo_contrato

ORDER BY dimension, importe_total_con_iva DESC;

-- Conclusión: el área que más gasto concentra es "SERVICIOS GENERALES DE
-- INFRAESTRUCTURAS" (3.591.764,47 € en 207 contratos), seguida de
-- "SERVICIOS GENERALES DE CI" (2.589.078,59 €, pero con 1.002 contratos:
-- mucho más volumen, importe medio más bajo) y "GESTION DE DEPORTES"
-- (2.488.288,89 €). Por tipo de contrato, "Servicios" domina claramente
-- (11.812.976,44 €), casi el doble que "Obras" (6.626.798,48 €) pese a que
-- Obras tiene umbrales legales más altos (40.000 € vs 15.000 €) - hay mucho
-- más VOLUMEN de contratos de servicios, no necesariamente contratos
-- individuales más caros.
--

-- =====================================================================
-- 4. Patrón elegido para investigar: contratos cerca del umbral legal
-- (posible fraccionamiento). Usa los indicadores ya calculados en el
-- modelo (cerca_umbral, >=90% del umbral sin superarlo).
-- =====================================================================
SELECT
    fc.expediente,
    de.nombre_normalizado,
    tc.tipo_contrato,
    fc.importe_sin_iva_estimado,
    tc.umbral_sin_iva,
    ROUND(100.0 * fc.importe_sin_iva_estimado / tc.umbral_sin_iva, 1) AS pct_del_umbral,
    da.area_departamento,
    fc.objeto
FROM fact_contratos fc
JOIN dim_empresa de ON fc.empresa_key = de.empresa_key
JOIN dim_tipo_contrato tc ON fc.tipo_contrato_key = tc.tipo_contrato_key
JOIN dim_area da ON fc.area_key = da.area_key
WHERE fc.cerca_umbral = TRUE
ORDER BY pct_del_umbral DESC;

-- Conclusión: el resultado (301 filas) muestra contratos individuales con
-- su porcentaje exacto respecto al umbral legal de su tipo, muchos de
-- ellos en el 100,0% (importe exacto al límite, ni un céntimo de más,
-- ej. 15.000,00 € o 40.000,00 € justos).

-- =====================================================================
-- 5. Comparativa Pre-COVID / Estado de alarma / Post-estado de alarma
-- Responde a la hipotesis central del proyecto (por que se eligio
-- 2019-2021). Un solo filtro (periodo_covid, ya calculado en dim_fecha)
-- en vez de acotar fechas a mano en cada consulta.
--
-- Los 3 periodos no duran lo mismo (Pre-COVID ~14 meses, Estado de
-- alarma ~13 meses, Post-estado de alarma solo ~7 meses, porque
-- nuestro periodo de análisis termina el 31/12/2021) - comparar solo
-- totales en bruto favorece a los periodos más largos. Se añade
-- "contratos_por_mes" para poder comparar de forma justa.
-- =====================================================================
WITH duracion_periodo AS (
    SELECT 'Pre-COVID' AS periodo_covid, 437 AS duracion_dias
    UNION ALL SELECT 'Estado de alarma', 421
    UNION ALL SELECT 'Post-estado de alarma', 235
)
SELECT
    df.periodo_covid,
    COUNT(*)                                          AS num_contratos,
    SUM(fc.importe_con_iva)                            AS importe_total_con_iva,
    ROUND(AVG(fc.importe_con_iva), 2)                  AS importe_medio_con_iva,
    dp.duracion_dias,
    ROUND(COUNT(*) / (dp.duracion_dias / 30.4), 1)     AS contratos_por_mes,
    ROUND(SUM(fc.importe_con_iva) / (dp.duracion_dias / 30.4), 2) AS importe_total_por_mes
FROM fact_contratos fc
JOIN dim_fecha df ON fc.fecha_key = df.fecha_key
JOIN duracion_periodo dp ON dp.periodo_covid = df.periodo_covid
WHERE df.fecha_key != -1
GROUP BY df.periodo_covid, dp.duracion_dias
ORDER BY MIN(df.fecha);

-- Conclusión: normalizando por mes, el ritmo de contratación es parecido
-- en los 3 periodos (Pre-COVID ~245/mes, Estado de alarma ~214/mes, Post
-- ~250/mes) - la caída real durante el estado de alarma es de solo ~13%,
-- mucho más suave de lo que sugerian los totales en bruto (que estaban
-- sesgados porque "Post-estado de alarma" dura menos tiempo: 7,7 meses
-- frente a los ~14 de los otros dos). Lo que se mantiene robusto tras
-- la corrección es el importe medio por contrato (no depende de la
-- duración del periodo): 2.127,55 € Pre-COVID -> 3.873,61 € en estado de
-- alarma -> 3.499,27 € después. El número de contratos apenas cambia, pero
-- cada uno es, de media, bastante más caro durante el COVID.


-- =====================================================================
-- 6. Estacionalidad: en que meses se concentran más contratos
-- Agregación + ordenación.
-- =====================================================================
SELECT
    df.mes,
    df.nombre_mes,
    COUNT(*)                 AS num_contratos,
    SUM(fc.importe_con_iva)  AS importe_total_con_iva
FROM fact_contratos fc
JOIN dim_fecha df ON fc.fecha_key = df.fecha_key
WHERE df.fecha_key != -1
GROUP BY df.mes, df.nombre_mes
ORDER BY num_contratos DESC;

-- Conclusión: noviembre concentra claramente mas contratos (1.167) y más
-- gasto (4.564.171,44 €) que cualquier otro mes, seguido de octubre (932 /
-- 3.501.186,96 €) - casi el doble que la media del resto de meses. Agosto
-- (484) y enero (496) son los mas bajos. El patrón encaja con el cierre
-- del ejercicio presupuestario municipal y con
-- el parón estival de agosto.

-- =====================================================================
-- 7. Comprobación de calidad
-- Mismos controles que ya corre src/04_load_snowflake.py al cargar
-- =====================================================================
SELECT 'fk_nulas_fecha' AS control, COUNT(*) AS valor
FROM fact_contratos WHERE fecha_key IS NULL
UNION ALL
SELECT 'fk_nulas_empresa', COUNT(*) FROM fact_contratos WHERE empresa_key IS NULL
UNION ALL
SELECT 'fk_nulas_area', COUNT(*) FROM fact_contratos WHERE area_key IS NULL
UNION ALL
SELECT 'fk_nulas_tipo_contrato', COUNT(*) FROM fact_contratos WHERE tipo_contrato_key IS NULL
UNION ALL
SELECT 'huerfanas_fecha', COUNT(*)
FROM fact_contratos fc LEFT JOIN dim_fecha df ON fc.fecha_key = df.fecha_key
WHERE df.fecha_key IS NULL
UNION ALL
SELECT 'huerfanas_empresa', COUNT(*)
FROM fact_contratos fc LEFT JOIN dim_empresa de ON fc.empresa_key = de.empresa_key
WHERE de.empresa_key IS NULL
UNION ALL
SELECT 'huerfanas_area', COUNT(*)
FROM fact_contratos fc LEFT JOIN dim_area da ON fc.area_key = da.area_key
WHERE da.area_key IS NULL
UNION ALL
SELECT 'huerfanas_tipo_contrato', COUNT(*)
FROM fact_contratos fc LEFT JOIN dim_tipo_contrato tc ON fc.tipo_contrato_key = tc.tipo_contrato_key
WHERE tc.tipo_contrato_key IS NULL
UNION ALL
SELECT 'duplicados_exactos', COUNT(*) FROM (
    SELECT expediente, empresa_key, importe_con_iva, fecha_key, objeto, COUNT(*) AS n
    FROM fact_contratos
    GROUP BY expediente, empresa_key, importe_con_iva, fecha_key, objeto
    HAVING COUNT(*) > 1
);


-- =====================================================================
-- 8. Detalle de los 3 contratos que superan el umbral legal
-- (complemento de la consulta 4, que mira cerca_umbral; esta mira
-- supera_umbral). Usado para el hallazgo "cómo es posible que un
-- contrato menor supere el umbral" del README.
-- =====================================================================
SELECT
    fc.expediente,
    de.nombre_normalizado,
    tc.tipo_contrato,
    fc.importe_sin_iva_estimado,
    tc.umbral_sin_iva,
    ROUND(100.0 * fc.importe_sin_iva_estimado / tc.umbral_sin_iva, 1) AS pct_del_umbral,
    da.area_departamento,
    fc.objeto
FROM fact_contratos fc
JOIN dim_empresa de ON fc.empresa_key = de.empresa_key
JOIN dim_tipo_contrato tc ON fc.tipo_contrato_key = tc.tipo_contrato_key
JOIN dim_area da ON fc.area_key = da.area_key
WHERE fc.supera_umbral = TRUE
ORDER BY pct_del_umbral DESC;

-- Conclusión: ninguno de los 3 (CABLES Y ESLINGAS S.L.U. 125,5%, ANGEL ROADE
-- S.L. 106,3%, NOYA VAZQUEZ, JORGE JUAN 192,8%) tiene en el objeto una
-- palabra clave que explique el exceso (a diferencia de otro contrato de
-- MONTAJES ELECTRICOS VIZCAINO S.L. que sí usa "Recoñecemento extraxudicial
-- factura", un mecanismo contable distinto al contrato menor). La
-- explicación más probable es una modificación/ampliación del contrato
-- durante la ejecución, o un error de clasificación del tipo_contrato - no
-- se puede confirmar con certeza solo con estos datos.


-- =====================================================================
-- 9. Porcentaje del umbral legal, contrato a contrato, para un proveedor
-- concreto. Usada para investigar si un mismo adjudicatario concentra
-- su actividad justo por debajo del límite legal (posible fraccionamiento
-- sistemático, no solo un contrato aislado).
-- Cambiar el nombre en el WHERE para repetir el análisis con cualquier
-- otro proveedor del ranking.
-- =====================================================================
SELECT
    fc.expediente,
    df.fecha,
    tc.tipo_contrato,
    fc.importe_sin_iva_estimado,
    tc.umbral_sin_iva,
    ROUND(100.0 * fc.importe_sin_iva_estimado / tc.umbral_sin_iva, 1) AS pct_del_umbral,
    fc.objeto
FROM fact_contratos fc
JOIN dim_empresa de ON fc.empresa_key = de.empresa_key
JOIN dim_fecha df ON fc.fecha_key = df.fecha_key
JOIN dim_tipo_contrato tc ON fc.tipo_contrato_key = tc.tipo_contrato_key
WHERE de.nombre_normalizado ILIKE '%CONSTRUCCIONES LOPEZ CAO%'  -- o 'ARIAS INFRAESTRUCTURAS', etc.
  AND tc.umbral_sin_iva IS NOT NULL
ORDER BY df.fecha;

-- Conclusión: de los 19 contratos de CONSTRUCCIONES LOPEZ CAO S.L. con
-- umbral aplicable, 10 están entre el 96,7% y el 100,0% del umbral legal,
-- un patrón que arranca justo en marzo de 2020 (antes, sus importes eran
-- mucho más dispersos: 32%, 9%, 0,2%). ARIAS INFRAESTRUCTURAS S.A. repite
-- el mismo patrón (5 de 11 contratos entre el 95,7% y el 100%), también
-- intensificándose desde mediados de 2020.


-- =====================================================================
-- 10. Importe total y nº de contratos por periodo_covid, para un
-- proveedor concreto. Usada para distinguir "la empresa desapareció del
-- ranking" (dejó de contratar) de "la empresa sigue ahí pero factura
-- mucho menos" (sigue contratando, solo que por importes menores).
-- =====================================================================
SELECT
    df.periodo_covid,
    COUNT(*)                        AS num_contratos,
    SUM(fc.importe_con_iva)         AS importe_total_con_iva,
    MAX(df.fecha)                   AS ultima_fecha
FROM fact_contratos fc
JOIN dim_empresa de ON fc.empresa_key = de.empresa_key
JOIN dim_fecha df ON fc.fecha_key = df.fecha_key
WHERE de.nombre_normalizado ILIKE '%MONTAJES ELECTRICOS VIZCAINO%'  -- o 'ARIAS INFRAESTRUCTURAS', etc.
  AND df.fecha_key != -1
GROUP BY df.periodo_covid
ORDER BY ultima_fecha;

-- Conclusión: MONTAJES ELECTRICOS VIZCAINO S.L. sigue teniendo contratos en
-- los 3 periodos (su último contrato en el dataset es de octubre de 2021,
-- no desaparece), pero el importe cae un 82% entre Pre-COVID (126.587,07 €)
-- y Estado de alarma (22.263,23 €) y no se recupera del todo después
-- (50.960,08 €) - sale del top 15 porque deja de ganar los contratos
-- grandes, no porque la empresa cierre. ARIAS INFRAESTRUCTURAS S.A. hace
-- justo lo contrario: crece de 1 contrato (29.262,10 €) Pre-COVID a 6
-- contratos (205.478,01 €) Post-alarma.


-- =====================================================================
-- 11. Posible fraccionamiento: pares de contratos del mismo área y tipo,
-- publicados con pocos días de diferencia, cada uno por debajo del umbral
-- individualmente pero que SUMADOS lo superarían, con objeto parecido
-- (EDITDISTANCE bajo = textos más parecidos). Es una señal a investigar,
-- no una prueba: en varios casos la explicación legítima es que un mismo
-- proyecto de obra exige contratos separados para roles profesionales
-- distintos (dirección de obra, dirección de ejecución, coordinación de
-- seguridad y salud, control arqueológico), que la ley exige adjudicar
-- por separado.
-- =====================================================================
SELECT
    a.expediente AS expediente_a, b.expediente AS expediente_b,
    a.empresa_key = b.empresa_key AS misma_empresa,
    deA.nombre_normalizado AS empresa_a, deB.nombre_normalizado AS empresa_b,
    dfA.fecha AS fecha_a, dfB.fecha AS fecha_b,
    DATEDIFF('day', dfA.fecha, dfB.fecha) AS dias_entre,
    a.importe_sin_iva_estimado AS importe_a, b.importe_sin_iva_estimado AS importe_b,
    a.importe_sin_iva_estimado + b.importe_sin_iva_estimado AS suma_sin_iva,
    tc.umbral_sin_iva,
    EDITDISTANCE(a.objeto, b.objeto) AS distancia_texto,
    a.objeto AS objeto_a, b.objeto AS objeto_b
FROM fact_contratos a
JOIN fact_contratos b
    ON a.area_key = b.area_key
   AND a.tipo_contrato_key = b.tipo_contrato_key
   AND a.expediente < b.expediente
JOIN dim_fecha dfA ON a.fecha_key = dfA.fecha_key
JOIN dim_fecha dfB ON b.fecha_key = dfB.fecha_key
JOIN dim_tipo_contrato tc ON a.tipo_contrato_key = tc.tipo_contrato_key
JOIN dim_empresa deA ON a.empresa_key = deA.empresa_key
JOIN dim_empresa deB ON b.empresa_key = deB.empresa_key
WHERE tc.umbral_sin_iva IS NOT NULL
  AND a.importe_sin_iva_estimado < tc.umbral_sin_iva
  AND b.importe_sin_iva_estimado < tc.umbral_sin_iva
  AND (a.importe_sin_iva_estimado + b.importe_sin_iva_estimado) > tc.umbral_sin_iva
  AND ABS(DATEDIFF('day', dfA.fecha, dfB.fecha)) <= 90
ORDER BY distancia_texto ASC
LIMIT 25;

-- Conclusión: el candidato más llamativo es ARIAS INFRAESTRUCTURAS S.A.,
-- que firmó el MISMO día (2020-10-13) dos contratos de "mejora de
-- pavimento de calzada" (Avenida de Glasgow y Rúa Sinfónica de Galicia),
-- cada uno justo por debajo de los 40.000 € (39.797,00 € y 39.793,23 €) -
-- sumados, 79.590,23 €, muy por encima del umbral de Obras. Es el caso que
-- más encaja con un fraccionamiento real (misma empresa, mismo día, mismo
-- tipo de obra, cada contrato calculado para no cruzar el límite). El
-- resto de resultados con mayor similitud de texto corresponden casi
-- siempre a roles profesionales distintos de un mismo proyecto de obra
-- (dirección de obra + dirección de ejecución + coordinación de seguridad
-- y salud + control arqueológico), que la normativa exige contratar por
-- separado - no es fraccionamiento, es la forma normal de tramitar una obra.
--
-- Aparte, el expediente 211/2020/389 (FEDERACION GALLEGA DE ATLETISMO DE
-- LA CORUÑA) aparece dos veces con el MISMO objeto pero importes distintos
-- (14.996,35 € y 13.996,04 €, en T3 y T4 de 2020) - no lo capturan las
-- reglas de deduplicación porque el importe difiere entre las dos filas.
-- Es, casi con toda seguridad, el mismo contrato facturado en dos fases (no
-- dos expedientes distintos), así que no es un caso de fraccionamiento,
-- pero merece quedar anotado como una peculiaridad del dato de origen.
