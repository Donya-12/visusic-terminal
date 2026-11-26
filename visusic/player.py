"""Low-latency audio playback with access to the heard samples.

Audio is decoded up front and streamed through sounddevice.  The spectrum is
computed from the same buffer that the sound card is playing, so visuals and
lyrics track the audio instead of a wall clock.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from .library import Track


class AudioError(RuntimeError):
    pass


def _to_stereo(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        data = data[:, None]
    channels = data.shape[1]
    if channels == 1:
        return np.repeat(data, 2, axis=1)
    if channels > 2:
        return data[:, :2].copy()
    return data


def ffmpeg_exe() -> str | None:
    """Path to a usable FFmpeg binary (bundled or on PATH)."""
    override = os.environ.get("VISUSIC_FFMPEG")
    if override and Path(override).is_file():
        return override
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def decode_with_ffmpeg(path: Path, samplerate: int) -> np.ndarray:
    """Decode any FFmpeg-supported file to float32 stereo at samplerate."""
    executable = ffmpeg_exe()
    if not executable:
        raise AudioError(
            "FFmpeg is not available; install imageio-ffmpeg or put ffmpeg.exe on PATH"
        )
    command = [
        executable, "-v", "error", "-i", str(path), "-vn", "-map", "a:0",
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2",
        "-ar", str(samplerate), "-",
    ]
    try:
        process = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
    except OSError as exc:
        raise AudioError(f"Could not start FFmpeg: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", "replace").strip().splitlines()
        message = detail[-1] if detail else f"exit code {process.returncode}"
        raise AudioError(f"FFmpeg could not decode {path.name}: {message}")
    raw = process.stdout
    if not raw:
        raise AudioError(f"{path.name} contains no audio")
    data = np.frombuffer(raw, dtype="<f4")
    if data.size % 2:
        data = data[:-1]
    return data.reshape(-1, 2)


def resample_linear(data: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Chunked linear resampling; enough for playback and cheap on memory."""
    if source_rate == target_rate or len(data) == 0:
        return data

    ratio = source_rate / target_rate
    frames = max(1, int(round(len(data) * target_rate / source_rate)))
    result = np.empty((frames, data.shape[1]), dtype=np.float32)
    last = len(data) - 1
    chunk = 1 << 20

    for start in range(0, frames, chunk):
        stop = min(frames, start + chunk)
        positions = np.arange(start, stop, dtype=np.float64) * ratio
        low = positions.astype(np.int64)
        np.clip(low, 0, last, out=low)
        high = np.minimum(low + 1, last)
        fraction = (positions - low).astype(np.float32)[:, None]
        result[start:stop] = data[low] * (1.0 - fraction) + data[high] * fraction

    return result


