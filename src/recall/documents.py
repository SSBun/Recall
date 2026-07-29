import hashlib
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = {".md", ".pdf", ".txt"}
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50


class SourceError(ValueError):
    pass


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    text: str
    content_hash: str
    size: int
    modified_ns: int


def discover_files(paths: list[str], recursive: bool) -> list[Path]:
    discovered: set[Path] = set()

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise SourceError(f"文件不存在: {path}")
        if path.is_dir():
            if not recursive:
                raise SourceError(f"目录需要 --recursive: {path}")
            candidates = path.rglob("*")
            discovered.update(
                candidate.resolve()
                for candidate in candidates
                if candidate.is_file()
                and candidate.suffix.lower() in SUPPORTED_SUFFIXES
            )
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise SourceError(f"不支持的文件格式: {path}")
        discovered.add(path.resolve())

    return sorted(discovered, key=lambda path: str(path))


def prepare_file(path: Path) -> SourceDocument:
    resolved = path.expanduser().resolve()
    try:
        stat = resolved.stat()
        text = _read_text(resolved)
    except (OSError, UnicodeError) as error:
        raise SourceError(f"无法读取 {resolved}: {error}") from error
    if not text.strip():
        raise SourceError(f"文档没有可索引文本: {resolved}")

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SourceDocument(resolved, text, content_hash, stat.st_size, stat.st_mtime_ns)


def split_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size 必须为正数，且 overlap 必须小于 chunk_size")

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            split_at = _last_separator(text, start + chunk_size // 2, end)
            if split_at is not None:
                end = split_at
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end - overlap, start + 1)

    return chunks


def _last_separator(text: str, lower: int, upper: int) -> int | None:
    best = -1
    width = 0
    for separator in ("\n\n", "\n", "。", ". ", " "):
        position = text.rfind(separator, lower, upper)
        if position > best:
            best = position
            width = len(separator)
    return best + width if best >= lower else None


def _read_text(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8")

    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise SourceError("读取 PDF 需要安装 pypdf") from error

    try:
        reader = PdfReader(path)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    # pypdf 的解析异常类型随损坏方式变化，统一映射到文件级 SOURCE_ERROR。
    except Exception as error:
        raise SourceError(f"无法解析 PDF {path}: {error}") from error
