# `git contrib`: the scripts as one Git command

## In plain words

The five scripts can also be run as one Git command, `git contrib`, from inside the
project's repository:

| Command                 | Runs                  | Answers                                    |
|-------------------------|-----------------------|--------------------------------------------|
| `git contrib shares`    | `author_shares.py`    | What is each author's fair share?          |
| `git contrib profile`   | `author_profile.py`   | How big is one author's contribution?      |
| `git contrib surviving` | `surviving_text.py`   | Which of one author's text is still there? |
| `git contrib removed`   | `removed_text.py`     | Which of one author's text was removed?    |
| `git contrib highlight` | `highlight_author.py` | Where in the project is one author's text? |

Each takes the same options as its script; inside the repository you can leave out
`--repo`, and after telling Git the main file once, `--main` too:

    cd ~/books/graphs
    git config contrib.main book.tex
    git contrib shares
    git contrib profile --author 'kowalski'

`git contrib -h` lists the subcommands, `git contrib shares --help` shows the options of
one of them, and `git contrib --help` (or `man git-contrib`) shows the manual page.

## Installation

    ./install.sh --install

links `git-contrib` into `~/.local/bin` and the manual page into
`~/.local/share/man/man1`.  The links point back into this directory, so updating the
scripts updates the command.  `./install.sh --uninstall` removes the two links.

The installer is deliberately simple: Linux only, and it stops with a message instead of
guessing when something is unusual -- `~/.local/bin` missing or not on `PATH`,
`~/.local/share/man` missing or not on the manual path, `python3`, `git`,
`git-filter-repo` or `manpath` missing, or a file already in place that is not its own
link.

## Details

- **Which repository.**  `git contrib` measures the repository containing the current
  directory, or the one given with `git -C DIR contrib ...` or `--repo DIR`.
- **`--git-dir` and `--work-tree` do not work.**  The scripts remove every `GIT_*`
  variable from the environment before running git, so that git can never be pointed at
  the measured repository by accident; `git --git-dir=...` passes the repository exactly
  that way, so `git contrib` refuses to run when `GIT_DIR` or `GIT_WORK_TREE` is set.
  Use `-C` or `--repo` instead.
- **The main file.**  `--main` defaults to `git config contrib.main` of the measured
  repository (the same default applies when the scripts are run directly).  Setting it
  writes to that repository's `.git/config`; the scripts themselves never do.
- **Running a subcommand without options** runs it with all defaults (one-author
  subcommands still need `--author`).  Running a script directly without options prints
  its usage instead.
- **Help.**  `git contrib --help` never reaches `git contrib`: Git turns it into
  `git help contrib`, which shows the manual page `man/git-contrib.1`.  That is why the
  page is installed.
- **The subcommand is a positional argument**, the one exception to the scripts' rule of
  options only, following Git's convention.
