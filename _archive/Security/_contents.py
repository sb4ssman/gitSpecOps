"""What is inside a binary file: the members of an archive, the metadata of an image. Pure:
bytes in, names and text out -- no git, no files, no network.

A text scan reads a compressed file as noise, so "nothing found" in an archive or a photo
meant "not looked at". Two kinds are opened here, with the standard library only:

- **Archives** -- zip (also .jar, .whl, Office documents and EPUBs), tar (plain, gz, bz2, xz)
  and single-file gz / bz2 / xz. Every member's name and content come back for the same scan
  as any file. 7z and rar need tools the standard library lacks, so they come back as *not
  inspected*, with the reason.
- **Images** -- PNG, JPEG, WebP and TIFF metadata: PNG text chunks (compressed ones too), EXIF
  text fields (artist, copyright, comments, the camera's serial number, Windows' UTF-16
  author/title tags) and XMP. Whether the EXIF carries a **GPS position** is reported on its own:
  coordinates are binary numbers that no text pattern can find.

Reading is bounded: a member or decompressed stream over the limit is reported, not read, so an
archive bomb costs nothing.
"""
from __future__ import annotations

import bz2
import gzip
import io
import lzma
import struct
import tarfile
import zipfile
import zlib
from dataclasses import dataclass, field

MEMBER_LIMIT_BYTES = 64 * 1024 * 1024
ARCHIVE_LIMIT_BYTES = 512 * 1024 * 1024
#: An archive inside an archive is opened too, this many levels down.
NESTING = 2

#: Office documents and EPUBs are zip files; their docProps/core.xml names the author.
ZIP_SUFFIXES = (".zip", ".jar", ".whl", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
                ".epub")
TAR_SUFFIXES = (".tar", ".tgz", ".tar.gz", ".tbz2", ".tar.bz2", ".txz", ".tar.xz")
STREAM_SUFFIXES = {".gz": lambda raw: gzip.GzipFile(fileobj=raw),
                   ".bz2": bz2.BZ2File, ".xz": lzma.LZMAFile}
UNREADABLE_SUFFIXES = (".7z", ".rar")
ARCHIVE_SUFFIXES = (*ZIP_SUFFIXES, *TAR_SUFFIXES, *STREAM_SUFFIXES, *UNREADABLE_SUFFIXES)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")


def is_archive(path: str) -> bool:
    return path.lower().endswith(ARCHIVE_SUFFIXES)


def is_image(path: str) -> bool:
    return path.lower().endswith(IMAGE_SUFFIXES)


@dataclass
class Opened:
    """An archive's members as (name, bytes), and what could not be read, with why."""
    members: list = field(default_factory=list)
    skipped: list = field(default_factory=list)   # (member name or "", reason)


def _bounded(stream, label: str, opened: Opened) -> bytes | None:
    data = stream.read(MEMBER_LIMIT_BYTES + 1)
    if len(data) > MEMBER_LIMIT_BYTES:
        opened.skipped.append((label, f"over {MEMBER_LIMIT_BYTES // (1024 * 1024)} MiB unpacked"))
        return None
    return data


def open_archive(path: str, data: bytes, depth: int = 0) -> Opened:
    """Every member of the archive at `path` (its name picks the format), nested ones included."""
    opened = Opened()
    lower = path.lower()
    try:
        if lower.endswith(ZIP_SUFFIXES):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                total = 0
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if info.flag_bits & 0x1:
                        opened.skipped.append((info.filename, "encrypted"))
                        continue
                    total += info.file_size
                    if info.file_size > MEMBER_LIMIT_BYTES or total > ARCHIVE_LIMIT_BYTES:
                        opened.skipped.append((info.filename, "over the size limit"))
                        continue
                    with archive.open(info) as member:
                        content = _bounded(member, info.filename, opened)
                    if content is not None:
                        opened.members.append((info.filename, content))
        elif lower.endswith(TAR_SUFFIXES):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                total = 0
                for info in archive:
                    if not info.isfile():
                        continue
                    total += info.size
                    if info.size > MEMBER_LIMIT_BYTES or total > ARCHIVE_LIMIT_BYTES:
                        opened.skipped.append((info.name, "over the size limit"))
                        continue
                    member = archive.extractfile(info)
                    content = _bounded(member, info.name, opened) if member else None
                    if content is not None:
                        opened.members.append((info.name, content))
        elif lower.endswith(tuple(STREAM_SUFFIXES)):
            suffix = next(s for s in STREAM_SUFFIXES if lower.endswith(s))
            name = path.rsplit("/", 1)[-1][: -len(suffix)]
            content = _bounded(STREAM_SUFFIXES[suffix](io.BytesIO(data)), name, opened)
            if content is not None:
                opened.members.append((name, content))
        else:
            opened.skipped.append(("", "this format needs a tool the standard library lacks"))
            return opened
    except (OSError, EOFError, ValueError, zipfile.BadZipFile, tarfile.TarError,
            lzma.LZMAError, zlib.error, NotImplementedError) as exc:
        opened.skipped.append(("", f"could not be opened ({type(exc).__name__})"))
        return opened
    if depth + 1 < NESTING:
        for name, content in list(opened.members):
            if is_archive(name):
                inner = open_archive(name, content, depth + 1)
                opened.members += [(f"{name}!{n}", c) for n, c in inner.members]
                opened.skipped += [(f"{name}!{n}" if n else name, why)
                                   for n, why in inner.skipped]
    return opened


# --- images --------------------------------------------------------------------------------

