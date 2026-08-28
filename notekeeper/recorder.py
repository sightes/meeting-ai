"""Grabación de audio desde micrófono y/o audio de sistema."""
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from notekeeper.config import DATA_DIR, NOTEKEEPER_MIC_DEVICE, NOTEKEEPER_SYSTEM_DEVICE
from notekeeper.storage import create_session, save_metadata


def list_devices():
    print("Dispositivos de audio disponibles:\n")
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        kind = "IN " if d["max_input_channels"] > 0 else "   "
        marker = " <-- default" if i == sd.default.device[0] else ""
        print(f"  [{i:2d}] {kind} {d['name']}{marker}")
    print()


def _resolve_device(device: str | int | None) -> int | None:
    if device is None:
        return None
    try:
        return int(device)
    except (TypeError, ValueError):
        pass
    devices = sd.query_devices()
    name = str(device).lower()
    matches = [i for i, d in enumerate(devices) if name in d["name"].lower()]
    if not matches:
        raise SystemExit(f"Dispositivo '{device}' no encontrado.")
    if len(matches) > 1:
        options = ", ".join(f"[{i}] {devices[i]['name']}" for i in matches)
        raise SystemExit(f"'{device}' es ambiguo ({options}). Sé más específico.")
    return matches[0]


def _resolve_input(device) -> int:
    if device is None:
        return sd.query_devices(kind="input")["index"]
    return _resolve_device(device)


def _reporter(stop: threading.Event):
    start = time.monotonic()
    while not stop.wait(5):
        print(f"  {int(time.monotonic() - start)}s grabados", flush=True)


def _capture_streams(streams: list[tuple[str, int, int, int]], duration: int | None) -> dict:
    """Captura varios dispositivos en paralelo.

    streams: lista de (label, device_index, samplerate, channels).
    Devuelve {label: ndarray shape (n, channels)}.
    """
    buffers = {label: [] for label, *_ in streams}
    stop = threading.Event()

    def worker(label: str, device: int, sr: int, channels: int):
        def callback(indata, frames, time_info, status):
            buffers[label].append(indata.copy())

        if duration:
            buffers[label].append(
                sd.rec(
                    frames=int(duration * sr),
                    samplerate=sr,
                    channels=channels,
                    dtype="float32",
                    device=device,
                    blocking=True,
                )
            )
            return

        with sd.InputStream(
            samplerate=sr, channels=channels, dtype="float32", device=device, callback=callback
        ):
            while not stop.is_set():
                stop.wait(5)

    threads = [
        threading.Thread(target=worker, args=(label, device, sr, ch), name=label, daemon=True)
        for label, device, sr, ch in streams
    ]

    for t in threads:
        t.start()

    if not duration:
        threading.Thread(target=_reporter, args=(stop,), daemon=True).start()
        try:
            input("\nPresiona Enter para detener...\n")
        except (KeyboardInterrupt, EOFError):
            pass
        stop.set()

    for t in threads:
        t.join()

    result = {}
    for label, _, _, ch in streams:
        parts = buffers[label]
        result[label] = (
            np.concatenate(parts, axis=0) if parts else np.empty((0, ch), dtype="float32")
        )
    return result


