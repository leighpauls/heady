from dataclasses import dataclass
from typing import List

import git


@dataclass
class HeadyRepo:
    trunk_refs: List[str]
    repo: git.Repo