@dataclass
class ImageMetadata:
    texts: list = field(default_factory=list)   # every metadata string, for the text scan
    gps: bool = False                           # EXIF holds a latitude or longitude


#: EXIF tags holding free text: ImageDescription, Make, Model, Software, Artist, Copyright,
#: UserComment, CameraOwnerName, BodySerialNumber, LensSerialNumber, and the camera's serial.
_TEXT_TAGS = {0x010E, 0x010F, 0x0110, 0x0131, 0x013B, 0x8298, 0x9286, 0xA430, 0xA431, 0xA435,
              0xC62F}
#: Windows Explorer's own tags, UTF-16LE: XPTitle, XPComment, XPAuthor, XPKeywords, XPSubject.
_XP_TAGS = {0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F}
_EXIF_IFD, _GPS_IFD = 0x8769, 0x8825
_GPS_POSITION_TAGS = {1, 2, 3, 4}   # latitude ref, latitude, longitude ref, longitude
_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def _tiff(data: bytes, found: ImageMetadata) -> None:
    """Read EXIF text fields and the GPS position's presence from a TIFF structure."""
    if data[:2] == b"II":
        order = "<"
    elif data[:2] == b"MM":
        order = ">"
    else:
        return
    try:
        (first,) = struct.unpack_from(order + "I", data, 4)
    except struct.error:
        return
    seen, queue = set(), [(first, "main")]
    while queue:
        offset, kind = queue.pop()
        if offset in seen or offset <= 0 or offset + 2 > len(data):
            continue
        seen.add(offset)
        try:
            (count,) = struct.unpack_from(order + "H", data, offset)
            for index in range(min(count, 512)):
                tag, kind_of, n, value = struct.unpack_from(order + "HHI4s", data,
                                                            offset + 2 + 12 * index)
                size = _TYPE_SIZES.get(kind_of, 1) * n
                if size <= 4:
                    raw = value[:size]
                else:
                    (pointer,) = struct.unpack(order + "I", value)
                    raw = data[pointer:pointer + size]
                if kind == "gps":
                    if tag in _GPS_POSITION_TAGS:
                        found.gps = True
                    continue
                if tag in (_EXIF_IFD, _GPS_IFD):
                    queue.append((struct.unpack(order + "I", value)[0],
                                  "gps" if tag == _GPS_IFD else "main"))
                elif tag in _XP_TAGS:
                    found.texts.append(raw.decode("utf-16-le", errors="replace").strip("\0"))
                elif tag in _TEXT_TAGS:
                    found.texts.append(raw.decode("utf-8", errors="replace").strip("\0 "))
            (following,) = struct.unpack_from(order + "I", data, offset + 2 + 12 * count)
            queue.append((following, kind))
        except struct.error:
            continue


def _png(data: bytes, found: ImageMetadata) -> None:
    position = 8
    while position + 8 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, position)
        body = data[position + 8: position + 8 + length]
        position += 12 + length
        try:
            if kind == b"tEXt":
                found.texts.append(body.replace(b"\0", b" ").decode("latin-1"))
            elif kind == b"zTXt":
                keyword, _, rest = body.partition(b"\0")
                found.texts.append(keyword.decode("latin-1") + " " +
                                   zlib.decompress(rest[1:]).decode("latin-1"))
            elif kind == b"iTXt":
                keyword, _, rest = body.partition(b"\0")
                compressed, rest = rest[:1] == b"\1", rest[2:]
                _language, _, rest = rest.partition(b"\0")
                _translated, _, text = rest.partition(b"\0")
                found.texts.append(keyword.decode("latin-1") + " " + (
                    zlib.decompress(text) if compressed else text).decode("utf-8", "replace"))
            elif kind == b"eXIf":
                _tiff(body, found)
        except zlib.error:
            pass   # a damaged chunk holds nothing readable; the raw-byte scan still ran
        if kind == b"IEND":
            break


def _jpeg(data: bytes, found: ImageMetadata) -> None:
    position = 2
    while position + 4 <= len(data) and data[position] == 0xFF:
        marker = data[position + 1]
        if marker in (0xD9, 0xDA):   # end of image, start of scan: no metadata follows
            break
        (length,) = struct.unpack_from(">H", data, position + 2)
        body = data[position + 4: position + 2 + length]
        if marker == 0xE1 and body.startswith(b"Exif\0\0"):
            _tiff(body[6:], found)
        elif marker in (0xE1, 0xFE):  # XMP, comment
            found.texts.append(body.decode("utf-8", errors="replace"))
        position += 2 + length


def _webp(data: bytes, found: ImageMetadata) -> None:
    position = 12
    while position + 8 <= len(data):
        kind, length = struct.unpack_from("<4sI", data, position)
        body = data[position + 8: position + 8 + length]
        if kind == b"EXIF":
            _tiff(body[6:] if body.startswith(b"Exif\0\0") else body, found)
        elif kind == b"XMP ":
            found.texts.append(body.decode("utf-8", errors="replace"))
        position += 8 + length + (length & 1)


def image_metadata(data: bytes) -> ImageMetadata | None:
    """The metadata an image carries, or None when the bytes are not a format read here."""
    found = ImageMetadata()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        _png(data, found)
    elif data.startswith(b"\xff\xd8"):
        _jpeg(data, found)
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        _webp(data, found)
    elif data[:4] in (b"II*\0", b"MM\0*"):
        _tiff(data, found)
    else:
        return None
    found.texts = [text for text in found.texts if text.strip()]
    return found
