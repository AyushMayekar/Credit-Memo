from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

DEFAULT_FILES = (
    "extraction-v4-output/TEST/GOODWIN-SAMPLE/extraction.json",
    "parser-v8-output/TEST/GOODWIN-SAMPLE/parsed_document.json",
    "/table-boundary-review/goodwin-sample/table_regions.json",
    )

DEFAULT_MAX_CHARACTERS = 45_000
MIN_MAX_CHARACTERS = 1_000
SEPARATOR = "=" * 96


def read_text_safely(path: Path) -> tuple[str | None, str | None]:
    """Read a text file using common UTF-8 encodings."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig"), None
        except Exception as exc:
            return None, f"Could not decode file: {exc}"
    except Exception as exc:
        return None, str(exc)


def split_text_by_lines(text: str, max_characters: int) -> list[str]:
    """Split text into character-limited parts at line boundaries."""
    if max_characters <= 0:
        raise ValueError("max_characters must be greater than zero.")
    if not text:
        return [""]
    if len(text) <= max_characters:
        return [text]

    parts: list[str] = []
    current_lines: list[str] = []
    current_length = 0

    for line in text.splitlines(keepends=True):
        if len(line) > max_characters:
            if current_lines:
                parts.append("".join(current_lines))
                current_lines = []
                current_length = 0
            for start in range(0, len(line), max_characters):
                parts.append(line[start : start + max_characters])
            continue

        if current_lines and current_length + len(line) > max_characters:
            parts.append("".join(current_lines))
            current_lines = []
            current_length = 0

        current_lines.append(line)
        current_length += len(line)

    if current_lines:
        parts.append("".join(current_lines))
    return parts


def build_snapshot_sections(
    root: Path,
) -> tuple[list[str], int, list[str], list[str]]:
    """Read requested files and return snapshot sections and counts."""
    sections: list[str] = []
    included = 0
    missing: list[str] = []
    failed: list[str] = []

    for relative_name in DEFAULT_FILES:
        path = root / relative_name
        section_lines = [SEPARATOR, f"FILE: {relative_name}", SEPARATOR, ""]

        if not path.exists():
            section_lines.extend(["[MISSING FILE]", ""])
            missing.append(relative_name)
            sections.append("\n".join(section_lines))
            continue

        if not path.is_file():
            section_lines.extend(["[NOT A FILE]", ""])
            failed.append(relative_name)
            sections.append("\n".join(section_lines))
            continue

        content, error = read_text_safely(path)
        if error is not None:
            section_lines.extend([f"[READ ERROR] {error}", ""])
            failed.append(relative_name)
            sections.append("\n".join(section_lines))
            continue

        section_lines.extend([content or "", ""])
        included += 1
        sections.append("\n".join(section_lines))

    return sections, included, missing, failed


def build_summary(included: int, missing: list[str], failed: list[str]) -> str:
    """Build the final snapshot summary."""
    lines = [
        SEPARATOR,
        "SNAPSHOT SUMMARY",
        SEPARATOR,
        f"Included: {included}",
        f"Missing: {len(missing)}",
        f"Read failures: {len(failed)}",
    ]
    if missing:
        lines.extend(["", "Missing files:", *[f"- {name}" for name in missing]])
    if failed:
        lines.extend(["", "Unreadable files:", *[f"- {name}" for name in failed]])
    return "\n".join(lines)


def create_snapshot_content(
    root: Path,
) -> tuple[str, int, list[str], list[str]]:
    """Create the complete snapshot before splitting it."""
    sections, included, missing, failed = build_snapshot_sections(root)
    header = "\n".join(
        [
            "CODE SNAPSHOT",
            SEPARATOR,
            f"Project root: {root}",
            f"Requested files: {len(DEFAULT_FILES)}",
            "",
        ]
    )
    summary = build_summary(included, missing, failed)
    snapshot = "\n".join([header, *sections, summary, ""])
    return snapshot, included, missing, failed


def create_part_header(part_number: int, total_parts: int, source_name: str) -> str:
    """Create the information header for one snapshot part."""
    return "\n".join(
        [
            "CODE SNAPSHOT",
            f"SNAPSHOT PART: {part_number} OF {total_parts}",
            f"SOURCE SNAPSHOT: {source_name}",
            SEPARATOR,
            "",
        ]
    )


def split_snapshot_with_headers(
    snapshot: str,
    max_characters: int,
    source_name: str,
) -> list[str]:
    """Split the snapshot while keeping every final part under the limit."""
    sample_header = create_part_header(9999, 9999, source_name)
    available_characters = max_characters - len(sample_header)
    if available_characters <= 0:
        raise ValueError("The character limit is too small for the part header.")

    raw_parts = split_text_by_lines(snapshot, available_characters)
    total_parts = len(raw_parts)
    final_parts = [
        create_part_header(index, total_parts, source_name) + content
        for index, content in enumerate(raw_parts, start=1)
    ]

    for index, part in enumerate(final_parts, start=1):
        if len(part) > max_characters:
            raise RuntimeError(
                f"Generated part {index} exceeds the {max_characters:,} character limit."
            )
    return final_parts


def resolve_output_directory(root: Path, output: Path | None) -> Path:
    """Resolve the directory where snapshot parts will be written."""
    if output is None:
        return root
    resolved = output.resolve()
    return resolved.parent if resolved.suffix else resolved


def resolve_output_prefix(output: Path | None) -> str:
    """Resolve the numbered snapshot filename prefix."""
    if output is not None and output.suffix:
        return output.stem
    return "snap"


def remove_old_snapshot_parts(output_directory: Path, output_prefix: str) -> int:
    """Remove old numbered snapshot files using the same prefix."""
    if not output_directory.exists():
        return 0

    pattern = re.compile(
        rf"^{re.escape(output_prefix)}\d+\.txt$",
        re.IGNORECASE,
    )
    removed = 0
    for path in output_directory.glob(f"{output_prefix}*.txt"):
        if path.is_file() and pattern.fullmatch(path.name):
            path.unlink()
            removed += 1
    return removed


def write_snapshot_parts(
    parts: list[str],
    output_directory: Path,
    output_prefix: str,
) -> list[Path]:
    """Write all snapshot parts and return their paths."""
    output_directory.mkdir(parents=True, exist_ok=True)
    written_files: list[Path] = []
    for index, content in enumerate(parts, start=1):
        output_path = output_directory / f"{output_prefix}{index}.txt"
        output_path.write_text(content, encoding="utf-8")
        written_files.append(output_path)
    return written_files


def parse_arguments() -> argparse.Namespace:
    """Read command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Export focused UI and credit-memo files into "
            "character-limited text snapshot parts."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional output directory or base filename. The default creates "
            "snap1.txt, snap2.txt, and so on in the project root."
        ),
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARACTERS,
        help=f"Maximum characters per file. Default: {DEFAULT_MAX_CHARACTERS:,}.",
    )
    args = parser.parse_args()
    if args.max_chars < MIN_MAX_CHARACTERS:
        parser.error(f"--max-chars must be at least {MIN_MAX_CHARACTERS:,}.")
    return args


