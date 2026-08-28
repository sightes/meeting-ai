# Changelog

Todos los cambios notables de **notekeeper** se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/),
y este proyecto se adhiere a [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Exportación a macOS Notas y Recordatorios** (`export-mac`): crea una nota en Apple
  Notes con el resumen de la reunión y un recordatorio por tarea (título, prioridad,
  fecha de vencimiento). Soporta `--dry-run` y filtro por sesión/`--tag`.
- **Resumen más explícito**: el resumen ahora incluye secciones opcionales de
  DECISIONES, ACUERDOS, PENDIENTES/PRÓXIMOS PASOS y BLOQUEANTES (cuando el LLM
  detecta contenido real), además de las viñetas generales.

## [0.3.0] - 2026-08-28

### Added
- **Exportación a GitHub Projects v2** (`notekeeper jira`): crea issues, los agrega a
  un panel de proyecto y rellena campos Status/Priority/Size/Estimate/fechas con labels
  por contexto. Deduplica contra issues existentes vía LLM. Incluye `backfill` para
  rellenar campos de tareas ya en el panel y `describe-fields` para documentar columnas.
- **Resúmenes Markdown** (`./resume` / `notekeeper resume`): genera
  `summaries/[tag][fecha][tema].md` por reunión y sincroniza los resúmenes al repo de
  proyectos (`project-tracking`) con commit+push automático.

## [0.2.0] - 2026-08-28

### Added
- **Chat interactivo en consola** (`./ask` / `notekeeper chat`): sesión de preguntas
  continua sobre las transcripciones, con memoria de conversación y salida coloreada
  (tipo opencode). Soporta filtro por contexto y búsqueda semántica (`-e`).
- **Segmentación de la base de conocimiento por contextos (tags)**: cada sesión puede
  llevar uno o varios tags (empresa/proyecto) guardados en `metadata.json`.
  - Asignar al grabar: `./grabar --tags scotiabank`.
  - Etiquetar/re-etiquetar sesiones: `notekeeper tag <sesión> <tag> [--all|--from-tag]`.
  - Filtrar consultas con `--tag`/`--tags` en `skill`, `search`, `jira`, `chat`, `list`,
    `transcript`, `diarize` y `show`.
- `notekeeper jira --tags <ctx>` y filtrado por contexto en embeddings (búsqueda semántica).

### Fixed
- **Bug de shell**: el prefijo `#tag` no funcionaba como argumento (bash interpreta `#`
  precedido de espacio como comentario). Se sustituyó por el flag `--tag`/`--tags`, y el
  modo chat acepta el contexto sin `#`: `./ask scotiabank`.

## [0.1.0] - 2026-08-27

### Added
- Grabación de reuniones desde micrófono y/o audio del sistema (`rec`).
- Transcripción con Whisper/Faster-Whisper (`transcript`).
- Diarización de hablantes con pyannote (`diarize`).
- Búsqueda de texto en transcripciones (`search`).
- Búsqueda semántica por embeddings (local u OpenRouter) (`embed-index`, `skill -s`).
- Consultas con IA (RAG) sobre las reuniones (`skill`).
- Resumen + tareas Jira (`jira`): genera `meeting_summary.txt`, `tasks.json`
  y `jira_tasks.csv` importable a Jira.

[Unreleased]: https://github.com/sightes/meeting-ai/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/sightes/meeting-ai/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/sightes/meeting-ai/releases/tag/v0.2.0
[0.1.0]: https://github.com/sightes/meeting-ai/releases/tag/v0.1.0
