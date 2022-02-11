from pprint import pprint
from typing import List, Optional, Set

import git

from heady import config, parsing, tree
from heady.repo import HeadyRepo


def main() -> None:
    commands = parsing.Commands()

    commands.add_subparser(
        "tree",
        help="Show the tree of visible heads.",
        execute=lambda r, args: print_tips_tree(r),
    )

    commands.add_subparser(
        "hide",
        help="Hide the subtree from this revision",
        execute=lambda r, args: hide_subtrees(r, args.revs),
    ).add_argument("revs", type=str, nargs="+")

    commands.add_subparser(
        "unhide",
        help="Hide the subtree from this revision",
        execute=lambda r, args: unhide_revs(r, args.revs),
    ).add_argument("revs", type=str, nargs="+")

    commands.add_subparser(
        "move",
        help="Move a subtree of commitss",
        execute=lambda r, args: move_commits(r, args.source_root, args.dest_parent),
    ).add_argument(
        "source_root", type=str, help="Root of the subtree to move."
    ).add_argument(
        "dest_parent", type=str, help="New parent of the subtree."
    )

    commands.add_subparser(
        "goto",
        help="Check out a revision using tree directions.",
        execute=lambda r, args: goto_commit(r, args.command, args.upstream),
    ).add_argument(
        "command", type=str, choices=["next", "prev", "tip", "upstream"]
    ).add_argument(
        "upstream",
        type=str,
        nargs="?",
        default=None,
        help="The upstream to goto. use with 'upstream' option",
    )

    commands.add_subparser(
        "fixup",
        help="Move children of any amended revisions of HEAD",
        execute=lambda r, args: fixup_commit(r),
    )

    commands.add_subparser(
        "upstream",
        help="Add an upstream branch to the commit.",
        execute=lambda r, args: add_upstream(r, args.upstream_ref, args.rev),
    ).add_argument(
        "upstream_ref",
        type=str,
        help="The upstream branch name to target.",
    ).add_argument(
        "rev", type=str, default="HEAD", nargs="?", help="The local revision to label."
    )

    commands.add_subparser(
        "upstream",
        help="Add an upstream branch to the commit.",
        execute=lambda r, args: add_upstream(r, args.upstream_ref, args.rev),
    ).add_argument(
        "upstream_ref",
        type=str,
        help="The upstream branch name to target.",
    ).add_argument(
        "rev", type=str, default="HEAD", nargs="?", help="The local revision to label."
    )

    commands.add_subparser(
        "push",
        help="Push commits with upstreams in the specified subtree.",
        execute=lambda r, args: push_commits(r, args.remote, args.rev),
    ).add_argument(
        "--remote", type=str, default="origin", help="Remote to push to."
    ).add_argument(
        "rev",
        type=str,
        default="HEAD",
        nargs="?",
        help="Push this commit and any children of this commit.",
    )

    commands.add_subparser(
        "pr",
        help="Provide link to create stacked PR.",
        execute=lambda r, args: print_pr_links(r, args.rev),
    ).add_argument(
        "rev", type=str, nargs="?", default="HEAD", help="Commit to create the PR of."
    )

    commands.add_subparser(
        "autohide",
        help="Hide commits whose upstreams are merged to trunk.",
        execute=lambda r, args: auto_hide(r),
    )

    commands.execute()


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
    print("Pushing:")
    for p in push_order:
        print(p)
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
            print(
                f"https://github.com/Nextdoor/nextdoor.com/compare/{upstream}?expand=1"
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
        for parent_upstream in parent_commit_node.upstreams:
            print(
                f"https://github.com/Nextdoor/nextdoor.com/compare/{parent_upstream}...{upstream}?expand=1"
            )


def auto_hide(r: HeadyRepo) -> None:
    t = tree.build_tree(r)
    print(tree.collect_merged_upstreams(r, t.trunk_nodes[-1].commit))


def _plan_push(remote: str, node: tree.CommitNode) -> List[str]:
    result = []
    for upstream in node.upstreams:
        result.append(f"{node.commit.hexsha}:refs/heads/{upstream}")
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
    tree.print_tree(r, t)


if __name__ == "__main__":
    main()
