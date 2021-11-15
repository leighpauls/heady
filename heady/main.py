import argparse
import pathlib

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
    hide_parser.add_argument("rev", type=str)
    hide_parser.set_defaults(func=hide_cmd)

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
    hide_subtree(r, args.rev)


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
    t = tree.build_tree(r)
    hide_root_sha = hide_root_commit.hexsha
    if hide_root_sha not in t.commit_nodes:
        raise ValueError(f"Did not find {hide_root_sha} in the visible tree")

    existing_hidden_tips = config.get_hide_list(r.repo)
    new_hidden_shas = []
    for new_hide_sha in tree.collect_subtree_shas(t.commit_nodes[hide_root_sha]):
        if new_hide_sha not in existing_hidden_tips:
            new_hidden_shas.append(new_hide_sha)

    config.append_to_hide_list(r.repo, new_hidden_shas)


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
