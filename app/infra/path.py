from pathlib import Path


def resolve_in_session(name:str, session_path:Path):
    clean = Path(name.lstrip("/\\"))

    full = (session_path / clean).resolve()

    if not full.is_relative_to(session_path.resolve()):
        raise ValueError(f"路径穿越：{name} does not exist in {session_path}")

    return full
