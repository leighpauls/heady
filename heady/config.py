import pathlib
from typing import Dict, Iterable, Set

import git


def get_hide_list(git_repo: git.Repo) -> Set[str]:
    res = set()
    with _ensure_hide_list_file(git_repo).open("r") as f:
        for line in f.readlines():
            res.add(line.strip())
    return res


def append_to_hide_list(git_repo: git.Repo, shas: Iterable[str]) -> None:
    with _ensure_hide_list_file(git_repo).open("a") as f:
        for sha in shas:
            f.write(f"{sha}\n")


def replace_hide_list(git_repo: git.Repo, shas: Iterable[str]) -> None:
    with _ensure_hide_list_file(git_repo).open("w") as f:
        for sha in shas:
            f.write(f"{sha}\n")


def acquire_next_label(git_repo: git.Repo, label_prefix: str) -> str:
    latest_label_numbers: Dict[str, int] = {}
    with _ensure_labels_file(git_repo).open("r") as f:
        for line in f.readlines():
            tokens = [t.strip() for t in line.split(" ")]
            latest_label_numbers[tokens[0]] = int(tokens[1])

    new_number = latest_label_numbers.get(label_prefix, 0) + 1
    latest_label_numbers[label_prefix] = new_number

    with _ensure_labels_file(git_repo).open("w") as f:
        for label, number in latest_label_numbers.items():
            f.write(f"{label} {number}\n")

    return f"{label_prefix}-{new_number}"


def _ensure_hide_list_file(git_repo: git.Repo) -> pathlib.Path:
    p = _ensure_config_directory(git_repo).joinpath("hidelist")
    if not p.exists():
        p.touch()
    return p


def _ensure_labels_file(git_repo: git.Repo) -> pathlib.Path:
    p = _ensure_config_directory(git_repo).joinpath("labels")
    if not p.exists():
        p.touch()
    return p


def _ensure_config_directory(git_repo: git.Repo) -> pathlib.Path:
    repo_path = pathlib.Path(git_repo.git_dir).resolve()
    repo_id = "_".join(repo_path.parts[1:])

    config_dir = pathlib.Path.home().joinpath(
        "Library", "Application Support", "heady", repo_id
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir
