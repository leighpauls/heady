import datetime
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

import git

from heady import config
from heady.repo import HeadyRepo


@dataclass
class CommitNode:
    commit: git.Commit
    children: List["CommitNode"]
    is_hidden: bool
    labels: Optional[List[str]]

    def __init__(
        self, commit: git.Commit, is_hidden: bool, labels: Optional[Iterable[str]]
    ):
        self.commit = commit
        self.children = []
        self.is_hidden = is_hidden
        self.labels = labels

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
        if self.commit.repo.head.commit == self.commit:
            dot_char = "@"
        elif self.is_hidden:
            dot_char = "."
        else:
            dot_char = "*"
        if self.labels:
            label_str = " {" + ",".join(self.labels) + "}"
        else:
            label_str = ""
        print(f"{bars}{dot_char} {self.commit.hexsha[:8]}{label_str} {short_message}")


@dataclass
class HeadyTree:
    commit_nodes: Dict[str, CommitNode]
    trunk_nodes: List[CommitNode]


def build_tree(r: HeadyRepo) -> HeadyTree:
    reflog: git.RefLog = r.repo.head.log()
    cur_time = datetime.datetime.now()
    max_age = datetime.timedelta(days=14)

    hide_list_shas = config.get_hide_list(r.repo)
    tip_shas = set()

    # Find tips from the reflog
    item: git.RefLogEntry
    for item in reversed(reflog):
        time_seconds, _offset = item.time
        item_time = datetime.datetime.fromtimestamp(time_seconds)
        age = cur_time - item_time
        if age > max_age:
            break
        item_sha = item.newhexsha
        if item_sha not in hide_list_shas:
            tip_shas.add(item_sha)

    # Find tips from special branches
    special_branches: Dict[str, Set[str]] = dict()
    for local_head in r.repo.heads:
        sha = local_head.commit.hexsha
        tip_shas.add(sha)
        special_branches.setdefault(sha, set()).add(local_head.name)
    special_branches.setdefault(r.repo.commit(r.trunk_ref).hexsha, set()).add(
        r.trunk_ref
    )

    # Find ancestors of tips which are not ancestors of trunk
    rev_list_cmds = list(tip_shas) + [f"^{r.trunk_ref}"]
    rev_list_output = r.repo.git.rev_list(*rev_list_cmds)
    branch_commit_shas = set(rev_list_output.split("\n")) if rev_list_output else set()

    branch_commits: List[git.Commit] = [
        r.repo.commit(sha) for sha in branch_commit_shas
    ]

    def make_node(commit: git.Commit) -> CommitNode:
        return CommitNode(
            commit,
            is_hidden=commit.hexsha in hide_list_shas,
            labels=special_branches.get(commit.hexsha, None),
        )

    # build the node objects
    commit_nodes: Dict[str, CommitNode] = {}
    for bc in branch_commits:
        commit_nodes[bc.hexsha] = make_node(bc)

    # link the node objects
    trunk_branch_commit = r.repo.commit(r.trunk_ref)
    trunk_nodes: Dict[str, CommitNode] = {
        trunk_branch_commit.hexsha: make_node(trunk_branch_commit)
    }
    for node in commit_nodes.values():
        parent_commit = node.commit.parents[0]
        parent_sha = parent_commit.hexsha
        if parent_sha not in commit_nodes:
            if parent_sha not in trunk_nodes:
                trunk_nodes[parent_sha] = make_node(parent_commit)
            trunk_nodes[parent_sha].children.append(node)
        else:
            commit_nodes[parent_sha].children.append(node)

    ordered_tree = sorted(
        trunk_nodes.values(), key=lambda n: n.commit.committed_datetime, reverse=True
    )
    return HeadyTree(commit_nodes, ordered_tree)


def collect_subtree_shas(node: CommitNode, dest: Set[str]) -> None:
    sha = node.commit.hexsha
    if sha in dest:
        return
    dest.add(sha)
    for child in node.children:
        collect_subtree_shas(child, dest)
