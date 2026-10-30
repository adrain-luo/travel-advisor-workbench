"""Offline public synthetic codec fixtures; never consume private chat data."""
import hashlib
import io
from pathlib import Path
import subprocess

import pytest
from PIL import Image

from backend.background import codec


def png():
    result = io.BytesIO()
    Image.new("RGB", (32, 24), (0, 0, 230)).save(result, format="PNG")
    return result.getvalue()


def synthetic_container():
    return b"wxgf" + b"\0" * 16 + b"".join(b"\0\0\0\1" + bytes([kind << 1, 1]) + b"synthetic" * 15 for kind in (32, 33, 34, 19))


def test_wxgf_nal_conversion_uses_bound_decoder_and_records_source(monkeypatch):
    original, preview = synthetic_container(), png()
    monkeypatch.setattr(codec, "_resolve_binary", lambda path=None: Path("trusted-package-ffmpeg.exe"))
    called = []
    def run(executable, data, timeout):
        called.append((executable, data, timeout))
        assert data.startswith(b"\0\0\0\1\x40\x01")
        assert 0 < timeout <= 15
        return preview
    monkeypatch.setattr(codec, "_run_ffmpeg", run)
    result, info = codec.convert_wxgf_to_png(original)
    assert result == preview and len(called) == 1
    assert info["quality"] == "unknown_cached_transcoded"
    assert info["native_source_sha256"] == hashlib.sha256(original).hexdigest()
    assert info["native_source_bytes"] == len(original)
    assert (info["width"], info["height"]) == (32, 24)


def test_embedded_image_decodes_without_binary_or_network(monkeypatch):
    def forbidden(*args):
        pytest.fail("embedded image should not start an external decoder")
    monkeypatch.setattr(codec, "_resolve_binary", forbidden)
    result, info = codec.convert_wxgf_to_png(b"wxgf" + b"\0" * 20 + png())
    assert result.startswith(b"\x89PNG")
    assert info["decode_method"] == "WXGF_embedded_to_PNG"


def test_malformed_wxgf_rejected_before_decoder_lookup(monkeypatch):
    def forbidden(*args):
        pytest.fail("invalid stream should not resolve or run a decoder")
    monkeypatch.setattr(codec, "_resolve_binary", forbidden)
    with pytest.raises(codec.CodecError, match="WXGF_CONTAINER_INVALID"):
        codec.convert_wxgf_to_png(b"wxgf")
    with pytest.raises(codec.CodecError, match="WXGF_HEVC_STREAM_UNSUPPORTED"):
        codec.convert_wxgf_to_png(b"wxgf" + b"\0" * 40)


def test_only_pinned_distribution_binary_path_is_accepted(tmp_path, monkeypatch):
    folder = tmp_path / "imageio_ffmpeg" / "binaries"
    folder.mkdir(parents=True)
    expected = folder / codec.BINARY_NAME
    expected.write_bytes(b"MZsynthetic-not-executed")
    class Distribution:
        version = "0.6.0"
        def locate_file(self, name):
            return tmp_path / name
    monkeypatch.setattr(codec.importlib.metadata, "distribution", lambda name: Distribution())
    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", "untrusted-system-override.exe")
    assert codec._resolve_binary() == expected
    assert codec._resolve_binary(expected) == expected
    with pytest.raises(codec.CodecError, match="WXGF_DECODER_PATH_INVALID"):
        codec._resolve_binary("relative.exe")
    with pytest.raises(codec.CodecError, match="WXGF_DECODER_PATH_INVALID"):
        codec._resolve_binary(tmp_path / "elsewhere.exe")


def test_pipe_runner_hides_stderr_limits_output_and_uses_no_source_paths(monkeypatch):
    calls = []
    class Process:
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            self.stdin, self.stdout = io.BytesIO(), io.BytesIO(b"12345")
        def kill(self):
            pass
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
    monkeypatch.setattr(codec.subprocess, "Popen", Process)
    monkeypatch.setattr(codec, "MAX_OUTPUT_BYTES", 4)
    with pytest.raises(codec.CodecError, match="WXGF_DECODER_OUTPUT_LIMIT"):
        codec._run_ffmpeg(Path("trusted.exe"), b"private-bytes", 1)
    command, options = calls[0]
    assert "pipe:0" in command and "pipe:1" in command
    assert "private-bytes" not in " ".join(command)
    assert options["stderr"] == subprocess.DEVNULL and options["shell"] is False
    assert command[command.index("-protocol_whitelist") + 1] == "pipe"


def test_decoder_failure_and_pixel_limit_are_concrete(monkeypatch):
    monkeypatch.setattr(codec, "_resolve_binary", lambda path=None: Path("trusted.exe"))
    def timeout(*args):
        raise codec.CodecError("WXGF_DECODER_TIMEOUT")
    monkeypatch.setattr(codec, "_run_ffmpeg", timeout)
    with pytest.raises(codec.CodecError, match="WXGF_DECODER_TIMEOUT"):
        codec.convert_wxgf_to_png(synthetic_container())
    monkeypatch.setattr(codec, "MAX_PIXELS", 1)
    with pytest.raises(codec.CodecError, match="WXGF_DECODER_DIMENSIONS_REJECTED"):
        codec._png_info(png())


def test_bundled_ffmpeg_synthetic_hevc_to_png():
    try:
        executable = codec._resolve_binary()
    except codec.CodecError:
        pytest.skip("pinned bundled decoder unavailable")
    command = [str(executable), "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "image2pipe", "-i", "pipe:0", "-frames:v", "1", "-pix_fmt", "yuv420p",
               "-c:v", "libx265", "-x265-params", "log-level=error:pools=1:frame-threads=1",
               "-f", "hevc", "pipe:1"]
    encoded = subprocess.run(command, input=png(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert encoded.returncode == 0 and len(encoded.stdout) < 100_000
    result, info = codec.convert_wxgf_to_png(b"wxgf" + b"\0" * 16 + encoded.stdout)
    assert info["decode_method"] == "WXGF_HEVC_FFmpeg_to_PNG"
    with Image.open(io.BytesIO(result)) as image:
        image.load()
        assert image.size == (32, 24)
