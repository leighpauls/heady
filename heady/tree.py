import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import git
import humanize

from heady import config
from heady.repo import HeadyRepo


@dataclass(frozen=True)
class Upstream:
    name: str
    remote_sha: Optional[str]
    remote_commit_datetime: Optional[datetime.datetime]


@dataclass
class CommitNode:
    commit: git.Commit
    children: List["CommitNode"]
    is_hidden: bool
    upstreams: Set[Upstream]
    refs: Set[str]
    merged_upstream_shas: Set[str]
    in_trunk: bool

    def __init__(
        self,
        commit: git.Commit,
        is_hidden: bool,
        upstreams: Set[Upstream],
        refs: Set[str],
        in_trunk: bool,
    ):
        self.commit = commit
        self.children = []
        self.is_hidden = is_hidden
        self.upstreams = upstreams
        self.refs = refs
        self.merged_upstream_shas = set()
        self.in_trunk = in_trunk

    def print_tree(self) -> None:
        self._print_many_children("")
        self._print_self("")
        print(":")

    def _print_tree(self, indent: str) -> None:
        self._print_children(indent)
        self._print_self(indent)

    def _print_children(self, indent: str) -> None:
        if len(self.children) == 1:
            self._print_single_child(indent)
        elif len(self.children) > 1:
            self._print_many_children(indent)

    def _print_single_child(self, indent: str) -> None:
        self.children[0]._print_tree(indent)

    def _print_many_children(self, indent: str) -> None:
        sorted_children: List[CommitNode] = list(
            sorted(
                self.children, key=lambda node: node.commit.committed_date, reverse=True
            )
        )
        is_first = not self.in_trunk
        for child in sorted_children:
            new_indent = " " if is_first else "|"
            child._print_tree(indent + new_indent + " ")
            print(indent + new_indent + "/")
            is_first = False

    def _print_self(self, indent: str) -> None:
        short_message = self.commit.message.split("\n", 1)[0]
        if self.commit.repo.head.commit == self.commit:
            dot_char = "@"
        elif self.in_trunk:
            dot_char = "o"
        elif self.is_hidden:
            dot_char = "."
        elif self.merged_upstream_shas:
            dot_char = "x"
        else:
            dot_char = "*"

        upstream_names = [u.name for u in self.upstreams]
        upstream_str = " [" + ", ".join(upstream_names) + "]" if upstream_names else ""
        ref_str = " (" + ", ".join(self.refs) + ")" if self.refs else ""
        hex_str = self.commit.hexsha[:8]
        age_string = humanize.naturaltime(
            datetime.datetime.now()
            - datetime.datetime.fromtimestamp(self.commit.committed_date)
        )

        upstream_info_str = ""
        if not self.in_trunk:
            if self.merged_upstream_shas:
                upstream_info_str = (
                    "| merged as: "
                    + ", ".join(
                        [merged_sha[:8] for merged_sha in self.merged_upstream_shas]
                    )
                    if self.merged_upstream_shas
                    else ""
                )
            elif self.upstreams:
                if sum(up.remote_sha is None for up in self.upstreams):
                    upstream_info_str = "| Not in remote"
                elif sum(up.remote_sha != self.commit.hexsha for up in self.upstreams):
                    if sum(
                        up.remote_commit_datetime
                        and self.commit.committed_datetime > up.remote_commit_datetime
                        for up in self.upstreams
                    ):
                        upstream_info_str = "| Remote Older"
                    else:
                        upstream_info_str = "| Remote Newer"
                else:
                    upstream_info_str = "| Remote up-to-date"

        print(
            f"{indent}{dot_char} {hex_str}{upstream_str}{ref_str} {age_string} {upstream_info_str}"
        )
        print(f"{indent}| {' ' * len(hex_str)} {short_message}")
        print(f"{indent}| ")


@dataclass
class HeadyTree:
    commit_nodes: Dict[str, CommitNode]
    trunk_nodes: List[CommitNode]
    amend_source_map: Dict[str, str]
    visible_upstreams: Dict[str, List[str]]


