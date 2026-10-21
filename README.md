# Radar de trabajo remoto para LATAM

Una web que junta vacantes remotas abiertas a Latinoamérica en 9 áreas: video editing, copywriting, desarrollo web, automatización con IA, operaciones, customer success, onboarding de producto, inside sales y administración. Se actualiza sola todos los días.

## Cómo funciona

1. Cada día, GitHub Actions corre `scripts/fetch_jobs.py`.
2. El script lee 6 feeds públicos (RemoteOK, Remotive, Himalayas, We Work Remotely, Jobicy y Working Nomads) y, además, el sitio de empleo de cada empresa de `config/companies.json`.
3. Se queda con las vacantes cuyo **título** coincide con tus áreas (`config/keywords.json`) y que están abiertas a LATAM o al mundo.
4. Guarda el resultado en `data/jobs.json` y GitHub Pages publica `site/index.html`, que lee ese archivo.

No hay nada que instalar: el script usa solo la librería estándar de Python.

## Puesta en marcha (una sola vez)

1. En GitHub: **New repository**, nombre `remote-jobs-radar`, visibilidad **Public** (Pages gratis lo necesita), sin README.
2. Sube estos archivos al repo (botón **Add file → Upload files**):
   - `config/keywords.json`
   - `config/companies.json`
   - `scripts/fetch_jobs.py`
   - `site/index.html`
   - `data/jobs.json`
   - `data/employer_excluded.json`
   - `README.md`
3. **El workflow no se arrastra bien** porque la carpeta `.github` está oculta en Mac y Windows. Créalo a mano: **Add file → Create new file**, escribe el nombre `.github/workflows/update.yml` (las barras crean las carpetas) y pega el contenido del archivo `update.yml`.
4. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
5. **Actions → Actualizar vacantes y publicar el sitio → Run workflow.** Tarda 1 o 2 minutos.
6. Cuando termine, tu sitio queda en `https://TU-USUARIO.github.io/remote-jobs-radar/`. Ese es el link para compartir.

Si el paso 5 falla con un error de permisos al hacer push: **Settings → Actions → General → Workflow permissions → Read and write permissions.**

## Mantenimiento (unos 15 minutos a la semana)

- **Agregar o quitar palabras clave:** edita `config/keywords.json` en GitHub (lápiz). Cada área tiene `include` (frases que cuentan) y `exclude` (frases que descartan).
- **Agregar una empresa:** en `config/companies.json` copia una línea y cambia `name`, `ats` (greenhouse, lever, ashby o smartrecruiters) y `slug` (el nombre al final de la URL de su tablero, por ejemplo `jobs.lever.co/brevo` → `brevo`).
- **Ver por qué se descartó una vacante de empresa:** abre `data/employer_excluded.json`. Cada una trae el motivo y, si fue por el texto, la frase exacta.
- **Países de Himalayas:** `himalayas_countries` lista los 19 países de LATAM (códigos `AR`, `BR`, `MX`…) y `himalayas_countries_per_run` dice cuántos se consultan por día (4). Se rotan, así que cada país se revisa cada 5 días como máximo. Las vacantes abiertas a todo el mundo salen en todas las consultas. Subir ese número da más cobertura por día pero se acerca al límite de consultas de Himalayas.
- **Si una fuente falla**, GitHub te manda un correo. El sitio sigue publicado con las demás y el pie de página marca cuál no respondió.
- **Si dejan de llegar actualizaciones:** GitHub puede pausar los workflows programados de repos públicos tras 60 días sin actividad. Cada día se guarda un commit con `data/jobs.json`, lo que debería evitarlo, pero no lo he podido comprobar. Si pasa, entra a **Actions** y pulsa **Enable workflow**.
- **No corras el workflow a mano más de 3 veces al día:** Remotive pide máximo 4 consultas diarias y bloquea el exceso.

## Cómo se decide qué vacantes se muestran

- **Área:** coincidencia de frases en el título. Las etiquetas de los feeds se ignoran porque meten ruido (un Software Engineer aparecía como copywriting).
- **Región en las bolsas (feeds):**
  - Se lee el texto de ubicación que publica cada fuente.
  - Ahí se distingue "Todo el mundo", "Toda LATAM" o países concretos.
  - Las vacantes que dicen "USA only", "Europe" y similares se descartan.
  - Las que no indican región quedan ocultas hasta marcar "Incluir vacantes sin región indicada".
