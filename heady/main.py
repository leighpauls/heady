import datetime
import pathlib
from dataclasses import dataclass
from pprint import pprint
from typing import Dict, List, Set

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
        dot_char = "@" if self.commit.repo.head.commit == self.commit else "*"
        print(f"{bars}{dot_char} {self.commit.hexsha[:8]} {short_message}")


@dataclass
class HeadyTree:
    commit_nodes: Dict[str, CommitNode]
    trunk_nodes: List[CommitNode]


@dataclass
class HeadyRepo:
    trunk_ref: str
    repo: git.Repo


def main() -> None:
    r = HeadyRepo("origin/main", git.Repo("/Users/leigh/src/nextdoor.com"))
    print_tips_tree(r)
    hide_subtree(r, "c36b61d4")


def hide_subtree(r: HeadyRepo, hide_root_ref: str) -> None:
    # Raises if the hide root doesn't exist
    hide_root_commit = r.repo.commit(hide_root_ref)

    # Verify that we are not attempting to hide a commit in trunk
    if is_ancestor(r, hide_root_ref, r.trunk_ref):
        raise ValueError(
            f"Can not hide {hide_root_ref} because it would hide {r.trunk_ref}"
        )

    if is_ancestor(r, hide_root_ref, "HEAD"):
        raise ValueError(f"Can not hide {hide_root_ref} because it would hide HEAD")

    # Find all the child nodes in the tree to hide
    tree = build_tree(r)
    hide_root_sha = hide_root_commit.hexsha
    if hide_root_sha not in tree.commit_nodes:
        raise ValueError(f"Did not find {hide_root_sha} in the visible tree")

    existing_hidden_tips = get_hide_list()
    new_hidden_shas = []
    for new_hide_sha in collect_subtree_shas(tree.commit_nodes[hide_root_sha]):
        if new_hide_sha not in existing_hidden_tips:
            new_hidden_shas.append(new_hide_sha)

    with ensure_hide_list_file().open("a") as f:
        for sha in new_hidden_shas:
            f.write(f"{sha}\n")


def collect_subtree_shas(node: CommitNode) -> List[str]:
    result = [node.commit.hexsha]
    for child in node.children:
        result.extend(collect_subtree_shas(child))
    return result


def is_ancestor(r: HeadyRepo, ancestor_ref: str, descendent_ref: str):
    # If all commits of ancestor_ref exist in descendent_ref, it must be an ancestor
    missing_lineage = list(
        r.repo.iter_commits(f"{descendent_ref}..{ancestor_ref}", max_count=1)
    )
    return len(missing_lineage) == 0


def print_tips_tree(r: HeadyRepo) -> None:
    tree = build_tree(r)

    for node in tree.trunk_nodes:
        node.print_tree()


def build_tree(r: HeadyRepo) -> HeadyTree:
    reflog: git.RefLog = r.repo.head.log()
    cur_time = datetime.datetime.now()
    max_age = datetime.timedelta(days=14)

    hide_list_shas = get_hide_list()
    tip_shas = set()

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

    # Find ancestors of tips which are not ancestors of trunk
    rev_list_cmds = list(tip_shas) + [f"^{r.trunk_ref}"]
    branch_commit_shas = set(r.repo.git.rev_list(*rev_list_cmds).split("\n"))

    root_sha = r.repo.merge_base(*list(branch_commit_shas), r.trunk_ref)

    branch_commits: List[git.Commit] = [
        r.repo.commit(sha) for sha in branch_commit_shas
    ]

    # build the node objects
    commit_nodes: Dict[str, CommitNode] = {}
    for bc in branch_commits:
        commit_nodes[bc.hexsha] = CommitNode(bc)

    # link the node objects
    trunk_branch_commit = r.repo.commit(r.trunk_ref)
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

    ordered_tree = sorted(
        trunk_nodes.values(), key=lambda n: n.commit.committed_datetime, reverse=True
    )
    return HeadyTree(commit_nodes, ordered_tree)


def ensure_config_directory() -> pathlib.Path:
    config_dir = pathlib.Path.home().joinpath("Library", "Application Support", "heady")
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def ensure_hide_list_file() -> pathlib.Path:
    p = ensure_config_directory().joinpath("hidelist")
    if not p.exists():
        p.touch()
    return p


def get_hide_list() -> Set[str]:
    res = set()
    with ensure_hide_list_file().open("r") as f:
        for line in f.readlines():
            res.add(line.strip())
    return res


if __name__ == "__main__":
    main()
