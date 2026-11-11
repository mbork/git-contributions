#!/usr/bin/env python3
# * Overview
"""git contrib: the five contribution scripts as one Git command.

Installed (by install.sh) as git-contrib on PATH, so that `git contrib SUBCOMMAND ...` runs
the script of SUBCOMMAND with the remaining arguments.  The scripts stay runnable on their
own.  See docs/git-contrib.md and man/git-contrib.1."""

# * Imports
import importlib
import os
import sys
from pathlib import Path

# The scripts and the contrib package sit next to the real file, wherever the link is.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contrib import cli  # noqa: E402 -- needs the path above

# * Subcommands
SUBCOMMANDS = {
    'shares': ('author_shares', "every author's fair share, in percent"),
    'profile': ('author_profile', "one author's contribution measured many ways"),
    'surviving': ('surviving_text', "one author's text still in the project"),
    'removed': ('removed_text', "one author's text that did not survive"),
    'highlight': ('highlight_author', "the project with one author's words highlighted"),
}
# git --git-dir and --work-tree set these; the scripts drop every GIT_* variable (so that
# git cannot be pointed at the original repository by accident), so they would be ignored.
UNSUPPORTED_VARIABLES = ('GIT_DIR', 'GIT_WORK_TREE')


def usage():
    width = max(len(name) for name in SUBCOMMANDS)
    lines = ['usage: git contrib SUBCOMMAND [OPTIONS]', '',
             "Measure authors' contributions to a LaTeX project kept in Git.", '',
             'subcommands:']
    lines += [f'  {name:<{width}}  {summary}' for name, (_, summary) in SUBCOMMANDS.items()]
    lines += ['', 'git contrib SUBCOMMAND --help shows the options of SUBCOMMAND;'
              ' man git-contrib shows the manual.']
    return '\n'.join(lines)


# * Main
def main():
    arguments = sys.argv[1:]
    if not arguments or arguments[0] in ('-h', '--help'):
        print(usage(), file=sys.stderr)
        sys.exit(0 if arguments else 2)
    name = arguments[0]
    if name not in SUBCOMMANDS:
        print(f'git contrib: unknown subcommand {name!r}\n\n{usage()}', file=sys.stderr)
        sys.exit(2)
    present = [variable for variable in UNSUPPORTED_VARIABLES if variable in os.environ]
    if present:
        print(f'git contrib: {" and ".join(present)} set (by git --git-dir or --work-tree?),'
              ' which git contrib does not support; use git -C DIR, or --repo DIR, instead',
              file=sys.stderr)
        sys.exit(2)
    module = importlib.import_module(SUBCOMMANDS[name][0])
    cli.PROG = f'git contrib {name}'
    cli.DOES_RUN_WITHOUT_ARGUMENTS = True
    sys.argv = [sys.argv[0], *arguments[1:]]
    cli.run(module.main)


if __name__ == '__main__':
    main()
