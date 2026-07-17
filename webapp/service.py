from __future__ import annotations

import os
import shutil
import tempfile
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol, Sequence

from markitdown import MarkItDown


class ConverterResult(Protocol):
    markdown: str


class Converter(Protocol):
    def convert_local(self, path: str | Path) -> ConverterResult: ...


@dataclass(frozen=True)
class ConversionRecord:
    source_name: str
    output_name: str | None
    success: bool
    message: str
    markdown: str = ""


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".wav",
    ".mp3",
    ".m4a",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".xml",
    ".epub",
    ".msg",
    ".txt",
    ".md",
}
ARCHIVE_EXTENSIONS = {".zip"}

OUTPUT_ROOT = Path(tempfile.gettempdir()) / "markitdown-web"
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_FILE_MB = 50
DEFAULT_MAX_TOTAL_MB = 200
DEFAULT_PREVIEW_CHARS = 40_000
DEFAULT_RETENTION_HOURS = 12


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, minimum)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configured_limits() -> tuple[int, int, int]:
    return (
        _env_int("MAX_FILES", DEFAULT_MAX_FILES),
        _env_int("MAX_FILE_MB", DEFAULT_MAX_FILE_MB),
        _env_int("MAX_TOTAL_MB", DEFAULT_MAX_TOTAL_MB),
    )


def allowed_extensions() -> set[str]:
    extensions = set(SUPPORTED_EXTENSIONS)
    if _env_bool("ALLOW_ARCHIVES", False):
        extensions.update(ARCHIVE_EXTENSIONS)
    return extensions


def cleanup_stale_outputs() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    retention_seconds = _env_int(
        "OUTPUT_RETENTION_HOURS", DEFAULT_RETENTION_HOURS
    ) * 3600
    cutoff = time.time() - retention_seconds

    for child in OUTPUT_ROOT.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def _normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name)
    normalized = normalized.replace("\x00", "").replace("/", "_").replace("\\", "_")
    normalized = " ".join(normalized.split()).strip(" .")
    return normalized or "document"


def _unique_output_name(source_name: str, used_names: set[str]) -> str:
    stem = _normalize_name(Path(source_name).stem)
    candidate = f"{stem}.md"
    counter = 2
    while candidate.casefold() in used_names:
        candidate = f"{stem}-{counter}.md"
        counter += 1
    used_names.add(candidate.casefold())
    return candidate


def _validate_files(paths: Sequence[Path]) -> None:
    max_files, max_file_mb, max_total_mb = configured_limits()
    if not paths:
        raise ValueError("لم يتم اختيار أي ملف.")
    if len(paths) > max_files:
        raise ValueError(f"الحد الأقصى هو {max_files} ملفًا في العملية الواحدة.")

    permitted = allowed_extensions()
    max_file_bytes = max_file_mb * 1024 * 1024
    max_total_bytes = max_total_mb * 1024 * 1024
    total_bytes = 0

    for path in paths:
        if not path.exists() or not path.is_file():
            raise ValueError(f"الملف غير متاح: {path.name}")
        if path.suffix.lower() not in permitted:
            raise ValueError(
                f"صيغة غير مدعومة أو غير مفعّلة: {path.suffix or '(بلا امتداد)'}"
            )
        size = path.stat().st_size
        if size > max_file_bytes:
            raise ValueError(f"يتجاوز الملف {path.name} حد {max_file_mb} MB.")
        total_bytes += size

    if total_bytes > max_total_bytes:
        raise ValueError(f"يتجاوز مجموع الملفات حد {max_total_mb} MB.")


def convert_paths(
    paths: Sequence[str | Path],
    *,
    converter_factory: Callable[[], Converter] = MarkItDown,
) -> tuple[list[ConversionRecord], Path | None]:
    cleanup_stale_outputs()
    normalized_paths = [Path(path) for path in paths]
    _validate_files(normalized_paths)

    request_dir = Path(tempfile.mkdtemp(prefix="job-", dir=OUTPUT_ROOT))
    converter = converter_factory()
    records: list[ConversionRecord] = []
    used_names: set[str] = set()

    for source in normalized_paths:
        output_name = _unique_output_name(source.name, used_names)
        output_path = request_dir / output_name
        try:
            result = converter.convert_local(source)
            markdown = result.markdown.strip()
            if not markdown:
                raise ValueError("أعاد المحول محتوى Markdown فارغًا.")
            output_path.write_text(markdown + "\n", encoding="utf-8")
            records.append(
                ConversionRecord(
                    source_name=source.name,
                    output_name=output_name,
                    success=True,
                    message="تم التحويل بنجاح.",
                    markdown=markdown,
                )
            )
        except Exception as exc:  # Keep batch processing after one file fails.
            records.append(
                ConversionRecord(
                    source_name=source.name,
                    output_name=None,
                    success=False,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )

    successful = [record for record in records if record.success]
    if not successful:
        shutil.rmtree(request_dir, ignore_errors=True)
        return records, None

    report_path = request_dir / "conversion-report.md"
    report_path.write_text(_build_report(records), encoding="utf-8")

    if len(successful) == 1 and len(records) == 1:
        return records, request_dir / successful[0].output_name  # type: ignore[arg-type]

    archive_path = request_dir / "markitdown-results.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for record in successful:
            if record.output_name:
                archive.write(request_dir / record.output_name, arcname=record.output_name)
        archive.write(report_path, arcname=report_path.name)
    return records, archive_path


def _build_report(records: Iterable[ConversionRecord]) -> str:
    lines = ["# تقرير التحويل", ""]
    for record in records:
        status = "نجاح" if record.success else "فشل"
        output = f" → `{record.output_name}`" if record.output_name else ""
        lines.append(f"- **{status}:** `{record.source_name}`{output} — {record.message}")
    lines.append("")
    return "\n".join(lines)


def build_ui_response(
    uploaded_files: Sequence[str] | str | None,
) -> tuple[str, str | None, str]:
    if uploaded_files is None:
        return "", None, "يرجى اختيار ملف واحد على الأقل."

    paths = [uploaded_files] if isinstance(uploaded_files, str) else list(uploaded_files)
    try:
        records, downloadable = convert_paths(paths)
    except ValueError as exc:
        return "", None, f"تعذر بدء التحويل: {exc}"

    successful = [record for record in records if record.success]
    failed = [record for record in records if not record.success]

    preview = ""
    if successful:
        first = successful[0]
        preview = first.markdown[:DEFAULT_PREVIEW_CHARS]
        if len(first.markdown) > DEFAULT_PREVIEW_CHARS:
            preview += "\n\n… تم اختصار المعاينة؛ الملف القابل للتنزيل كامل."

    status_lines = [
        f"تم بنجاح: {len(successful)}",
        f"تعذر تحويله: {len(failed)}",
    ]
    if failed:
        status_lines.append("")
        status_lines.extend(
            f"- {record.source_name}: {record.message}" for record in failed
        )

    return preview, str(downloadable) if downloadable else None, "\n".join(status_lines)
