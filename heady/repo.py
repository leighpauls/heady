from dataclasses import dataclass

import git


@dataclass
class HeadyRepo:
    trunk_ref: str
    repo: git.Repo

