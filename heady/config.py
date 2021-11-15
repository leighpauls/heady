import pathlib
from typing import Iterable, Set

import git


def get_hide_list(git_repo: git.Repo) -> Set[str]:
    res = set()
    with ensure_hide_list_file(git_repo).open("r") as f:
        for line in f.readlines():
            res.add(line.strip())
    return res


def append_to_hide_list(git_repo: git.Repo, shas: Iterable[str]) -> None:
    with ensure_hide_list_file(git_repo).open("a") as f:
        for sha in shas:
            f.write(f"{sha}\n")


def ensure_config_directory(git_repo: git.Repo) -> pathlib.Path:
    repo_path = pathlib.Path(git_repo.git_dir).resolve()
    repo_id = "_".join(repo_path.parts[1:])

    config_dir = pathlib.Path.home().joinpath(
        "Library", "Application Support", "heady", repo_id
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def ensure_hide_list_file(git_repo: git.Repo) -> pathlib.Path:
    p = ensure_config_directory(git_repo).joinpath("hidelist")
    if not p.exists():
        p.touch()
    return p
