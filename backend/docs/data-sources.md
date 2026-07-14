# Fuentes oficiales, acceso y automatización de PRORA

Auditoría verificada el **13 de julio de 2026** contra fichas y endpoints de las entidades
responsables. Las fechas de corte describen el dato, no la fecha en que se modificó el metadato.
Que un recurso sea público no implica que esté actualizado ni que tenga un esquema estable.

## Clasificación de acceso

- **API pública:** consumo programático sin credenciales de usuario. Para Socrata se recomienda
  `X-App-Token` por cuota y trazabilidad, aunque SODA 2.1 admite consultas simples anónimas.
- **Archivo público:** URL descargable sin autenticación, pero requiere control de versión,
  checksum, parser y prueba de contrato.
- **Formulario o acceso institucional:** descarga condicionada a identificación/propósito, o
  información operativa disponible solo en sistemas autorizados. No se automatiza simulando una
  sesión humana.

## Matriz verificada

| Dominio y producto | Acceso automatizable | ID o endpoint oficial | Cobertura, periodo y frecuencia | Campos útiles verificados | Licencia/atribución | Límites y decisión para PRORA |
|---|---|---|---|---|---|---|
| **SIVIGILA histórico agregado** | **Sí, SODA 2.1 público** | [`4hyg-wa9d`](https://www.datos.gov.co/Salud-y-Protecci-n-Social/Datos-de-Vigilancia-en-Salud-P-blica-de-Colombia/4hyg-wa9d/about_data); `GET https://www.datos.gov.co/resource/4hyg-wa9d.json` | Nacional, municipio-departamento y semana; datos **2007–2022**; ficha declara actualización anual. Consulta oficial al 13-07-2026: 2.465.826 filas. | `cod_eve`, `nombre_evento`, `semana`, `ano`, `cod_dpto_o`, `cod_mun_o`, `departamento_ocurrencia`, `municipio_ocurrencia`, `conteo` | CC BY-SA 4.0 en metadato Socrata; atribución INS | Es histórico, no operativo. Incluye las enfermedades vectoriales priorizadas e IRAG inusitada, pero no equivale a toda IRA. Concatenar departamento y municipio después de validar códigos; conservar categorías desconocidas/exterior. **Debe ser una fuente activa de backfill, separada del flujo actual.** |
| **SIVIGILA microdatos anonimizados 2024** | **Sí, archivos XLSX públicos directos; no API** | [Biblioteca SharePoint de Microdatos](https://portalsivigila.ins.gov.co/Microdatos/Forms/AllItems.aspx); patrón verificado `https://portalsivigila.ins.gov.co/Microdatos/Datos_2024_{evento}.xlsx` | Vigencia final 2024 por evento. Se verificaron HTTP 200, tipo XLSX y modificación 13-09-2025 para 210, 217, 220, 345, 348, 420, 430, 440, 460, 470, 490, 495, 895 y 995. Los archivos miden entre 20 KB y 91 MB. | Los eventos individuales exponen 72 campos; para el agregado solo se leen evento, semana, año y municipio de ocurrencia. El evento colectivo 995 usa municipio notificador y `tot_irag + tot_irauci + tot_iraext`; una fila **no** equivale a un caso. | El portal los describe como bases depuradas, nominales y sin identificación personal; atribución INS y condiciones del portal | Aunque están anonimizados contienen cuasi-identificadores. PRORA descarga a almacenamiento temporal, calcula SHA-256, agrega inmediatamente a evento-municipio-semana y descarta el XLSX. El snapshot contiene únicamente agregados. No mezcla 345, 348 y 995: 348 conserva continuidad como proxy IRAG; 345/995 quedan contextuales por tener población/unidad distintas. Sigue siendo histórico, no una señal operativa 2026. |
| **SIVIGILA reciente y operativo 2025+** | **No hay API pública tabular estable confirmada** | [Buscador de microdatos SIVIGILA](https://portalsivigila.ins.gov.co/buscador), [vigilancia rutinaria](https://portalsivigila.ins.gov.co/Paginas/Vigilancia-Rutinaria.aspx) y BES | El BES se publica semanalmente, pero no constituye una base municipal completa. Al 13-07-2026 PRORA no verificó archivos anuales 2025+ con el contrato anterior. | El esquema depende del evento y del diccionario anual SIVIGILA; el BES es PDF | Aplicar condiciones del INS y finalidad declarada | No se automatiza una sesión humana ni se infieren municipios desde totales departamentales. Los datos 2025+ requieren publicación tabular oficial verificable o entrega institucional agregada; hasta entonces no se presentan como predicción en tiempo real. |
| **PAI departamental histórico** | **Sí, SODA 2.1 público** | [`6i25-2hdt`](https://www.datos.gov.co/Salud-y-Protecci-n-Social/Coberturas-administrativas-de-vacunaci-n-por-depar/6i25-2hdt/about_data); `GET https://www.datos.gov.co/resource/6i25-2hdt.json` | 33 departamentos, anual, **2019–2022**, 660 filas. El dato se actualizó por última vez el 29-11-2023; el metadato cambió en 2026. | `coddepto`, `departamento`, `a_o`, `biol_gico`, `cobertura_de_vacunaci_n`; además campos de presentación `indicator1*` | CC BY-SA 4.0 en metadato Socrata; atribución MinSalud | Solo BCG, PENTA3, N2D, TV y TV.R, con variantes de texto/encoding entre años. No contiene influenza ni fiebre amarilla y no puede imputarse a municipios. Útil como control histórico departamental, no como covariable municipal reciente. |
| **PAI municipal 1998–2025** | **Sí, archivo público directo** | [`coberturas-vacunacion-municipal-desde-1998.zip`](https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VS/PP/PAI/coberturas-vacunacion-municipal-desde-1998.zip) | Hojas anuales 1998–2025; archivo publicado/modificado en febrero de 2026; corte anual 2025. | Por hoja: `CODEP`/departamento, `DIVIPOLA`, `Municipio`, poblaciones meta, dosis y porcentajes por biológico, dosis y grupo de edad. Incluye SRP, influenza y fiebre amarilla, entre otros. El esquema cambia por año. | El ZIP no expone una licencia estructurada junto al archivo; atribuir a MinSalud y verificar condiciones antes de redistribuir | Archivo Excel ancho (hasta 158 columnas en 2025), encabezado en fila 5, hojas y rótulos variables. **Público, no “institucional”**; necesita parser versionado, checksum y diccionario por hoja. |
| **PAI municipal 2026** | **Sí, archivo público directo** | [`dosis-coberturas-biologicos-municipios-2026.zip`](https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VS/PP/PAI/dosis-coberturas-biologicos-municipios-2026.zip) | Hojas `Enero` y `Febrero`; 1.157 y 2.406 filas físicas respectivamente en la versión inspeccionada; publicado en marzo de 2026 | `Cons`, `Departamento`, `COD` (DIVIPOLA), `Municipio`, metas, dosis y coberturas por biológico/grupo; 127–128 columnas. Contiene influenza, SRP y fiebre amarilla | No se observó licencia estructurada junto al ZIP; atribución MinSalud | Descarga automatizable, pero el nombre/versionado futuro no es un API. Hay filas de agregados y posibles duplicados territoriales que deben clasificarse antes de ingerir. No asumir publicación mensual continua solo por existir dos hojas. |
| **IDEAM multivariable reciente** | **Sí, SODA 2.1 público** | [`57sv-p2fu`](https://www.datos.gov.co/Ambiente-y-Desarrollo-Sostenible/Datos-de-Estaciones-de-IDEAM-y-de-Terceros/57sv-p2fu/about_data); `GET https://www.datos.gov.co/resource/57sv-p2fu.json` | Red nacional de estaciones, no cobertura censal municipal. La ficha declara frecuencia anual, pero el recurso se renueva diariamente y funciona como ventana reciente: consulta del 13-07-2026 cubría solo 10–11 de julio, 340 nombres de municipio y los 33 departamentos. | `codigoestacion`, `codigosensor`, `fechaobservacion`, `valorobservado`, `nombreestacion`, `departamento`, `municipio`, `zonahidrografica`, `latitud`, `longitud`, `descripcionsensor`, `unidadmedida`, `entidad` | CC BY-SA 4.0; atribución IDEAM | Datos de IDEAM y terceros, crudos y con posible retraso/error. Conservar `entidad`; filtrar sensor/unidad. Sirve para actualización reciente, **no para backfill histórico** ni como medición de todos los municipios. |
| **IDEAM precipitación histórica** | **Sí, SODA 2.1 público** | [`s54a-sgyg`](https://www.datos.gov.co/Ambiente-y-Desarrollo-Sostenible/Precipitaci-n/s54a-sgyg/about_data); `GET https://www.datos.gov.co/resource/s54a-sgyg.json` | Nacional por estación; observación típica cada 10 minutos; publicación diaria. Primer/último timestamp consultado: 20-01-2003 / 12-07-2026. | Los 12 campos anteriores excepto `entidad`; `descripcionsensor=Precipitación`, `unidadmedida=Milímetros` | CC BY-SA 4.0; atribución IDEAM | Control de calidad básico, no validación oficial final. El intervalo de observación (10 min) no es la frecuencia de actualización (diaria). Agregación semanal e interpolación son transformaciones versionadas de PRORA. |
| **IDEAM temperatura histórica** | **Sí, SODA 2.1 público** | [`sbwg-7ju4`](https://www.datos.gov.co/Ambiente-y-Desarrollo-Sostenible/Temperatura-Ambiente-del-Aire/sbwg-7ju4/about_data); `GET https://www.datos.gov.co/resource/sbwg-7ju4.json` | Nacional por estación; observación horaria; publicación diaria. Primer/último timestamp consultado: 01-01-2001 / 12-07-2026. | Mismos 12 campos de precipitación; sensor y unidad identifican temperatura del aire | CC BY-SA 4.0; atribución IDEAM | Aplicar QA, deduplicación estación-sensor-fecha y homologación de unidades. No usar una estación como si fuera el municipio completo. |
| **IDEAM humedad histórica** | **Sí, SODA 2.1 público** | [`uext-mhny`](https://www.datos.gov.co/Ambiente-y-Desarrollo-Sostenible/Humedad-del-Aire/uext-mhny/about_data); `GET https://www.datos.gov.co/resource/uext-mhny.json` | Nacional por estación; humedad a 2 m horaria; publicación diaria. Primer/último timestamp consultado: 04-01-2001 / 12-07-2026. | Mismos 12 campos; humedad relativa y unidad porcentual según sensor | CC BY-SA 4.0; atribución IDEAM | Es el dataset propiedad de la Oficina de Informática IDEAM. No usar vistas comunitarias como `debm-5t2v` como fuente canónica. |
| **Catálogo de estaciones IDEAM** | **Sí, SODA 2.1 público** | [`hp9r-jxuu`](https://www.datos.gov.co/Ambiente-y-Desarrollo-Sostenible/Cat-logo-Nacional-de-Estaciones-del-IDEAM/hp9r-jxuu/about_data); `GET https://www.datos.gov.co/resource/hp9r-jxuu.json` | Nacional; actualización declarada diaria | `codigo`, `nombre`, `categoria`, `tecnologia`, `estado`, `departamento`, `municipio`, `ubicaci_n`, `altitud`, `longitud`, `latitud`, fechas, áreas hidrográficas y `entidad` | CC BY-SA 4.0; atribución IDEAM | Catálogo, no observaciones. Debe resolver estación y operador conservando vigencia/estado. IDEAM advierte que datos automáticos pueden estar sin validar. |
| **Deforestación nacional en datos.gov.co** | **Archivo público, no SODA tabular** | [`39dh-rc72`](https://www.datos.gov.co/d/39dh-rc72) (nacional) y [`env9-bhc9`](https://www.datos.gov.co/d/env9-bhc9) (Amazonia) | Recursos `assetType=file`, frecuencia anual; a la fecha contienen `Cambio_2022.zip` y `Cambio_2022_amazonia.zip` | No hay columnas SODA. El esquema está dentro del ZIP geoespacial y debe fijarse después de inspeccionar archivo, CRS, unidad y periodo | CC BY-SA 4.0 en metadato; atribución IDEAM | Son descargables, pero están rezagados y no deben configurarse como dataset tabular. Registrar checksum y no confundir cambio neto de bosque con hectáreas municipales de deforestación anual. |
| **SMByC anual 2024 y DTD 2025** | **Sí, repositorio/archivos públicos; no API estable** | [Repositorio SMByC](https://bart.ideam.gov.co/smbyc/), [resultados 2024](https://bart.ideam.gov.co/smbyc/Resultados%20Cifra%20Deforestacion%202024/) y [boletín DTD 45](https://bart.ideam.gov.co/smbyc/Boletines%20Detecciones%20Tempranas%20de%20Deforestacion/2025/Boletin/Boletin%2045%20-%20IV%20trimestre%202025.pdf) | Cifra consolidada anual 2024; DTD trimestral hasta IV-2025 | PDF, mapas y productos geográficos según carpeta; no se verificó contrato tabular uniforme | Condiciones del IDEAM por producto; conservar atribución y metadatos | DTD es una alerta temprana, no la cifra anual consolidada. Crear dos fuentes y dos unidades/temporalidades; no ejecutar un mismo cron trimestral sobre ambas. |
| **DIVIPOLA MGN 2025** | **Sí, ArcGIS REST público** | [`FeatureServer/317/query`](https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DIVIPOLA_MGN_2025/FeatureServer/317/query) | 1.122 entidades en consulta del 13-07-2026; versión MGN 2025; máximo 2.000 por respuesta | `OBJECTID`, `DPTO_CCDGO`, `MPIO_CCDGO`, `MPIO_CDPMP`, `MPIO_TIPO`, `MPIO_NAREA`, `MPIO_NANO`, `DPTO_CNMBRE`, `MPIO_CNMBRE`, `MPIO_CRSLCION`; geometría poligonal EPSG:3857 si se solicita | Copyright DANE; `licenseInfo` vacío en el servicio. Verificar condiciones para redistribución | El conector sin geometría es automatizable y cabe en una respuesta, aunque debe paginar por robustez. Preservar ceros iniciales y refrescar solo al cambiar la versión MGN. |
| **CNPV 2018 socioeconómico** | **Archivos públicos; no SODA** | [Catálogo DANE 643](https://microdatos.dane.gov.co/catalog/643), [descargas por departamento](https://microdatos.dane.gov.co/index.php/catalog/643/get-microdata) y materiales MGN integrados | Nacional; censo estático 2018; municipio, clase y niveles menores sujetos a anonimización | Viviendas: `U_DPTO`, `U_MPIO`, `VB_ACU` (acueducto), `VC_ALC` (alcantarillado), entre otros. Hogares: `H_NRO_CUARTOS`, `H_NRO_DORMIT`, `HA_TOT_PER` para construir hacinamiento con metodología explícita | Microdatos de uso público gratuitos, cita DANE obligatoria; Ley 79/1993 y condiciones del catálogo limitan revelación/redistribución | Público, no “institucional”. Requiere descarga ZIP, unión de viviendas/hogares, ponderación/agregación municipal, control de reserva y definición versionada del indicador. Es covariable estructural de 2018, no dato actual. |

## Composición urbano-rural CNPV 2018

PRORA persiste la composición municipal desde la capa oficial ArcGIS REST
[`Clases Integradas / 801`](https://geoportal.dane.gov.co/mparcgis/rest/services/MARCO_INTEGRADO/Serv_DatosCNPV2018_Integrados_MGN2018/MapServer/801),
separada de la capa municipal agregada `800`. La capa `801` publica
`MPIO_CDPMP`, `CLAS_CCDGO` y `STP27_PERS`; el contrato conserva las tres clases:

- `1`: cabecera municipal;
- `2`: centro poblado;
- `3`: área resto municipal.

Las variables derivadas usan como denominador la suma poblacional de las clases
1, 2 y 3 para el mismo municipio. `urban_population_pct` corresponde a clase 1;
`rural_population_pct` corresponde a clases 2 y 3. También se conservan por
separado los porcentajes de centro poblado y área resto. Esta es una covariable
estructural del CNPV 2018, no una medición anual ni una inferencia por densidad.
Cada ingesta archiva las filas de las capas `800` y `801` en el mismo snapshot
inmutable, identifica la capa de origen, registra las fórmulas en el manifiesto
y envía clases/códigos inválidos a cuarentena.

## API Socrata: contrato operativo

Socrata documenta [endpoints](https://dev.socrata.com/docs/endpoints),
[paginación](https://dev.socrata.com/docs/paging.html) y
[App Tokens](https://dev.socrata.com/docs/app-tokens.html). PRORA usa actualmente SODA 2.1:

```text
GET https://www.datos.gov.co/resource/{dataset_id}.json
X-App-Token: <token opcional recomendado>
$limit=<lote>&$offset=<desplazamiento>&$order=:id
```

La paginación sin `$order` no es determinista. Para millones de registros se debe usar marca de
agua por fecha/año y particiones, no recorrer offsets crecientes en cada ejecución. SODA 3 requiere
token y favorece `POST`, pero migrarlo exige una prueba de compatibilidad; no se cambia el endpoint
en producción solo porque la documentación lo denomine “latest”.

## Auditoría de `source_catalog.py`

Esta auditoría no modifica el catálogo de ejecución; documenta los cambios que debe aplicar la capa
de conectores/operación en una iteración controlada.

| Registro actual | Veredicto | Corrección necesaria |
|---|---|---|
| `dane-divipola` | Correcto | Mantener capa 317 y agregar en metadatos versión 2025, campos, EPSG y condición de licencia no declarada. |
| `ideam-climate` (`57sv-p2fu`) | Parcial | “Nacional” significa red con presencia en 33 departamentos, no cobertura de 1.122 municipios. Marcarlo como ventana reciente multivariable/terceros y conservar `entidad`; no usarlo para historia desde 2018. |
| `ideam-precipitation` (`s54a-sgyg`) | Correcto con precisión | Separar `observation_interval=10 minutes` de `publication_refresh=daily`. |
| `ideam-stations` (`hp9r-jxuu`) | Correcto | Conservarlo como catálogo, no como observación climática. |
| `sivigila-national` | Correcto para historia | `4hyg-wa9d` permanece como agregado reproducible 2007–2022; no se presenta como dato vigente. |
| `sivigila-microdata-2024` | Correcto con control de privacidad | Contrato por evento, descarga efímera, SHA-256 del XLSX y snapshot únicamente agregado. Mantener 345/995 fuera de la serie IRA canónica por incompatibilidad de unidad; 348 conserva el proxy histórico explícito. |
| `pai-national` | **Modelo de acceso incorrecto/incompleto** | No es únicamente `institutional-file`: existen `6i25-2hdt`, el ZIP municipal 1998–2025 y el ZIP enero–febrero 2026, todos públicos. Puede seguir `requires_configuration` hasta implementar parser/checkpoint, pero `source_type` y `reason` deben decir **archivo público sin API estable**, no acceso restringido. El visor `rssvr2` presenta error de configuración y no debe ser el único endpoint. |
| `ideam-deforestation` | **Mezcla productos** | Separar cifra anual consolidada y DTD trimestral. Los IDs `39dh-rc72`/`env9-bhc9` son archivos, no tablas; el repositorio 2024 es más reciente. Ajustar cron y unidad por producto. |
| `dane-socioeconomic` | **Modelo de acceso impreciso** | CNPV 2018 ofrece ZIP públicos. `requires_configuration` es correcto por falta de parser/indicador aprobado, no por acceso institucional. Cambiar a `public-file` y registrar términos/cita DANE. |
| Temperatura/humedad histórica | **Faltan** | Incorporar `sbwg-7ju4` y `uext-mhny` como fuentes públicas activas para backfill; no usar la vista comunitaria `debm-5t2v`. |

## Prioridad de integración

1. Mantener `4hyg-wa9d` para 2007–2022 y ejecutar el conector anual 2024 por grupos completos de
   evento. Conservar 2025+ como fuente independiente condicionada hasta verificar una publicación
   tabular oficial; el BES no se asigna a municipios.
2. Implementar parser PAI por versión para los dos ZIP públicos y usar `6i25-2hdt` como control de
   reconciliación departamental, no como sustituto municipal.
3. Añadir temperatura `sbwg-7ju4` y humedad `uext-mhny`; usar `57sv-p2fu` solo como actualización
   reciente y las series específicas para historia.
4. Implementar agregados CNPV 2018 con definición revisada de agua, alcantarillado y hacinamiento.
5. Mantener deforestación deshabilitada hasta separar anual/DTD y fijar esquema geoespacial.

## Reglas de calidad y trazabilidad

- Preservar código DIVIPOLA como texto, fecha/semana, unidad, URL, ID/archivo, fecha de extracción,
  atribución, licencia/condiciones y SHA-256 del original.
- No interpretar la fecha de actualización del metadato como fecha del dato.
- No propagar una cobertura departamental a municipios ni una estación a todo un municipio.
- Normalizar mojibake y sinónimos de biológico/evento sin reemplazar el valor fuente.
- Mantener observación, DTD, cifra anual consolidada y predicción en entidades separadas.
- Cuarentenar archivos con hoja/campos distintos al contrato aprobado; nunca adaptar columnas por
  posición silenciosamente.
- Publicar siempre fecha de corte, completitud territorial y estado de validación de cada fuente.
