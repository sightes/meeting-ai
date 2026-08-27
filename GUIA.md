# Notekeeper — Guía completa

CLI local para grabar reuniones, transcribirlas, consultarlas con IA y generar tareas Jira.

## Índice

1. [Instalación](#instalación)
2. [Captura de audio (mic, sistema o ambos)](#captura-de-audio)
3. [Grabar](#grabar)
4. [Transcribir](#transcribir)
5. [Consultar y buscar](#consultar-y-buscar)
6. [Resumen + tareas Jira](#resumen--tareas-jira)
7. [Configuración (.env)](#configuración-env)
8. [Estructura de datos](#estructura-de-datos)
9. [Solución de problemas](#solución-de-problemas)

---

## Instalación

```bash
cd meeting-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

- Python 3.11+
- `ffmpeg` para soporte de MP3/M4A
- GPU recomendada para Whisper large-v3

---

## Captura de audio

En macOS el **micrófono físico jamás escucha el audio del sistema** (es hardware).
El audio de la computadora solo llega a través de dispositivos virtuales.

### Dispositivos típicos (después de instalar BlackHole)

| Dispositivo | Rol |
|---|---|
| `USB Microphone` | Tu voz (físico) |
| `BlackHole 2ch` | Cable virtual: recibe lo que sale por "notekeeper out" |
| `notekeeper out` | Multi-salida = Bocinas + BlackHole |
| `notekeeper in` | Agregado (mic + sistema) — opcional |

### Ruta del audio

1. Instala el driver virtual **BlackHole** (https://existential.audio/blackhole/).
2. En **Audio MIDI Setup** crea la multi-salida **"notekeeper out"** con
   `Bocinas + BlackHole 2ch`, todo a **48 kHz**.
3. En la app de la reunión (Zoom/Meet/Teams) configura la **salida** como
   **"notekeeper out"**: así el sonido va a tus oídos Y a BlackHole.
4. Graba con los comandos de abajo eligiendo la entrada correcta.

### ¿Qué entrada usar?

Modo de grabación                  | Entrada                       | Resultado
-----------------------------------|-------------------------------|----------------------------------
Micrófono físico                   | `-d 5` (USB Microphone)       | Solo tu voz
Solo audio del sistema             | `-d 10` (BlackHole 2ch)       | Solo la reunión/otros
Reunión completa (recomendado)     | `-m --mic 5`                  | Tu voz + audio del sistema (mezclado)

---

## BlackHole: uso y recomendaciones

### Qué es y cómo funciona
**BlackHole** es un *driver de audio virtual* gratuito (https://existential.audio/blackhole/)
que crea un "cable digital": todo lo que la app envía a su salida entra en BlackHole
y queda disponible como una entrada que cualquier grabador puede leer.
Es **imprescindible** en macOS para capturar el audio de la reunión, porque el
hardware del micrófono jamás escucha el audio del sistema.

### Instalación y configuración recomendada
1. Descarga e instala el driver (BlackHole 2ch es suficiente para reuniones).
2. Verifica que aparezcan nuevos dispositivos con:
   ```bash
   python -m notekeeper rec -l
   ```
   Debe listar `BlackHole 2ch` (y `BlackHole 16ch` si instalaste esa versión).
3. **Ajusta TODOS los dispositivos implicados a la misma frecuencia de muestreo**
   (48 kHz) en *Audio MIDI Setup*: bocinas, micrófono y BlackHole. Discrepancias de
   frecuencia son la causa #1 de grabaciones en silencio o distorsionadas.
4. Crea una **multi-salida** (p. ej. "notekeeper out") con `Bocinas + BlackHole 2ch`.
   Así escuchas el audio Y este se captura a la vez.
5. En la app de la reunión (Zoom / Meet / Teams), fija la **salida** a la multi-salida
   "notekeeper out" y la **entrada** a tu micrófono. Mantén el **mic en silencio / mute** en
   video-llamadas para evitar eco y doble captura.

### Recomendaciones de buenas prácticas
- **Siempre mezcla tu voz con la grabación**: usa el modo de reunión completa
  (`-m --mic <id>`) en lugar de grabar solo BlackHole, para que tu voz quede
  registrada y no dependas del "agregado" virtual.
- **Preferible la mezcla en código (`-m`) antes que "agregados" de Audio MIDI**:
  los agregados con BlackHole son frágiles y suelen dejar de capturar el sistema.
- **Fija la sesión/duración** con `-t` para no grabar de más y ahorrar espacio:
  las grabaciones WAV de reuniones de 1 hora ocupan ~330 MB a 48 kHz.
- **Verifica niveles al terminar**: el comando imprime RMS/pico por canal. Si el canal
  que esperabas suena plano (RMS muy bajo o 0), el audio real no llegó a esta entrada.
- **Mantén BlackHole y los dispositivos a 48 kHz** tras cualquier agregado o actualización
  del sistema operativo; macOS suele revertir estas configuraciones.

### Alternativas si no puedes usar BlackHole
- **Soundflower** (más viejo, requiere que firmes/instales con precaución en versiones nuevas de macOS).
- **Loopback** (de pago, de Rogue Amoeba, con interfaz gráfica).
- **Grabar solo tu voz** (mic físico) y pegar el audio de la reunión aparte, luego concatener
  antes de transcribir.

### Si la reunión es importante, haz una prueba rápida
Antes de una reunión clave, graba 10 s y verifica:
```bash
python -m notekeeper rec -m --mic 5 -t 10
python -m notekeeper show
```
Si la transcripción tiene sentido y ambos canales tienen señal, ya estás listo.

---

## Grabar

```bash
python -m notekeeper rec                  # Grabar con settings por defecto
python -m notekeeper rec -l               # Listar dispositivos de audio
python -m notekeeper rec -d 10            # Solo audio del sistema (BlackHole)
python -m notekeeper rec -m               # Reunión completa: mic + sistema mezclados
python -m notekeeper rec -m --mic 5       # Elegir el micrófono de la mezcla
python -m notekeeper rec -t 60            # Grabar 60 segundos
python -m notekeeper rec -o reunion       # Guardar en sesión "reunion"
```

Al terminar imprime los niveles por canal. Si está en silencio, revísalo en
[Solución de problemas](#solución-de-problemas).

---

## Transcribir

```bash
python -m notekeeper transcript                  # Transcribir todos los pendientes
python -m notekeeper transcript -s 2025-08-26    # Transcribir sesión específica
```

Usa faster-whisper (`WHISPER_MODEL`, por defecto `large-v3`). Detecta idioma
automáticamente y guarda `transcript.txt` + `segments.json` (con timestamps).

---

## Consultar y buscar

```bash
python -m notekeeper list                                      # Listar grabaciones
python -m notekeeper show                                      # Mostrar la más reciente
python -m notekeeper show 2025-08-26                           # Sesión específica
python -m notekeeper search "tareas pendientes"                # Buscar texto
python -m notekeeper search "staging" -n 10                    # Más resultados

# Chat con IA sobre tus transcripciones (RAG + LLM)
# Consulta las últimas 10 reuniones, indexadas por fecha
python -m notekeeper skill "qué tareas quedaron pendientes"
python -m notekeeper skill "qué se decidió sobre staging"
python -m notekeeper skill "quién quedó a cargo del backup"
python -m notekeeper skill -n 5 "tu pregunta"     # solo las últimas 5 reuniones
```

Requiere `LLM_API_KEY` en `.env` (OpenRouter: https://openrouter.ai/keys).
Sin key, `skill` devuelve el contexto relevante pero sin respuesta de IA.

---

## Resumen + tareas Jira

```bash
python -m notekeeper jira                  # Últimas 10 reuniones transcritas
python -m notekeeper jira -n 3             # Especificar cuántas reuniones
python -m notekeeper jira 2026-08-27       # Una sesión específica
```

Genera en la carpeta de la sesión más reciente:

- `meeting_summary.txt` — resumen de actividades y decisiones
- `tasks.json` — lista estructurada de tareas
- `jira_tasks.csv` — **importable a Jira** (Issue → Import issues from CSV)

Cada tarea incluye: **title**, **description** (con criterio de aceptación),
**issue_type** (Task/Story/Bug), **priority** (High/Medium/Low),
**story_points** (1/2/3/5/8 = tamaño), **eta** (AAAA-MM-DD), **assignee** y
**session** (la reunión de origen, para agrupar por fecha).

---

## Configuración (.env)

Crea `.env` (ya está en `.gitignore`):

```env
# Transcripción
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=int8

# LLM via OpenRouter (para skill y jira)
LLM_MODEL=anthropic/claude-sonnet-4
LLM_API_KEY=sk-or-tu-key-aqui
LLM_BASE_URL=https://openrouter.ai/api/v1

# Datos
NOTEKEEPER_DATA=recordings

# Captura de audio (opcional)
NOTEKEEPER_SYSTEM_DEVICE=BlackHole 2ch
NOTEKEEPER_MIC_DEVICE=
```

> **Seguridad de credenciales:** `.env` está en `.gitignore` y no se sube al repositorio.
> El código **nunca** debe contener API keys, tokens ni secretos hardcodeados; todas las
> credenciales se leen desde variables de entorno (`.env`). Si modificas el código, no
> agregues claves en los archivos fuente: agrega la variable en `.env.example` (con un
> valor de ejemplo) y usa `os.getenv()` para leerla. Si alguna vez se filtra una key a git,
> revócala de inmediato en OpenRouter y rota la variable.

---

## Estructura de datos

```
recordings/
├── 2025-08-26_14-30-00/
│   ├── recording.wav        # audio capturado
│   ├── transcript.txt       # transcripción completa
│   ├── segments.json        # segmentos con timestamps
│   ├── metadata.json        # fecha, duración, fuente, etc.
│   ├── meeting_summary.txt  # resumen (cmd jira)
│   ├── tasks.json           # tareas Jira (cmd jira)
│   └── jira_tasks.csv       # importable a Jira (cmd jira)
```

---

## Solución de problemas

| Síntoma | Causa / Solución |
|---|---|
| Grabas pero **no capturas el audio de la reunión** | La app debe emitir por la **multi-salida "notekeeper out"**, no por sus Bocinas/Auris propios. |
| Grabas tu voz pero **no el sistema** | Estás grabando del mic físico. Usa `-d 10` (BlackHole) o `-m` (mezcla). |
| Tos los computadores en silencio | Revisa en Audio MIDI Setup que **todos** los dispositivos estén a **48 kHz** (bloc de auto favorito de los problemas de BlackHole). |
| El agregado **"notekeeper in"** no captura el sistema | Los agregados con BlackHole son frágiles. Usa `-m` (mezcla en código) que no depende de él. |
| `skill` / `jira` dicen "No hay LLM_API_KEY" | Pega tu key en `.env`. |
| La transcripción tarda mucho en CPU | Baja a `WHISPER_MODEL=small` o `base` en `.env`. |