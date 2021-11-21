import argparse
import pathlib
from pprint import pprint
from typing import List

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
        default="origin/main",
        help="Trunk reference. Usually origin/main or origin/master",
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

    r = HeadyRepo(args.trunk, git.Repo(repo_path))

    args.func(r, args)


def tree_cmd(r: HeadyRepo, _args: argparse.Namespace) -> None:
    print_tips_tree(r)


def hide_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    revs: List[str] = args.revs
    hide_subtrees(r, revs)


def unhide_cmd(r: HeadyRepo, args: argparse.Namespace) -> None:
    revs: List[str] = args.revs
    unhide_revs(r, revs)

def hide_subtrees(r: HeadyRepo, hide_root_refs: List[str]) -> None:
    # Raises if the hide root doesn't exist

    hide_root_commits = []
    for hide_root_ref in hide_root_refs:
        hide_root_commit = r.repo.commit(hide_root_ref)

        # Verify that we are not attempting to hide a commit in trunk
        if is_ancestor(r, hide_root_ref, r.trunk_ref):
            raise ValueError(
                f"Can not hide {hide_root_ref} because it would hide {r.trunk_ref}"
            )

        if is_ancestor(r, hide_root_ref, "HEAD"):
            raise ValueError(f"Can not hide {hide_root_ref} because it would hide HEAD")

        hide_root_commits.append(hide_root_commit
                                 )
    # Find all the child nodes in the tree to hide
    t = tree.build_tree(r)
    shas_to_hide = set()
    for hide_root_commit in hide_root_commits:
        hide_root_sha = hide_root_commit.hexsha
        if hide_root_sha not in t.commit_nodes:
            raise ValueError(f"Did not find {hide_root_sha} in the visible tree")
        tree.collect_subtree_shas(t.commit_nodes[hide_root_sha], shas_to_hide)

    nodes_to_remove = shas_to_hide - config.get_hide_list(r.repo)

    print("nodes to hide")
    pprint(nodes_to_remove)
    config.append_to_hide_list(r.repo, nodes_to_remove)

def unhide_revs(r: HeadyRepo, unhide_revs: List[str]) -> None:
    new_hide_list = config.get_hide_list(r.repo)
    for rev in unhide_revs:
        # Raises if the hide root doesn't exist
        unhide_sha = r.repo.commit(rev).hexsha
        if unhide_sha not in new_hide_list:
            raise ValueError(f'Can not unhide {rev} because it is not hidden')
        else:
            new_hide_list.remove(unhide_sha)

    config.replace_hide_list(r.repo, new_hide_list)


def is_ancestor(r: HeadyRepo, ancestor_ref: str, descendent_ref: str):
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
