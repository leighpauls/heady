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

    def print_tree(self) -> None:
        self._print_children(1)
        self._print_splits(0, len(self.children))
        self._print_self(0)
        print(":")

    def _print_tree(self, indent: int) -> None:
        self._print_children(indent)
        self._print_splits(indent, len(self.children) - 1)
        self._print_self(indent)

    def _print_children(self, indent: int) -> None:
        for i, child in enumerate(self.children):
            child._print_tree(indent + i)

    def _print_splits(self, indent: int, num_splits: int) -> None:
        for i in range(indent + num_splits, indent, -1):
            bars = "| " * (i - 1)
            print(f"{bars}|/")

    def _print_self(self, indent: int) -> None:
        bars = "| " * indent
        short_message = self.commit.message.split("\n", 1)[0]
        print(f"{bars}* {self.commit.hexsha[:8]} {short_message}")


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
    trunk_branch_commit = repo.commit(trunk_branch)
    trunk_nodes: Dict[str, CommitNode] = {
        trunk_branch_commit.hexsha: CommitNode(trunk_branch_commit)
    }
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

    ordered_tree = sorted(
        trunk_nodes.values(), key=lambda n: n.commit.committed_datetime, reverse=True
    )

    times.append(time.time())

    for node in ordered_tree:
        node.print_tree()

    times.append(time.time())

    print("times:", [times[i] - times[i - 1] for i in range(1, len(times))])


if __name__ == "__main__":
    main()
