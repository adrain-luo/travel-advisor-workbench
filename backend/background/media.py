"""Fetch an explicitly attributed Moments image; no client/cache/key access.

Root alone supplies verified record URLs/attributes and executes network calls.
ISAAC-64 behavior and public test vectors:
https://github.com/334456777/WeFlow/blob/799e440d1bcc8e813cb4402f220c1570839a78cb/crates/weflow-core/src/isaac64.rs
Transport/decode reference:
https://github.com/334456777/WeFlow/blob/799e440d1bcc8e813cb4402f220c1570839a78cb/crates/weflow-core/src/services/sns.rs#L632
Token construction reference:
https://github.com/334456777/WeFlow/blob/799e440d1bcc8e813cb4402f220c1570839a78cb/crates/weflow-core/src/sns.rs#L104
No candidate package is imported. The advertised rendition is retained; /150 is
never replaced with /0. Keys/tokens/URLs are never returned or logged.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid

MASK64 = (1 << 64) - 1
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_SUFFIXES = (".qpic.cn", ".wechat.com", ".video.qq.com", ".tc.qq.com")


class MediaFailure(Exception):
    """A fixed non-secret code only."""


def _mix(v):
    a, b, c, d, e, f, g, h = v
    a = (a - e) & MASK64; f ^= h >> 9; h = (h + a) & MASK64
    b = (b - f) & MASK64; g = (g ^ (a << 9)) & MASK64; a = (a + b) & MASK64
    c = (c - g) & MASK64; h ^= b >> 23; b = (b + c) & MASK64
    d = (d - h) & MASK64; a = (a ^ (c << 15)) & MASK64; c = (c + d) & MASK64
    e = (e - a) & MASK64; b ^= d >> 14; d = (d + e) & MASK64
    f = (f - b) & MASK64; c = (c ^ (e << 20)) & MASK64; e = (e + f) & MASK64
    g = (g - c) & MASK64; d ^= f >> 17; f = (f + g) & MASK64
    h = (h - d) & MASK64; e = (e ^ (g << 14)) & MASK64; g = (g + h) & MASK64
    return [a, b, c, d, e, f, g, h]


class Isaac64:
    def __init__(self, decimal_key):
        if not isinstance(decimal_key, str) or not re.fullmatch(r"[0-9]{1,20}", decimal_key):
            raise MediaFailure("unsupported_media_key")
        seed = int(decimal_key)
        if seed > MASK64:
            raise MediaFailure("unsupported_media_key")
        self.mm, self.rs = [0] * 256, [0] * 256
        self.aa = self.bb = self.cc = self.count = 0
        self.rs[0] = seed
        values = [0x647C4677A2884B7C, 0xB9F8B322C73AC862, 0x8C0EA5053D4712A0,
                  0xB29B2E824A595524, 0x82F053DB8355E0CE, 0x48FE4A0FA5A09315,
                  0xAE985BF2CBFC89ED, 0x98F5704F6C44C0AB]
        for round_index in range(2):
            for i in range(0, 256, 8):
                source = self.rs if round_index == 0 else self.mm
                values = _mix([(values[j] + source[i + j]) & MASK64 for j in range(8)])
                self.mm[i:i + 8] = values
        self._refill()

    def _refill(self):
        self.cc = (self.cc + 1) & MASK64
        self.bb = (self.bb + self.cc) & MASK64
        for i in range(256):
            x = self.mm[i]
            if i & 3 == 0:
                self.aa = (self.aa ^ ~(self.aa << 21)) & MASK64
            elif i & 3 == 1:
                self.aa ^= self.aa >> 5
            elif i & 3 == 2:
                self.aa = (self.aa ^ (self.aa << 12)) & MASK64
            else:
                self.aa ^= self.aa >> 33
            self.aa = (self.mm[(i + 128) & 255] + self.aa) & MASK64
            y = (self.mm[(x >> 3) & 255] + self.aa + self.bb) & MASK64
            self.mm[i] = y
            self.bb = (self.mm[(y >> 11) & 255] + x) & MASK64
            self.rs[i] = self.bb
        self.count = 256

    def keystream(self, length):
        output = bytearray()
        while len(output) < length:
            if self.count == 0:
                self._refill()
            self.count -= 1
            output.extend(self.rs[self.count].to_bytes(8, "big"))
        return bytes(output[:length])


def self_test():
    """Offline public-WASM-vector tests. No files, network or private keys."""
    stream = Isaac64("2105122989").keystream(4200)
    checks = {
        "first_batch": stream[:32].hex() == "89cd4cd8f38b2190b5756244f6d7c75f9ea92584164b69b400b924e93acf563c",
        "short_seed": Isaac64("1").keystream(13).hex() == "e19ed5d2ca98af2da7a18d07ca",
        "second_batch": stream[2040:2072].hex() == "a1f2d5e4f943482900b4cc589cce41bc045143d889fad6b1172e530846d8a4e3",
        "third_batch": stream[4168:4200].hex() == "20870d6e9921d2121cd4d13ed157ed55bf8b35498cb696fdcb19d6227f3a120c",
    }
    if not all(checks.values()):
        raise MediaFailure("isaac_public_vector_failure")
    return checks


def _allowed_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname is not None
                and parsed.port in (None, 443) and not parsed.username
                and not parsed.password and not parsed.fragment
                and any(parsed.hostname.lower().endswith(suffix) for suffix in ALLOWED_SUFFIXES))
    except ValueError:
        return False


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > 3 or not _allowed_url(newurl):
            raise MediaFailure("redirect_not_allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _request_details(media):
    url = media.get("url")
    if not isinstance(url, str) or not url or len(url) > 16384:
        raise MediaFailure("advertised_url_missing")
    parsed = urllib.parse.urlsplit(url)
    upgraded = parsed.scheme == "http"
    if upgraded:
        url = urllib.parse.urlunsplit(parsed._replace(scheme="https"))
    if not _allowed_url(url):
        raise MediaFailure("advertised_url_not_allowed")
    attrs = media.get("url_attributes") or {}
    thumb_attrs = media.get("thumbnail_attributes") or {}
    if not isinstance(attrs, dict) or not isinstance(thumb_attrs, dict):
        raise MediaFailure("source_attributes_invalid")
    token = attrs.get("token") or thumb_attrs.get("token")
    key = attrs.get("key") or thumb_attrs.get("key")
    query = urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True)
    token_appended = bool(token) and not any(name == "token" for name, _ in query)
    if token_appended:
        query += [("token", str(token)), ("idx", "1")]
        parts = urllib.parse.urlsplit(url)
        url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    return url, str(key) if key is not None else None, upgraded, token_appended


def _image_info(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        fmt = image.format
        width, height = image.size
        if fmt not in {"JPEG", "PNG", "GIF", "WEBP", "BMP"}:
            raise MediaFailure("image_format_unsupported")
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise MediaFailure("image_dimensions_rejected")
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
    return {"format": fmt, "width": width, "height": height}


def retrieve_image(media, *, post_id, author_id, expected_media_index, output_dir):
    """Return a safe occurrence manifest; caller owns verified record provenance.

    media is the exact selected record's media occurrence, including original
    url/url_attributes/thumbnail_attributes. No CLI accepts secrets or URLs.
    """
    result = {"post_id": str(post_id), "author_id": str(author_id),
              "media_index": expected_media_index, "status": "FAILED",
              "quality": "unknown_CDN_rendition", "source": "verified_record_advertised_url"}
    try:
        if (not re.fullmatch(r"[0-9]+", str(post_id)) or not isinstance(author_id, str)
                or not author_id or not isinstance(expected_media_index, int)
                or expected_media_index < 0 or not isinstance(media, dict)
                or media.get("media_index") != expected_media_index):
            raise MediaFailure("occurrence_binding_invalid")
        url, key, upgraded, token_appended = _request_details(media)
        root = Path(output_dir).resolve(strict=True)
        if not root.is_dir():
            raise MediaFailure("output_directory_missing")
        result["https_upgraded"] = upgraded
        result["source_token_appended"] = token_appended
        result["rendition_path_changed"] = False
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _CheckedRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request = urllib.request.Request(url, headers={
            "User-Agent": "MicroMessenger Client", "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9", "Connection": "close"})
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise MediaFailure("http_incomplete_response")
            length = response.headers.get("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_IMAGE_BYTES):
                raise MediaFailure("response_size_rejected")
            raw = response.read(MAX_IMAGE_BYTES + 1)
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise MediaFailure("response_size_rejected")
            if length and len(raw) != int(length):
                raise MediaFailure("response_incomplete")
        decoded = raw
        decoded_with = "none_plain_image"
        try:
            info = _image_info(raw)
        except Exception:
            if key is None:
                raise MediaFailure("encrypted_or_invalid_image_without_record_key")
            self_test()
            stream = Isaac64(key).keystream(len(raw))
            decoded = bytes(value ^ stream[i] for i, value in enumerate(raw))
            try:
                info = _image_info(decoded)
            except Exception:
                raise MediaFailure("image_decode_failed") from None
            decoded_with = "ISAAC64_record_key"
        digest = hashlib.sha256(decoded).hexdigest()
        blobs = root / "blobs"
        blobs.mkdir(exist_ok=True)
        destination = blobs / digest
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise MediaFailure("existing_blob_mismatch")
        else:
            temporary = blobs / (digest + "." + uuid.uuid4().hex + ".part")
            try:
                with temporary.open("xb") as handle:
                    handle.write(decoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
        reopened = destination.read_bytes()
        if hashlib.sha256(reopened).hexdigest() != digest:
            raise MediaFailure("stored_blob_mismatch")
        _image_info(reopened)
        result.update(status="STORED_VERIFIED", sha256=digest, bytes=len(decoded),
                      received_bytes=len(raw), blob_path=str(destination),
                      decode_method=decoded_with, **info)
    except MediaFailure as error:
        result["failure_code"] = str(error)
    except urllib.error.HTTPError as error:
        result["failure_code"] = "http_status_" + str(error.code)
    except Exception:
        # Never log exception text: urllib exceptions may include signed URLs.
        result["failure_code"] = "request_or_storage_failure"
    return result
