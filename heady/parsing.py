import argparse
import pathlib
from typing import Callable

import git

from heady import repo


class Commands:
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument(
            "--repo",
            default=None,
            help="Location of the repo. Will use cwd if not provided.",
        )
        self.parser.add_argument(
            "--trunk",
            default="origin/main,origin/stable",
            help="Trunk references. Comma separated. Usually origin/main or origin/master",
        )
        self.parser.add_argument(
            "--remote", type=str, default="origin", help="Remote used for upstreaming."
        )

        self.subparsers = self.parser.add_subparsers(dest="command", required=True)

    def add_subparser(
        self,
        subcommand_name: str,
        help: str,
        execute: Callable[[repo.HeadyRepo, argparse.Namespace], None],
    ) -> "Subparser":
        subparser = self.subparsers.add_parser(subcommand_name, help=help)
        subparser.set_defaults(func=execute)
        return Subparser(subparser)

    def execute(self) -> None:
        args = self.parser.parse_args()
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

        git_repo = git.Repo(repo_path)
        trunks = []
        for t in args.trunk.split(","):
            try:
                git_repo.commit(t)
                trunks.append(t)
            except git.BadName:
                pass

        if not trunks:
            raise ValueError(f"Unable to find any trunks from {args.trunk}")

        r = repo.HeadyRepo(trunks, git_repo, args.remote)
        args.func(r, args)


class Subparser:
    def __init__(self, subparser: argparse.ArgumentParser):
        self._subparser = subparser

    def add_argument(self, *args, **kwargs) -> "Subparser":
        self._subparser.add_argument(*args, **kwargs)
        return self