class Player:
    def __init__(self, volume: float = 0.75) -> None:
        self._lock = threading.Lock()
        self._samples: np.ndarray | None = None
        self._cursor = 0
        self._volume = float(np.clip(volume, 0.0, 1.0))
        self._playing = False
        self._finished = False
        self._latency = 0.0
        self.sr = 0
        self.duration = 0.0
        self.stream: sd.OutputStream | None = None
        self.overruns = 0
        self._open_stream()

    # ------------------------------------------------------------------ audio
    def _open_stream(self) -> None:
        errors: list[str] = []
        candidates: list[int | None] = [None]

        try:
            hostapis = sd.query_hostapis()
            for index, api in enumerate(hostapis):
                if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
                    candidates.insert(0, int(api["default_output_device"]))
                    break
        except Exception:
            pass

        rates: list[int] = [48000, 44100]
        for device in candidates:
            try:
                info = sd.query_devices(device if device is not None else None,
                                        kind="output")
                rates.insert(0, int(info["default_samplerate"]))
            except Exception:
                pass
            tried: set[int] = set()
            for rate in rates:
                if rate in tried:
                    continue
                tried.add(rate)
                stream = None
                try:
                    stream = sd.OutputStream(
                        device=device,
                        samplerate=rate,
                        channels=2,
                        dtype="float32",
                        blocksize=1024,
                        latency="low",
                        callback=self._callback,
                    )
                    stream.start()
                except Exception as exc:  # PortAudio errors are not one class
                    errors.append(f"device={device} {rate} Hz: {exc}")
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
                    continue

                self.stream = stream
                self.sr = rate
                latency = stream.latency
                if isinstance(latency, (tuple, list)):
                    latency = latency[-1]
                self._latency = float(latency or 0.0)
                return

        detail = "\n  ".join(errors[-4:]) if errors else "no output device"
        raise AudioError(f"Could not open an audio output.\n  {detail}")

    def _callback(self, outdata, frames, _time, status) -> None:
        if status:
            self.overruns += 1
        outdata.fill(0.0)
        with self._lock:
            if not self._playing or self._samples is None or self._finished:
                return
            start = self._cursor
            end = min(start + frames, len(self._samples))
            count = end - start
            if count > 0:
                np.multiply(self._samples[start:end], self._volume,
                            out=outdata[:count])
            self._cursor = end
            if end >= len(self._samples):
                self._finished = True

    # ------------------------------------------------------------- transport
    def load(self, track: Track, autoplay: bool = True) -> float:
        with self._lock:
            self._playing = False

        path = Path(track.path)
        rate = self.sr
        try:
            data, rate = sf.read(path, dtype="float32", always_2d=True)
        except Exception as soundfile_error:
            try:
                data = decode_with_ffmpeg(path, self.sr)
            except AudioError as ffmpeg_error:
                raise AudioError(
                    f"Could not decode {path.name}: {soundfile_error}; "
                    f"{ffmpeg_error}"
                ) from ffmpeg_error

        if data.size == 0:
            raise AudioError(f"{path.name} contains no audio")

        data = _to_stereo(data)
        data = resample_linear(data, rate, self.sr)
        data = np.ascontiguousarray(data, dtype=np.float32)

        with self._lock:
            self._samples = data
            self._cursor = 0
            self._finished = False
            self.duration = len(data) / float(self.sr)
            self._playing = autoplay and self.stream is not None
        return self.duration

    def play(self) -> None:
        with self._lock:
            if self._samples is None:
                return
            if self._finished:
                self._cursor = 0
                self._finished = False
            self._playing = True

    def pause(self) -> None:
        with self._lock:
            self._playing = False

    def toggle(self) -> None:
        with self._lock:
            if self._samples is None:
                return
            if not self._playing and self._finished:
                self._cursor = 0
                self._finished = False
            self._playing = not self._playing

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._playing

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    def seek(self, seconds: float) -> None:
        with self._lock:
            if self._samples is None:
                return
            seconds = float(np.clip(seconds, 0.0, self.duration))
            self._cursor = int(seconds * self.sr)
            self._finished = self._cursor >= len(self._samples)

    def seek_by(self, delta: float) -> None:
        self.seek(self.position() + delta)

    def position(self) -> float:
        with self._lock:
            cursor = self._cursor
            finished = self._finished
            latency = self._latency
        if self.duration <= 0:
            return 0.0
        if finished:
            return self.duration
        heard = cursor / self.sr - latency
        return float(np.clip(heard, 0.0, self.duration))

    # ---------------------------------------------------------------- volume
    @property
    def volume(self) -> float:
        with self._lock:
            return self._volume

    def set_volume(self, value: float) -> float:
        with self._lock:
            self._volume = float(np.clip(value, 0.0, 1.0))
            return self._volume

    # -------------------------------------------------------------- analysis
    def analysis_window(self, size: int = 4096) -> np.ndarray:
        with self._lock:
            samples = self._samples
            cursor = self._cursor
            latency = self._latency
        if samples is None:
            return np.zeros(size, dtype=np.float32)

        heard = int(cursor - latency * self.sr)
        heard = max(0, min(heard, len(samples)))
        start = max(0, heard - size)
        segment = samples[start:heard]
        if len(segment) < 2:
            return np.zeros(size, dtype=np.float32)
        return segment.mean(axis=1).astype(np.float32, copy=False)

    # --------------------------------------------------------------- cleanup
    def close(self) -> None:
        self._playing = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