def main() -> None:
    """Create character-limited snapshot text files."""
    args = parse_arguments()
    root = args.root.resolve()

    if not root.exists():
        raise SystemExit(f"Project root does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Project root is not a directory: {root}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_name = f"current_code_snapshot_{timestamp}.txt"
    snapshot, included, missing, failed = create_snapshot_content(root)
    parts = split_snapshot_with_headers(snapshot, args.max_chars, source_name)
    output_directory = resolve_output_directory(root, args.output)
    output_prefix = resolve_output_prefix(args.output)
    removed_count = remove_old_snapshot_parts(output_directory, output_prefix)
    written_files = write_snapshot_parts(parts, output_directory, output_prefix)

    print("Snapshot export completed.")
    print(f"Project root: {root}")
    print(f"Included: {included}/{len(DEFAULT_FILES)}")
    print(f"Total snapshot characters: {len(snapshot):,}")
    print(f"Maximum characters per file: {args.max_chars:,}")
    print(f"Snapshot files created: {len(written_files)}")
    if removed_count:
        print(f"Old snapshot files removed: {removed_count}")

    for path in written_files:
        character_count = len(path.read_text(encoding="utf-8"))
        print(f"- {path} ({character_count:,} characters)")
    if missing:
        print(f"Missing files: {len(missing)}")
    if failed:
        print(f"Read failures: {len(failed)}")


if __name__ == "__main__":
    main()