- **Región en las empresas (se verifica en tres pasos):**
  1. La empresa debe marcar la vacante como remota.
  2. La ubicación y el código de país no pueden ser de EE. UU., Canadá, Europa u otra región fuera de LATAM.
  3. La descripción no puede exigir vivir en EE. UU. ("US based", "continental US", "authorized to work in the US", "must be located in…") ni en otro país fuera de LATAM.
  - Si pasa los tres pero no dice dónde sí se puede vivir, queda como "región sin indicar" (oculta por defecto). Solo se publica como LATAM, mundo o país cuando la ubicación o la descripción lo dicen.
- **Vigencia:** en las empresas, una vacante se quita en cuanto desaparece de su tablero, porque el tablero lista todo lo abierto. En las bolsas se quita si lleva 10 días sin aparecer en su fuente, si pasó su fecha de vencimiento (cuando el feed la da) o si tiene más de 45 días.

## Límites conocidos

- **La región es una lectura automática del texto** y puede equivocarse. Hay que confirmarla en la vacante.
- **En las bolsas no se comprueba si cada vacante sigue abierta.** Solo se quitan las que dejan de aparecer en el feed. Una verificación por enlace queda pendiente porque muchos sitios bloquean esas consultas.
- **Himalayas aporta la mayoría de las vacantes** porque permite filtrar por país. Una vacante que solo acepta a un país (por ejemplo, solo Perú) aparece cuando le toca el turno a ese país, hasta 5 días después de publicada. Las demás fuentes entregan pocas: la API gratuita de Remotive devuelve solo 12 vacantes y RemoteOK, unas 100 recientes.
- **Automatización con IA tiene pocas vacantes** con las frases actuales. Conviene afinar esa lista con ejemplos reales.
- **Las áreas de operaciones, customer success, onboarding, inside sales y administración** buscan por frases de título (`operations manager`, `customer success`, `onboarding`, `sdr`, `executive assistant`, etc.). Un título poco convencional no aparecerá hasta agregar su frase en `config/keywords.json`.
- **Himalayas hace 17 búsquedas por país** (4 países por día), así que cada corrida tarda unos minutos. Si recibes un error 429, baja `himalayas_countries_per_run` a 2.

- **La lectura de la descripción es por frases fijas.** Puede descartar una vacante buena (por ejemplo, un beneficio "dentro de EE. UU." en la misma descripción) y puede dejar pasar una que exija EE. UU. con otras palabras. El archivo de descartadas sirve para detectar lo primero.
- **Solo funciona con empresas en Greenhouse, Lever, Ashby o SmartRecruiters.** Las que usan otro sistema (Workday o su propio sitio) hay que revisarlas a mano.

## Términos de las fuentes

Cada fuente pide enlazar a su publicación original y nombrarla. La página lo hace en cada fila y en el pie.

- **Remotive** prohíbe reenviar sus vacantes a Google Jobs o LinkedIn y pedir correos a cambio de mostrarlas. Esta web no hace ninguna de las dos cosas y lleva `noindex` para que Google no la indexe. **No agregues formularios de suscripción por correo** mientras Remotive esté entre las fuentes.
- **RemoteOK** pide un enlace sin `nofollow` y no permite usar su logo.
- **Himalayas** pide un enlace visible a himalayas.app y mencionar que los datos vienen de ahí.
- **We Work Remotely** y **Jobicy** piden atribución con enlace a la fuente.
- **Working Nomads:** no encontré términos publicados sobre este feed. Se acredita igual y conviene revisarlo antes de compartir el sitio con mucha gente.

## Probarlo en tu computadora

```
python3 scripts/fetch_jobs.py
mkdir -p _t/data && cp site/index.html _t/ && cp data/jobs.json _t/data/
cd _t && python3 -m http.server 8000
```

Abre http://localhost:8000. Abrir `index.html` con doble clic no funciona porque el navegador bloquea la lectura de `data/jobs.json`.
