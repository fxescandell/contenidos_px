IGNORED_SOURCE_FOLDERS = {"processed"}


def is_ignored_source_folder(name: str) -> bool:
    return (name or "").strip().lower() in IGNORED_SOURCE_FOLDERS


def path_contains_ignored_source_folder(path: str) -> bool:
    parts = [part for part in str(path or "").replace("\\", "/").split("/") if part and part != "."]
    return any(is_ignored_source_folder(part) for part in parts)