def _to_mono(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        return data
    if data.shape[1] == 1:
        return data[:, 0]
    return data.mean(axis=1).astype("float32")


def _mix(system: np.ndarray, mic: np.ndarray) -> np.ndarray:
    s, m = _to_mono(system), _to_mono(mic)
    n = min(len(s), len(m))
    if n == 0:
        return np.empty((0,), dtype="float32")
    return (0.5 * m[:n] + 0.5 * s[:n]).astype("float32")


def _channel_report(data: np.ndarray) -> float:
    print("\nNiveles por canal:")
    if data.shape[0] == 0:
        print("  Sin muestras capturadas.")
        return 0.0
    total_peak = 0.0
    for c in range(data.shape[1]):
        rms = 20 * np.log10(np.sqrt(np.mean(data[:, c] ** 2)) + 1e-12)
        peak = 20 * np.log10(np.max(np.abs(data[:, c])) + 1e-12)
        total_peak = max(total_peak, float(np.max(np.abs(data[:, c]))))
        print(f"  Canal {c}: RMS {rms:6.1f} dBFS | Peak {peak:6.1f} dBFS")
    return total_peak


def _save(session_dir: Path, data: np.ndarray, sr: int, extra_meta: dict, tags: list[str] | None = None):
    filepath = session_dir / "recording.wav"
    sf.write(str(filepath), data, sr)
    save_metadata(session_dir, {
        "recorded_at": datetime.now().isoformat(),
        "duration": round(len(data) / sr, 2),
        "sample_rate": sr,
        "channels": 1 if data.ndim == 1 else data.shape[1],
        "filename": "recording.wav",
        "tags": [str(t).strip().lower() for t in (tags or []) if str(t).strip()],
        **extra_meta,
    })
    print(f"\nGuardado: {filepath}")
    print(f"Duración: {len(data) / sr:.1f}s")
    print(f"Sesión: {session_dir.name}")
    return filepath


def _session_dir(output: str | None) -> Path:
    if output:
        session = DATA_DIR / output
        session.mkdir(parents=True, exist_ok=True)
    else:
        session = create_session(datetime.now())
    return session


def _record_single(device, duration, output, tags=None):
    index = _resolve_input(device)
    info = sd.query_devices(index)
    sr = int(info["default_samplerate"])
    channels = info["max_input_channels"]

    print(f"Grabando desde '{info['name']}': {channels} canal(es) @ {sr}Hz")
    print("Formato: WAV")
    if duration:
        print(f"Duración: {duration}s")
    if tags:
        print(f"Tags/contexto: {', '.join(tags)}")

    recording = _capture_streams([("rec", index, sr, channels)], duration)["rec"]

    if recording.shape[0] == 0:
        print("\nNo se capturaron muestras; no se guardó archivo.")
        return None

    if _channel_report(recording) < 0.001:
        print("\nADVERTENCIA: grabación en silencio.")
        print("Revisa la ruta del audio: la app que reproduce debe mandar salida")
        print("al multi-salida (notekeeper out) para que BlackHole reciba el sonido.")

    return _save(_session_dir(output), recording, sr, {"source": info["name"]}, tags=tags)


def _record_mixed(device, mic, duration, output, tags=None):
    system_idx = _resolve_input(device) if device is not None else _resolve_device(NOTEKEEPER_SYSTEM_DEVICE)
    if mic is True:
        mic = NOTEKEEPER_MIC_DEVICE or None
    mic_idx = _resolve_input(mic)

    info_sys = sd.query_devices(system_idx)
    info_mic = sd.query_devices(mic_idx)
    sr = max(int(info_sys["default_samplerate"]), int(info_mic["default_samplerate"]))

    spec = [
        ("system", system_idx, sr, min(2, info_sys["max_input_channels"]) or 1),
        ("mic", mic_idx, sr, min(2, info_mic["max_input_channels"]) or 1),
    ]

    print(f"Grabando MIX de reunión:")
    print(f"  Sistema   : '{info_sys['name']}' ({spec[0][3]} ch)")
    print(f"  Micrófono : '{info_mic['name']}' ({spec[1][3]} ch)")
    print(f"  Formato   : mono @ {sr}Hz")
    if tags:
        print(f"  Tags/contexto: {', '.join(tags)}")
    if duration:
        print(f"Duración: {duration}s")

    data = _capture_streams(spec, duration)
    mixed = _mix(data["system"], data["mic"])

    if mixed.size == 0:
        print("\nNo se capturaron muestras; no se guardó archivo.")
        return None

    if _channel_report(mixed.reshape(-1, 1)) < 0.001:
        print("\nADVERTENCIA: grabación en silencio.")
        print("Revisa que la app de la reunión mande su audio a 'notekeeper out'")
        print(f"(o que '{info_sys['name']}' reciba el sistema).")

    return _save(_session_dir(output), mixed, sr, {
        "source": "mic+system",
        "system_device": info_sys["name"],
        "mic_device": info_mic["name"],
    }, tags=tags)


def record(device=None, duration=None, output=None, mic=None, tags=None):
    list_devices()

    if mic is not None:
        return _record_mixed(device, mic, duration, output, tags=tags)
    return _record_single(device, duration, output, tags=tags)


def list_recordings(sessions: list | None = None):
    from notekeeper.storage import list_sessions, get_audio_path, load_metadata, get_tags

    if sessions is None:
        sessions = list_sessions()
    if not sessions:
        print("No hay grabaciones.")
        return

    print(f"{'Sesión':<25} {'Audio':<15} {'Duración':<10} {'Tags':<20} {'Transcrito'}")
    print("-" * 80)

    for s in sessions:
        audio = get_audio_path(s)
        meta = load_metadata(s)
        has_transcript = (s / "transcript.txt").exists()
        duration = meta.get("duration", "")
        dur_str = f"{duration:.0f}s" if isinstance(duration, (int, float)) else ""
        audio_str = audio.suffix if audio else ""
        tags = ",".join(sorted(get_tags(s)))
        status = "✓" if has_transcript else "—"
        print(f"  {s.name:<23} {audio_str:<15} {dur_str:<10} {tags:<20} {status}")