from pathlib import Path

from langchain_core.tools import tool


@tool
def analyze_file(file_path: str) -> str:
    """Read and analyze a file's content. Returns the content of the file.

    Args:
        file_path: Path to the file to analyze
    """
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"
    if not path.is_file():
        return f"Not a file: {file_path}"
    if path.stat().st_size > 1_000_000:
        return f"File too large ({path.stat().st_size} bytes). Max 1MB."

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return f"File: {file_path}\nSize: {path.stat().st_size} bytes\n\n{content}"
    except Exception as e:
        return f"Error reading file: {str(e)}"
