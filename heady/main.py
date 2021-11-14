import datetime
import time
from dataclasses import dataclass
from pprint import pprint
from typing import Dict, List

import git


@dataclass
class CommitNode:
    commit: git.Commit
    children: List["CommitNode"]

    def __init__(self, commit: git.Commit):
        self.commit = commit
        self.children = []


def main() -> None:
    times = [time.time()]
    trunk_branch = "origin/main"
    repo = git.Repo("/Users/leigh/src/nextdoor.com")
    reflog: git.RefLog = repo.head.log()
    times.append(time.time())

    cur_time = datetime.datetime.now()
    max_age = datetime.timedelta(days=14)

    tips = []
    tip_shas = set()

    item: git.RefLogEntry
    for item in reversed(reflog):
        time_seconds, _offset = item.time
        item_time = datetime.datetime.fromtimestamp(time_seconds)
        age = cur_time - item_time
        if age > max_age:
            break
        tips.append(item)
        tip_shas.add(item.newhexsha)
    pprint(len(tip_shas))
    times.append(time.time())

    rev_list_cmds = list(tip_shas) + [f"^{trunk_branch}"]
    branch_commit_shas = set(repo.git.rev_list(*rev_list_cmds).split("\n"))
    print("branch commits: ", len(branch_commit_shas))

    times.append(time.time())

    root_sha = repo.merge_base(*list(branch_commit_shas), trunk_branch)
    print("root sha", root_sha)
    times.append(time.time())

    branch_commits: List[git.Commit] = [repo.commit(sha) for sha in branch_commit_shas]

    # build the node objects
    commit_nodes: Dict[str, CommitNode] = {}
    for bc in branch_commits:
        commit_nodes[bc.hexsha] = CommitNode(bc)

    # link the node objects
    trunk_nodes: Dict[str, CommitNode] = {}
    for node in commit_nodes.values():
        parent_commit = node.commit.parents[0]
        parent_sha = parent_commit.hexsha
        if parent_sha not in commit_nodes:
            if parent_sha not in trunk_nodes:
                trunk_nodes[parent_sha] = CommitNode(parent_commit)
            trunk_nodes[parent_sha].children.append(node)
        else:
            commit_nodes[parent_sha].children.append(node)
    print(len(trunk_nodes))

    times.append(time.time())

    print("times:", [times[i] - times[i - 1] for i in range(1, len(times))])

    pprint(trunk_nodes)


if __name__ == "__main__":
    main()
