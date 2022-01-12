import argparse
import pathlib
import re
from pprint import pprint
from typing import List, Optional, Set

import git

from heady import config, tree
from heady.repo import HeadyRepo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        default=None,
        help="Location of the repo. Will use cwd if not provided.",
    )
    parser.add_argument(
        "--trunk",
        default="origin/main,origin/stable",
        help="Trunk references. Comma separated. Usually origin/main or origin/master",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    tree_parser = subparsers.add_parser("tree", help="Show the tree of visible heads.")
    tree_parser.set_defaults(func=tree_cmd)

    hide_parser = subparsers.add_parser(
        "hide", help="Hide the subtree from this revision"
    )
    hide_parser.add_argument("revs", type=str, nargs="+")
    hide_parser.set_defaults(func=hide_cmd)

    hide_parser = subparsers.add_parser(
        "unhide", help="Hide the subtree from this revision"
    )
    hide_parser.add_argument("revs", type=str, nargs="+")
    hide_parser.set_defaults(func=unhide_cmd)

    move_parser = subparsers.add_parser("move", help="Move a subtree of commitss")
    move_parser.set_defaults(func=move_cmd)
    move_parser.add_argument(
        "source_root", type=str, help="Root of the subtree to move."
    )
    move_parser.add_argument("dest_parent", type=str, help="New parent of the subtree.")

    goto_parser = subparsers.add_parser(
        "goto", help="Check out a revision using tree directions."
    )
    goto_parser.set_defaults(func=goto_cmd)
    goto_parser.add_argument(
        "command", type=str, choices=["next", "prev", "tip", "upstream"]
    )
    goto_parser.add_argument(
        "upstream",
        type=str,
        nargs="?",
        default=None,
        help="The upstream to goto. use with 'upstream' option",
    )

    fixup_parser = subparsers.add_parser(
        "fixup", help="Move children of any amended revisions of HEAD"
    )
    fixup_parser.set_defaults(func=fixup_cmd)

    upstream_parser = subparsers.add_parser(
        "upstream", help="Add an upstream branch to the commit."
    )
    upstream_parser.set_defaults(func=upstream_cmd)
    upstream_parser.add_argument(
        "upstream_ref",
        type=str,
        help="The upstream ref to target. In the form of <remote>/<branch>",
    )
    upstream_parser.add_argument(
        "rev", type=str, default="HEAD", nargs="?", help="The local revision to label."
    )

    push_parser = subparsers.add_parser(
        "push", help="Push commits with upstreams in the specified subtree."
    )
    push_parser.set_defaults(func=push_cmd)
    push_parser.add_argument("remote", type=str, help="Remote to push to.")
    push_parser.add_argument(
        "rev",
        type=str,
        default="HEAD",
        nargs="?",
        help="Push this commit and any children of this commit.",
    )

    pr_parser = subparsers.add_parser("pr", help="Provide link to create stacked PR.")
    pr_parser.set_defaults(func=pr_cmd)
    pr_parser.add_argument(
        "rev", type=str, nargs="?", default="HEAD", help="Commit to create the PR of."
    )

    args = parser.parse_args()

    original_repo_path = (
        pathlib.Path(args.repo).expanduser().resolve()
        if args.repo
        else pathlib.Path.cwd()
    )
    repo_path = original_repo_path

    while True:
        if repo_path.is_dir() and repo_path.joinpath(".git").exists():
            break
        if repo_path.parent == repo_path:
            raise ValueError(f"No git repo present in {original_repo_path}")
        repo_path = repo_path.parent

    r = HeadyRepo(args.trunk.split(","), git.Repo(repo_path))

    args.func(r, args)


def tree_cmd(r: HeadyRepo, _args: argparse.Namespace) -> None:
    print_tips_tree(r)


def hide_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    revs: List[str] = args.revs
    hide_subtrees(r, revs)


def unhide_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    revs: List[str] = args.revs
    unhide_revs(r, revs)


def move_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    move_commits(r, args.source_root, args.dest_parent)


def goto_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    goto_commit(r, args.command, args.upstream)


def fixup_cmd(r: HeadyRepo, _args: argparse.Namespace) -> None:
    fixup_commit(r)


def upstream_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    add_upstream(r, args.upstream_ref, args.rev)


def push_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    push_commits(r, args.remote, args.rev)


def pr_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    print_pr_links(r, args.rev)


def hide_subtrees(r: HeadyRepo, hide_root_refs: List[str]) -> None:
    # Raises if the hide root doesn't exist

    hide_root_commits = []
    for hide_root_ref in hide_root_refs:
        hide_root_commit = r.repo.commit(hide_root_ref)

        # Verify that we are not attempting to hide a commit in trunk
        if is_in_trunk(r, hide_root_ref):
            raise ValueError(
                f"Can not hide {hide_root_ref} because it would hide a truck ref."
            )

        if is_ancestor(r, hide_root_ref, "HEAD"):
            raise ValueError(
                f"Can not hide {hide_root_ref} because it would hide HEAD."
            )

        hide_root_commits.append(hide_root_commit)
    # Find all the child nodes in the tree to hide
    t = tree.build_tree(r)
    shas_to_hide = set()
    for hide_root_commit in hide_root_commits:
        hide_root_sha = hide_root_commit.hexsha
        if hide_root_sha not in t.commit_nodes:
            print(f"Did not find {hide_root_sha} in the visible tree, skipping it.")
        else:
            tree.collect_subtree_shas(t.commit_nodes[hide_root_sha], shas_to_hide)

    nodes_to_remove = shas_to_hide - config.get_hide_list(r.repo)

    print("Hiding:")
    pprint(nodes_to_remove)
    config.append_to_hide_list(r.repo, nodes_to_remove)


def unhide_revs(r: HeadyRepo, unhide_revs: List[str]) -> None:
    new_hide_list = config.get_hide_list(r.repo)
    for rev in unhide_revs:
        # Raises if the hide root doesn't exist
        unhide_sha = r.repo.commit(rev).hexsha
        if unhide_sha not in new_hide_list:
            print(f"Can not unhide {rev} because it is not hidden")
        else:
            new_hide_list.remove(unhide_sha)

    config.replace_hide_list(r.repo, new_hide_list)


def add_upstream(r: HeadyRepo, upstream_ref: str, rev: str) -> None:
    t = tree.build_tree(r)

    source_commit = r.repo.commit(rev)
    if is_in_trunk(r, rev):
        raise ValueError(f"Can not add upstream to {rev} because it is in trunk.")

    if source_commit.hexsha not in t.commit_nodes:
        raise ValueError(
            f"Can not add upstream to {rev} because it is not visible in the tree"
        )

    upstream_pattern = re.compile(r"^(?P<remote>.+?)/(?P<branch>.+)$")
    upstream_parts = upstream_pattern.match(upstream_ref)
    if upstream_parts is None:
        raise ValueError(f"Upstream ref must be in the format <remote>/<branch>")
    upstream_name = upstream_parts["remote"]

    if upstream_name not in r.repo.remotes:
        raise ValueError(f"Remote {upstream_name} not found.")

    _visit_commit(r, source_commit)
    new_message = f"{source_commit.message}\nupstream: {upstream_ref}\n"

    r.repo.git.commit(message=new_message, amend=True, no_verify=True)
    amended_commit = r.repo.head.commit
    _move_children_to_head(r, t, source_commit)
    _visit_commit(r, amended_commit)


def move_commits(r: HeadyRepo, source: str, dest: str) -> None:
    source_commit = r.repo.commit(source)
    dest_commit: git.Commit = r.repo.commit(dest)
    if is_in_trunk(r, source):
        raise ValueError(f"Can't move {source} because it's in trunk.")

    t = tree.build_tree(r)
    if source_commit.hexsha not in t.commit_nodes:
        raise ValueError(f"Can't move {source} because it's not visible in the tree.")

    _visit_commit(r, dest_commit)
    _move_commits_recursive(r, t, source_commit)


def goto_commit(r: HeadyRepo, command: str, upstream: Optional[str]) -> None:
    t = tree.build_tree(r)

    if command == "upstream":
        if not upstream:
            raise ValueError("No upstream provided.")
        upstreams = t.visible_upstreams.get(upstream)
        if not upstreams:
            raise ValueError(
                f"No vissible commits marked with upstream {upstream} found."
            )
        if len(upstreams) > 1:
            raise ValueError(
                f"Found multiple visible commits are marked with {upstream}. Hide all but one and try again: {upstreams}"
            )
        _visit_commit(r, t.commit_nodes[upstreams[0]].commit)
        return
    elif upstream is not None:
        raise ValueError(
            "<upstream> arg is only allowed for command 'goto upstream ...'"
        )

    head_commit = r.repo.head.commit
    head_node = t.commit_nodes[head_commit.hexsha]

    if command == "prev":
        parent_commit = head_commit.parents[0]
        _visit_commit(r, parent_commit)
    elif command == "next":
        children = head_node.children
        if len(children) > 1:
            raise ValueError(
                "Can't 'goto next' from node with more than 1 child in tree."
            )
        elif len(children) == 0:
            raise ValueError("Can't 'goto next' from node without a child.")

        _visit_commit(r, head_node.children[0].commit)
    elif command == "tip":
        cur_node = head_node
        while cur_node.children:
            if len(cur_node.children) > 1:
                raise ValueError("Can't 'goto tip' from node with more than 1 tip.")
            cur_node = cur_node.children[0]
        _visit_commit(r, cur_node.commit)


def fixup_commit(r: HeadyRepo) -> None:
    t = tree.build_tree(r)
    starting_head_commit = r.repo.head.commit
    head_commit_sha = r.repo.head.commit.hexsha

    amend_source_sha = t.amend_source_map.get(head_commit_sha)
    if not amend_source_sha:
        print(f"No amend history found for {head_commit_sha}")
        return

    amend_source_children_shas: Set[str] = set()

    while amend_source_sha:
        source_node = t.commit_nodes.get(amend_source_sha)
        if source_node:
            visible_children_shas = {
                ch.commit.hexsha for ch in source_node.children if not ch.is_hidden
            }
            amend_source_children_shas |= visible_children_shas
        amend_source_sha = t.amend_source_map.get(amend_source_sha)

    if not amend_source_children_shas:
        print(f"No children found for amend history of {head_commit_sha}")
        return

    for source_child_sha in amend_source_children_shas:
        _visit_commit(r, starting_head_commit)
        _move_commits_recursive(r, t, t.commit_nodes[source_child_sha].commit)
    _visit_commit(r, starting_head_commit)


def push_commits(r: HeadyRepo, remote: str, rev: str) -> None:
    t = tree.build_tree(r)

    root_commit = r.repo.commit(rev)
    root_node = t.commit_nodes.get(root_commit.hexsha)
    if root_node is None:
        raise ValueError(f"Did not find {rev} in tree.")

    if remote not in r.repo.remotes:
        raise ValueError(f"Remote {remote} not specified in this repository.")

    push_order = _plan_push(remote, root_node)
    r.repo.git.push(remote, *push_order, force_with_lease=True, no_verify=True)


def print_pr_links(r: HeadyRepo, rev: str) -> None:
    t = tree.build_tree(r)
    target_commit = r.repo.commit(rev)
    target_node = t.commit_nodes.get(target_commit.hexsha)
    if not target_node:
        raise ValueError(f"Could not find {rev} in tree.")
    if not target_node.upstreams:
        raise ValueError(f"Rev {rev} has no associated upstream branches.")

    parent_commit_sha = target_commit.parents[0].hexsha

    if is_in_trunk(r, parent_commit_sha):
        for upstream in target_node.upstreams:
            remote_branch = upstream[upstream.find("/") + 1 :]
            print(
                f"https://github.com/Nextdoor/nextdoor.com/compare/{remote_branch}?expand=1"
            )
        return

    parent_commit_node = t.commit_nodes.get(parent_commit_sha)
    if not parent_commit_node:
        raise ValueError(f"Couldn't find suitable base branch from {parent_commit_sha}")
    if not parent_commit_node.upstreams:
        raise ValueError(
            f"Parent commit {parent_commit_sha} has no associated upstream branches."
        )

    for upstream in target_node.upstreams:
        remote_branch = upstream[upstream.find("/") + 1 :]
        for parent_upstream in parent_commit_node.upstreams:
            parent_remote_branch = parent_upstream[parent_upstream.find("/") + 1 :]
            print(
                f"https://github.com/Nextdoor/nextdoor.com/compare/{parent_remote_branch}...{remote_branch}?expand=1"
            )


def _plan_push(remote: str, node: tree.CommitNode) -> List[str]:
    result = []
    for upstream in node.upstreams:
        if upstream.startswith(f"{remote}/"):
            remote_branch = upstream[upstream.find("/") + 1 :]
            result.append(f"{node.commit.hexsha}:refs/heads/{remote_branch}")
    for ch in node.children:
        result.extend(_plan_push(remote, ch))
    return result


def _move_commits_recursive(
    r: HeadyRepo, t: tree.HeadyTree, source: git.Commit
) -> None:
    source_sha = source.hexsha
    print(f"Cherry pick {source_sha}.")
    r.repo.git.cherry_pick(source_sha)
    new_commit = r.repo.head.commit

    print(f"Record move {source_sha} to {new_commit.hexsha}")
    # config.append_to_hide_list(r.repo, [source_sha])

    # record the move by making a reflog entry
    r.repo.head.set_reference(source_sha)
    r.repo.head.set_reference(new_commit, f"heady move: {source_sha}")

    _move_children_to_head(r, t, source)


def _move_children_to_head(
    r: HeadyRepo, t: tree.HeadyTree, source_parent: git.Commit
) -> None:
    base_commit = r.repo.head.commit
    for child_node in t.commit_nodes[source_parent.hexsha].children:
        _move_commits_recursive(r, t, child_node.commit)
        _visit_commit(r, base_commit)


def _visit_commit(r: HeadyRepo, dest: git.Commit) -> None:
    if r.repo.is_dirty():
        raise ValueError(f"Can't move while the repo is dirty.")

    r.repo.head.set_reference(dest, f"heady visit:{dest.hexsha}")
    r.repo.head.reset(index=True, working_tree=True)


def is_in_trunk(r: HeadyRepo, ref: str) -> bool:
    for trunk in r.trunk_refs:
        if is_ancestor(r, ref, trunk):
            return True
    return False


def is_ancestor(r: HeadyRepo, ancestor_ref: str, descendent_ref: str) -> bool:
    # If all commits of ancestor_ref exist in descendent_ref, it must be an ancestor
    missing_lineage = list(
        r.repo.iter_commits(f"{descendent_ref}..{ancestor_ref}", max_count=1)
    )
    return len(missing_lineage) == 0


def print_tips_tree(r: HeadyRepo) -> None:
    t = tree.build_tree(r)
    for node in t.trunk_nodes:
        node.print_tree()


if __name__ == "__main__":
    main()
