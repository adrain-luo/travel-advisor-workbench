"""Bounded offline WXGF preview decoding using the pinned bundled FFmpeg.

No client, process-memory, filesystem search, package download or network access.
Reference: 334456777/WeFlow 799e440d1bcc8e813cb4402f220c1570839a78cb,
crates/weflow-core/src/image.rs:384-600. Package resolver audit:
imageio/imageio-ffmpeg ae47d8028c237ca5507ceef1b843ee427b442887.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import warnings

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SECONDS = 15.0
PACKAGE_VERSION = "0.6.0"
BINARY_NAME = "ffmpeg-win-x86_64-v7.1.exe"


class CodecError(RuntimeError):
    """Fixed code only; decoder stderr and source data never become logs."""


def _resolve_binary(explicit_path=None):
    """Resolve only the pinned wheel binary, without import-time helper probes.

    imageio_ffmpeg.get_ffmpeg_exe may prefer an environment override and invoke
    unbounded version probes; do not use its conda/system/environment fallback.
    """
    if os.name != "nt" or sys.maxsize <= 2**32:
        raise CodecError("WXGF_DECODER_PLATFORM_UNSUPPORTED")
    try:
        distribution = importlib.metadata.distribution("imageio-ffmpeg")
        if distribution.version != PACKAGE_VERSION:
            raise CodecError("WXGF_DECODER_VERSION_MISMATCH")
        package = Path(distribution.locate_file("imageio_ffmpeg/binaries")).resolve(strict=True)
        expected = (package / BINARY_NAME).resolve(strict=True)
        if not expected.is_file() or not expected.is_relative_to(package):
            raise CodecError("WXGF_DECODER_PATH_INVALID")
        if explicit_path is not None:
            given = Path(explicit_path)
            if not given.is_absolute() or given.resolve() != expected:
                raise CodecError("WXGF_DECODER_PATH_INVALID")
        return expected
    except CodecError:
        raise
    except (importlib.metadata.PackageNotFoundError, FileNotFoundError):
        raise CodecError("WXGF_DECODER_MISSING") from None
    except (OSError, ValueError, TypeError):
        raise CodecError("WXGF_DECODER_PATH_INVALID") from None


def _hevc_candidates(data):
    starts = [(match.start(), match.end()) for match in re.finditer(rb"\x00\x00(?:\x00)?\x01", data[4:])]
    if len(starts) > 4096:
        raise CodecError("WXGF_NAL_LIMIT")
    units = []
    for index, (_, begin) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(data) - 4
        unit = data[begin + 4:end + 4]
        if len(unit) >= 2 and not unit[0] & 0x80 and unit[1] & 7:
            units.append(unit)
    vps = [index for index, unit in enumerate(units) if (unit[0] >> 1) & 63 == 32]
    groups = []
    for index, start in enumerate(vps):
        end = vps[index + 1] if index + 1 < len(vps) else len(units)
        group = units[start:end]
        types = {(unit[0] >> 1) & 63 for unit in group}
        if {32, 33, 34} <= types and any(kind < 32 for kind in types):
            groups.append(b"".join(b"\x00\x00\x00\x01" + unit for unit in group))
    groups.sort(key=len, reverse=True)
    if not groups:
        raise CodecError("WXGF_HEVC_STREAM_UNSUPPORTED")
    return groups[:3]


def _png_info(data):
    from PIL import Image
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > MAX_OUTPUT_BYTES:
        raise CodecError("WXGF_DECODER_OUTPUT_INVALID")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if image.format != "PNG" or width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                    raise CodecError("WXGF_DECODER_DIMENSIONS_REJECTED")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        return {"width": width, "height": height, "mime": "image/png"}
    except CodecError:
        raise
    except Exception:
        raise CodecError("WXGF_DECODER_OUTPUT_INVALID") from None


def _embedded_png(data):
    """Validate an embedded still image from the same container, then emit PNG."""
    from PIL import Image
    limit = min(4096, len(data) - 12)
    starts = [position for magic in (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
              if (position := data.find(magic, 4, limit)) >= 0]
    for position in sorted(starts):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data[position:])) as image:
                    width, height = image.size
                    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                        continue
                    image.load()
                    output = io.BytesIO()
                    image.convert("RGBA" if "A" in image.getbands() else "RGB").save(output, format="PNG")
            png = output.getvalue()
            _png_info(png)
            return png
        except Exception:
            continue
    return None


def _run_ffmpeg(executable, hevc, timeout):
    """One owned process, bounded pipe output and timeout; never echo stderr."""
    if timeout <= 0:
        raise CodecError("WXGF_DECODER_TIMEOUT")
    command = [str(executable), "-hide_banner", "-loglevel", "error", "-nostdin",
               "-max_alloc", str(MAX_OUTPUT_BYTES), "-protocol_whitelist", "pipe",
               "-threads", "1", "-max_pixels", str(MAX_PIXELS), "-f", "hevc", "-i", "pipe:0",
               "-an", "-sn", "-dn", "-frames:v", "1", "-threads", "1", "-c:v", "png",
               "-f", "image2pipe", "pipe:1"]
    environment = {key: value for key, value in os.environ.items() if key not in {"FFREPORT", "IMAGEIO_FFMPEG_EXE"}}
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=environment, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        raise CodecError("WXGF_DECODER_START_FAILED") from None
    output, failure = bytearray(), []

    def receive():
        try:
            while True:
                block = process.stdout.read(65536)
                if not block:
                    break
                if len(output) + len(block) > MAX_OUTPUT_BYTES:
                    failure.append("WXGF_DECODER_OUTPUT_LIMIT")
                    process.kill()
                    break
                output.extend(block)
        except OSError:
            failure.append("WXGF_DECODER_PIPE_FAILED")

    def feed():
        try:
            for start in range(0, len(hevc), 65536):
                process.stdin.write(hevc[start:start + 65536])
            process.stdin.close()
        except (OSError, BrokenPipeError):
            pass

    receiver = threading.Thread(target=receive, daemon=True)
    sender = threading.Thread(target=feed, daemon=True)
    receiver.start(); sender.start()
    try:
        try:
            return_code = process.wait(timeout=min(timeout, MAX_SECONDS))
        except subprocess.TimeoutExpired:
            raise CodecError("WXGF_DECODER_TIMEOUT") from None
        receiver.join(timeout=1)
        sender.join(timeout=1)
        if receiver.is_alive() or sender.is_alive():
            raise CodecError("WXGF_DECODER_PIPE_FAILED")
        if failure:
            raise CodecError(failure[0])
        if return_code != 0 or not output:
            raise CodecError("WXGF_DECODER_FAILED")
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (process.stdin, process.stdout):
            try:
                pipe.close()
            except OSError:
                pass
        receiver.join(timeout=1); sender.join(timeout=1)


def convert_wxgf_to_png(data, *, ffmpeg_path=None):
    """Convert one attributed container to a preview; preserve source hash/size."""
    if not isinstance(data, bytes) or not 20 <= len(data) <= MAX_INPUT_BYTES or data[:4] != b"wxgf":
        raise CodecError("WXGF_CONTAINER_INVALID")
    started = time.monotonic()
    # Validate an explicit binary request even when an embedded image is usable.
    executable = _resolve_binary(ffmpeg_path) if ffmpeg_path is not None else None
    source = {"native_source_sha256": hashlib.sha256(data).hexdigest(),
              "native_source_bytes": len(data), "native_source_format": "wxgf",
              "quality": "unknown_cached_transcoded"}
    png = _embedded_png(data)
    if png is not None:
        return png, {**source, **_png_info(png), "decode_method": "WXGF_embedded_to_PNG"}
    streams = _hevc_candidates(data)
    executable = executable or _resolve_binary()
    last_error = "WXGF_DECODER_FAILED"
    for stream in streams:
        remaining = MAX_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise CodecError("WXGF_DECODER_TIMEOUT")
        try:
            png = _run_ffmpeg(executable, stream, remaining)
            return png, {**source, **_png_info(png), "decode_method": "WXGF_HEVC_FFmpeg_to_PNG"}
        except CodecError as error:
            last_error = str(error)
            if last_error in {"WXGF_DECODER_TIMEOUT", "WXGF_DECODER_OUTPUT_LIMIT", "WXGF_DECODER_START_FAILED"}:
                break
    raise CodecError(last_error)
