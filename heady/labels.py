from typing import List

import git


def get_labels(commit: git.Commit) -> List[str]:
    result = []
    for line in commit.message.split("\n"):
        if not line.startswith("heady_label:"):
            continue
        result.append(line.split(":", 1)[1].strip())
    return result
