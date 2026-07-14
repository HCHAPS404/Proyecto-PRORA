# Seguridad, privacidad y uso responsable

## Principios

- **Datos mínimos:** PRORA trabaja con agregados municipio-semana. No necesita
  nombres, documentos, teléfonos, direcciones ni historias clínicas.
- **Separación de funciones:** ciudadanía consulta información pública; usuarios
  autenticados guardan preferencias; analistas gestionan fuentes y modelos;
  administradores controlan operación.
- **Trazabilidad:** cada ingesta, versión, pronóstico, alerta y acción privilegiada
  debe poder asociarse a fuente, fecha, versión y `request_id`.
- **Fallo seguro:** una fuente incompleta, modelo ausente o proveedor LLM caído se
  informa; no se reemplaza con información inventada.

## Amenazas prioritarias

La revisión debe cubrir como mínimo el
[OWASP API Security Top 10 2023](https://owasp.org/API-Security/editions/2023/en/0x11-t10/),
especialmente autorización por objeto/función, autenticación, consumo de recursos,
SSRF, inventario de endpoints y consumo inseguro de APIs externas.

| Riesgo | Control esperado |
| --- | --- |
| Acceso a recursos de otro usuario | filtrar siempre por identidad/rol en servidor; UUID no es autorización |
| Robo o repetición de sesión | acceso corto, refresh rotado/revocable, Argon2, TLS y cierre de sesión |
| Abuso y agotamiento | rate limiting, límites de payload/paginación/tiempo, cuotas de entrenamiento |
| Inyección | validación Pydantic, consultas parametrizadas, listas permitidas en Socrata |
| SSRF | conectores con hosts y datasets permitidos; nunca descargar una URL arbitraria del usuario |
| Dependencia externa comprometida | timeouts, reintentos acotados, checksum, esquema y cuarentena |
| Modelo o alerta manipulados | roles, artefactos inmutables, checksum, aprobación y auditoría |

## Identidad y sesión

- Contraseñas de al menos 12 caracteres; Argon2 para hashing y nunca registro del
  secreto. En producción conviene añadir verificación de correo, MFA para roles
  privilegiados y controles contra credenciales filtradas.
- JWT de acceso breve y token de renovación revocable. Las llaves deben provenir
  del gestor de secretos y rotarse con periodo de convivencia de claves.
- Para navegador, la evolución recomendada es refresh token en cookie `HttpOnly`,
  `Secure`, `SameSite` apropiado y protección CSRF. Si se mantiene almacenamiento
  web, una vulnerabilidad XSS puede extraer tokens y debe aceptarse explícitamente.
- Cada operación de fuentes, entrenamiento, promoción y configuración necesita
  autorización de servidor; ocultar un botón no es un control.

## API y red

- TLS 1.2 o superior; HSTS en el borde público una vez que todo el dominio use
  HTTPS. Nginx aporta cabeceras básicas, pero CSP debe probarse con los recursos
  reales antes de imponerla.
- CORS con orígenes exactos. No combinar credenciales con `*`.
- La base, bandeja institucional y registro de modelos permanecen en red privada.
- Fijar límites de solicitud en proxy y aplicación, así como timeouts de entrada,
  base y conectores. Los trabajos costosos se encolan en el worker.

## Datos de salud

- Rechazar o poner en cuarentena archivos que contengan campos identificadores no
  contemplados. No basta con ocultarlos en el frontend.
- Cifrar tránsito, base, copias, objetos y volúmenes. Restringir exportaciones y
  registrar quién descargó qué agregado.
- Acordar clasificación, finalidad, retención, eliminación y responsable de cada
  fuente con INS, Ministerio, IDEAM, DANE y entidades territoriales según aplique.
- Aplicar supresión o agrupación adicional a celdas pequeñas antes de publicación
  para reducir riesgo de reidentificación.

## Agente analítico

El proveedor generativo es opt-in. Sin llave, el agente determinista continúa
operando sobre la base agregada.

- Enviar únicamente hechos agregados recuperados por la API; nunca archivos
  originales, tokens, correos, prompts internos ni identificadores personales.
- Mostrar procedencia, fecha, horizonte e incertidumbre; distinguir observación de
  predicción y declarar cuando no hay evidencia.
- No permitir que el modelo ejecute SQL, cambie alertas, entrene modelos o llame
  URLs arbitrarias. Toda herramienta requiere esquema, lista permitida y control
  de autorización separado.
- Conservar auditoría mínima con política de retención; evitar guardar preguntas
  que puedan contener datos personales sin filtrado.
- Revisar contrato, ubicación del tratamiento y retención del proveedor antes de
  habilitarlo en producción.

## Cadena de suministro y secretos

- `.env`, credenciales, datos y artefactos no se incluyen en imágenes ni Git.
- Generar SBOM, fijar imágenes por digest en producción, escanear CVE y actualizar
  dependencias con pruebas. Ejecutar contenedores como usuario no root.
- Proteger CI/CD con ramas aprobadas, firmas o procedencia de artefactos y
  credenciales de vida corta. Separar secretos de build y runtime.
- Rotar inmediatamente cualquier secreto expuesto; eliminarlo del último commit
  no lo elimina del historial.

## Registro y respuesta a incidentes

Registrar autenticación, denegaciones, cambios de rol, sincronizaciones, calidad,
entrenamientos, promoción, alertas y exportaciones. No registrar contraseñas,
tokens, archivos fuente ni respuestas completas de terceros. Centralizar alertas
por picos de 401/403/429, errores de fuente, cambios de volumen, deriva y fallas de
checksum.

Antes de producción deben existir responsables, contactos de entidades, niveles
de severidad, aislamiento, revocación de sesión, reversión de modelos,
preservación de evidencia, comunicación y ejercicios periódicos.

## Lista de salida

- [ ] Revisión de autorización por rol y por objeto.
- [ ] MFA para analistas y administradores.
- [ ] TLS, HSTS, CSP evaluada, CORS exacto y base no pública.
- [ ] Gestor de secretos, rotación y escaneo de repositorio.
- [ ] SAST, SCA/SBOM, DAST y prueba de carga.
- [ ] Copia y restauración verificadas.
- [ ] Evaluación de privacidad y convenios de fuente aprobados.
- [ ] Modelos aprobados, calibrados, auditables y reversibles.
- [ ] Monitoreo, alertamiento e incident response probado.