def build_tree(r: HeadyRepo) -> HeadyTree:
    reflog: git.RefLog = r.repo.head.log()
    cur_time = datetime.datetime.now()
    max_age = datetime.timedelta(days=14)

    hide_list_shas = config.get_hide_list(r.repo)
    tip_shas = set()

    amended_shas = set()
    amend_source_map = {}

    moved_shas = set()
    move_source_map = {}

    # Find tips from the reflog
    item: git.RefLogEntry
    for item in reversed(reflog):
        # Hide shas which have been amended since the last time they were visited
        if item.message.startswith("commit (amend):"):
            amended_shas.add(item.oldhexsha)
            amend_source_map[item.newhexsha] = item.oldhexsha

        if item.message.startswith("heady move:"):
            moved_shas.add(item.oldhexsha)
            move_source_map[item.newhexsha] = item.oldhexsha

        time_seconds, _offset = item.time
        item_time = datetime.datetime.fromtimestamp(time_seconds)
        age = cur_time - item_time
        if age > max_age:
            break
        item_sha = item.newhexsha
        if (
            item_sha not in hide_list_shas
            and item_sha not in amended_shas
            and item_sha not in moved_shas
        ):
            tip_shas.add(item_sha)

    # Find tips from special branches
    special_branches: Dict[str, Set[str]] = dict()
    for local_head in r.repo.heads:
        sha = local_head.commit.hexsha
        tip_shas.add(sha)
        special_branches.setdefault(sha, set()).add(local_head.path)
    for trunk_ref in r.trunk_refs:
        special_branches.setdefault(r.repo.commit(trunk_ref).hexsha, set()).add(
            trunk_ref
        )

    # Find tips which can't merge with trunk
    tips_to_exclude = set()
    for tip_sha in tip_shas:
        for trunk_ref in r.trunk_refs:
            try:
                r.repo.git.merge_base(tip_sha, trunk_ref)
            except git.CommandError as e:
                if e.status != 1:
                    raise
                print(
                    f"Tip {tip_sha} has no merge base with trunk {trunk_ref}. Excluding it."
                )
                tips_to_exclude.add(tip_sha)
                break

    tip_shas.difference_update(tips_to_exclude)

    rev_list_cmds = list(tip_shas) + [f"^{trunk_ref}" for trunk_ref in r.trunk_refs]
    rev_list_output = r.repo.git.rev_list(*rev_list_cmds)
    branch_commit_shas = set(rev_list_output.split("\n")) if rev_list_output else set()

    branch_commits: List[git.Commit] = [
        r.repo.commit(sha) for sha in branch_commit_shas
    ]

    visible_upstream_shas: Dict[str, List[str]] = {}

    def make_node(commit: git.Commit, in_trunk: bool) -> CommitNode:
        is_hidden = (
            commit.hexsha in hide_list_shas
            or commit.hexsha in moved_shas
            or commit.hexsha in amended_shas
        )
        upstream_names = get_upstream_names(commit)

        upstreams = set()
        for upstream_name in upstream_names:
            if not is_hidden:
                sha_set = visible_upstream_shas.setdefault(upstream_name, [])
                sha_set.append(commit.hexsha)

            try:
                upstream_commit = r.repo.commit(f"{r.remote}/{upstream_name}")
            except (git.BadObject, git.BadName):
                upstreams.add(Upstream(upstream_name, None, None))
            else:
                upstreams.add(
                    Upstream(
                        upstream_name,
                        upstream_commit.hexsha,
                        upstream_commit.committed_datetime,
                    )
                )

        return CommitNode(
            commit,
            is_hidden=is_hidden,
            upstreams=upstreams,
            refs=special_branches.get(commit.hexsha, set()),
            in_trunk=in_trunk,
        )

    # build the node objects
    commit_nodes: Dict[str, CommitNode] = {}
    for bc in branch_commits:
        commit_nodes[bc.hexsha] = make_node(bc, False)

    # Add the trunk nodes
    trunk_nodes: Dict[str, CommitNode] = {}
    for trunk_ref in r.trunk_refs:
        trunk_commit = r.repo.commit(trunk_ref)
        trunk_nodes[trunk_commit.hexsha] = make_node(trunk_commit, True)

    # link the node objects
    for node in commit_nodes.values():
        try:
            parent_commit = node.commit.parents[0]
        except:
            print(f"Error finding parent of {node.commit}")
            raise
        parent_sha = parent_commit.hexsha
        if parent_sha not in commit_nodes:
            if parent_sha not in trunk_nodes:
                trunk_nodes[parent_sha] = make_node(parent_commit, True)
            trunk_nodes[parent_sha].children.append(node)
        else:
            commit_nodes[parent_sha].children.append(node)

    ordered_tree = sorted(
        trunk_nodes.values(), key=lambda n: n.commit.committed_datetime, reverse=True
    )

    oldest_trunk_node = ordered_tree[-1]
    merged_upstreams = collect_merged_upstreams(r, oldest_trunk_node.commit)

    for commit_node in commit_nodes.values():
        for upstream in commit_node.upstreams:
            commit_node.merged_upstream_shas.update(
                merged_upstreams.get(upstream.name, [])
            )

    return HeadyTree(
        commit_nodes, ordered_tree, amend_source_map, visible_upstream_shas
    )


def print_tree(r: HeadyRepo, t: HeadyTree) -> None:
    for node in t.trunk_nodes:
        node.print_tree()


def collect_subtree_shas(node: CommitNode, dest: Set[str]) -> None:
    sha = node.commit.hexsha
    if sha in dest:
        return
    dest.add(sha)
    for child in node.children:
        collect_subtree_shas(child, dest)


def get_upstream_names(commit: git.Commit) -> Set[str]:
    result = set()
    for line in commit.message.split("\n"):
        if not line.startswith("upstream:"):
            continue
        result.add(line.split(":", 1)[1].strip())
    return result


def collect_merged_upstreams(
    r: HeadyRepo, oldest_trunk_commit: git.Commit
) -> Dict[str, List[str]]:
    """Returns a map of upstream name to merged commit."""
    trunk_parent_sha = oldest_trunk_commit.parents[0].hexsha

    visited_trunk_shas = set()
    upstreams_in_trunk = {}
    for trunk_ref in r.trunk_refs:
        for trunk_commit in r.repo.iter_commits(f"{trunk_parent_sha}..{trunk_ref}"):
            trunk_commit_sha = trunk_commit.hexsha
            if trunk_commit_sha in visited_trunk_shas:
                continue
            visited_trunk_shas.add(trunk_commit_sha)

            for upstream_name in get_upstream_names(trunk_commit):
                commit_list = upstreams_in_trunk.setdefault(upstream_name, [])
                commit_list.append(trunk_commit.hexsha)

    return upstreams_in_trunk
