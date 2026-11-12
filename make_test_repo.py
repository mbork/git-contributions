#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# * Overview
"""Build a small synthetic Git repo with a multi-file LaTeX book, to try the scripts on.

The history is scripted so that it covers the cases the scripts must handle: fresh writing,
typo and punctuation fixes, a rewrite of someone else's sentence, moves within a file and
across files (from a file that is not included), removals by the writer and by others,
commenting text out, preamble edits, a file rename, an author alias fixed by .mailmap, an
annotated tag in the middle of history, a branch merged with a conflict resolution, and text
removed by one author and re-added by another.
"""

# * Imports
import argparse
import os
import subprocess
import sys
from pathlib import Path

# * Authors
ALICE = ('Alice Author', 'alice@example.org')
BOB = ('Bob Builder', 'bob@example.org')
BOB_ALIAS = ('bob', 'bob@old.example.org')
CAROL = ('Carol Critic', 'carol@example.org')

MAILMAP = 'Bob Builder <bob@example.org> bob <bob@old.example.org>\n'

# * Book contents
MAIN_TEX = r"""\documentclass{book}
\usepackage{amsmath,amssymb,amsthm}
\input{macros}

\begin{document}
\title{A Short Course in Graph Theory}
\author{Alice Author \and Bob Builder \and Carol Critic}
\maketitle
\tableofcontents

\include{chapters/intro}
\end{document}
"""

MACROS_TEX = r"""\newtheorem{lemma}{Lemma}[chapter]
\newcommand{\N}{\mathbb{N}}
"""

INTRO_TEX = r"""\chapter{Introduction}
\label{chap:intro}

% Rozdział wstępny -- do poprawienia.
This book is an introduction to the theory of finite graphs. We assume that the reader knows basic set theory and is familiar with mathematical induction. Throughout the book, all graphs are finite and simple, unless explicitly stated otherwise.

Graphs appear in many areas of mathematics and computer science, e.g. in the study of networks, in scheduling problems and in chemistry. Let us consider a simple example: a group of people, some of whom know each other, can be described by a graph whose vertices are the people and whose edges join acquaintances.

The book is organised as follows. In Chapter~\ref{chap:basics} we introduce the basic notions and prove the handshake lemma. The appendix contains a short list of open problems which the reader may find interesting.

We thank our colleagues for many helpful discussions and for their patience while this book was being writen.
"""

THEORY_TEX = r"""\chapter{Basic notions}
\label{chap:basics}

\section{Graphs and degrees}

A \emph{graph} is a pair $G=(V,E)$, where $V$ is a finite set of \emph{vertices} and $E$ is a set of two-element subsets of $V$, called \emph{edges}. The \emph{degree} of a vertex $v$, denoted by $\deg v$, is the number of edges containing $v$.

\begin{lemma}[Handshake lemma]
\label{lem:handshake}
For every graph $G=(V,E)$ we have
\begin{equation}
  \sum_{v \in V} \deg v = 2|E|.
\end{equation}
\end{lemma}

\begin{proof}
Every edge contains exactly two vertices, so it is counted exactly twice in the sum on the left-hand side. Hence the sum equals $2|E|$, as claimed.
\end{proof}

It follows that the number of vertices of odd degree is even. Indeed, the sum of all degrees is even, and the vertices of even degree contribute an even number to it.
"""

DRAFT_PARAGRAPH = (r"A \emph{walk} in a graph is a sequence of vertices in which every two"
                   r" consecutive vertices are adjacent. A walk whose vertices are pairwise"
                   r" distinct is called a \emph{path}, and the length of a path is the number"
                   r" of its edges.")

DRAFT_TEX = f"""% Notes for a future section on walks.
{DRAFT_PARAGRAPH}
"""

TREES_SECTION = r"""
\section{Trees}

A \emph{tree} is a connected graph without cycles. Every tree with $n$ vertices has exactly $n-1$ edges; this can be proved by induction on $n$, removing a leaf in the induction step.
"""

APPENDIX_SENTENCE = ('Most of these problems are easy to state but surprisingly hard to'
                     ' solve.')

APPENDIX_TEX = r"""\chapter{Open problems}

Below we list a few questions for the reader. @SENTENCE@ The reader is encouraged to try small cases first.

\begin{enumerate}
\item Is it true that every graph with $n \ge 3$ vertices and minimum degree at least $n/2$ contains a cycle through all its vertices?
\item Find all graphs $G$ for which
\[
  \sum_{v \in V(G)} \deg^2 v = |V(G)| \cdot |E(G)|.
\]
\end{enumerate}

The following identities may help:
\begin{align*}
  \sum_{v \in V} \deg v &= 2|E|, \\
  |E| &\le \binom{|V|}{2}.
\end{align*}

A quick experiment in Python:
\begin{verbatim}
degrees = [3, 1, 2, 2]
print(sum(degrees) % 2)  # always 0
\end{verbatim}
""".replace('@SENTENCE@', APPENDIX_SENTENCE)


# * Git helpers
class Repo:
    """A Git repo built with a fixed, isolated configuration and fake dates."""

    def __init__(self, path):
        self.path = path
        self.day = 0
        # GIT_* variables could point git at another repository.
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith('GIT_')}
        # Ignore the user's and the system's Git configuration (signing, hooks, templates).
        self.env['GIT_CONFIG_GLOBAL'] = os.devnull
        self.env['GIT_CONFIG_SYSTEM'] = os.devnull
        self.env['GIT_CONFIG_NOSYSTEM'] = '1'

    def git(self, *args, author=None, should_check=True):
        env = dict(self.env)
        if author is not None:
            name, email = author
            date = f'2026-01-{self.day + 1:02d}T10:00:00+01:00'
            env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=date,
                       GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email,
                       GIT_COMMITTER_DATE=date)
        result = subprocess.run(['git', *args], cwd=self.path, env=env,
                                capture_output=True, text=True)
        if should_check and result.returncode != 0:
            sys.exit(f'git {" ".join(args)} failed:\n{result.stderr}')
        return result

    def write(self, rel_path, text):
        file_path = self.path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text, encoding='utf-8')

    def read(self, rel_path):
        return (self.path / rel_path).read_text(encoding='utf-8')

    def edit(self, rel_path, old, new):
        """Replace the one occurrence of OLD in REL_PATH by NEW."""
        text = self.read(rel_path)
        count = text.count(old)
        if count != 1:
            sys.exit(f'internal error: {old!r} occurs {count} times in {rel_path}')
        self.write(rel_path, text.replace(old, new))

    def commit(self, author, message=None):
        """Commit everything as AUTHOR; without MESSAGE, conclude a merge with its default."""
        self.git('add', '--all')
        if message is None:
            self.git('commit', '--quiet', '--no-edit', author=author)
        else:
            self.git('commit', '--quiet', '--message', message, author=author)
        self.day += 1
        subject = self.git('log', '-1', '--format=%s').stdout.strip()
        print(f'  {author[0]:<13} {subject}', file=sys.stderr)


# * History
def build_history(repo):
    # ** Before the tag
    repo.git('init', '--quiet', '--initial-branch=main')
    repo.write('main.tex', MAIN_TEX)
    repo.write('macros.tex', MACROS_TEX)
    repo.write('chapters/intro.tex', INTRO_TEX)
    repo.write('.mailmap', MAILMAP)
    repo.commit(ALICE, 'Start the book with an introduction')

    repo.write('chapters/theory.tex', THEORY_TEX)
    repo.edit('main.tex', '\\include{chapters/intro}\n',
              '\\include{chapters/intro}\n\\include{chapters/theory}\n')
    repo.commit(BOB_ALIAS, 'Add the chapter on basic notions')

    repo.edit('chapters/intro.tex', 'being writen.', 'being written.')
    repo.edit('chapters/intro.tex', 'is organised as', 'is organized as')
    repo.commit(CAROL, 'Fix typos in the introduction')

    repo.write('notes-draft.tex', DRAFT_TEX)
    repo.commit(CAROL, 'Draft a paragraph on walks and paths')

    repo.edit('chapters/intro.tex',
              'Let us consider a simple example: a group of people, some of whom know each'
              ' other, can be described by a graph whose vertices are the people and whose'
              ' edges join acquaintances.',
              'For instance, a social network can be modelled by a graph in which the'
              ' vertices represent users and two users are adjacent whenever they are'
              ' friends.')
    repo.commit(BOB, 'Rewrite the example in the introduction')

    thanks = ('We thank our colleagues for many helpful discussions and for their patience'
              ' while this book was being written.\n')
    organization = 'The book is organized as follows.'
    repo.edit('chapters/intro.tex', '\n' + thanks, '')
    repo.edit('chapters/intro.tex', organization, thanks + '\n' + organization)
    repo.commit(ALICE, 'Move the acknowledgments up')

    repo.edit('chapters/theory.tex', '\nIt follows that',
              '\n\\section{Walks and paths}\n\n' + DRAFT_PARAGRAPH + '\n\nIt follows that')
    (repo.path / 'notes-draft.tex').unlink()
    repo.commit(BOB, 'Move the draft on walks into the chapter')

    repo.edit('chapters/intro.tex',
              ' Throughout the book, all graphs are finite and simple, unless explicitly'
              ' stated otherwise.', '')
    repo.commit(ALICE, 'Drop a redundant sentence')

    repo.edit('chapters/intro.tex',
              ' The appendix contains a short list of open problems which the reader may'
              ' find interesting.', '')
    repo.commit(BOB, 'Remove the mention of the appendix')

    repo.edit('main.tex', '\\input{macros}\n', '\\input{macros}\n\\usepackage{hyperref}\n')
    repo.edit('macros.tex', '\\newcommand{\\N}',
              '\\newcommand{\\abs}[1]{\\lvert #1\\rvert}\n\\newcommand{\\N}')
    repo.commit(CAROL, 'Add hyperref and an absolute value macro')

    repo.edit('chapters/intro.tex', thanks, '% TODO: przenieść do przedmowy.\n% ' + thanks)
    repo.commit(BOB, 'Comment out the acknowledgments')

    repo.git('mv', 'chapters/theory.tex', 'chapters/basics.tex')
    repo.edit('main.tex', '\\include{chapters/theory}', '\\include{chapters/basics}')
    repo.commit(ALICE, 'Rename the chapter file')
    repo.git('tag', '--annotate', 'v0.1', '--message', 'First draft', author=ALICE)

    # ** A branch with a conflicting edit
    first_sentence = 'This book is an introduction to the theory of finite graphs.'
    repo.git('switch', '--quiet', '--create', 'trees')
    repo.write('chapters/basics.tex', repo.read('chapters/basics.tex') + TREES_SECTION)
    repo.commit(CAROL, 'Add a section on trees')
    repo.edit('chapters/intro.tex', first_sentence,
              'This book is a gentle introduction to the theory of finite graphs.')
    repo.commit(CAROL, 'Make the first sentence friendlier')

    repo.git('switch', '--quiet', 'main')
    repo.edit('chapters/intro.tex', first_sentence,
              'This book is an elementary introduction to the theory of finite graphs.')
    repo.commit(ALICE, 'Say the book is elementary')

    result = repo.git('merge', '--quiet', '--no-ff', '--no-edit', 'trees', author=BOB,
                      should_check=False)
    if result.returncode == 0:
        sys.exit('internal error: the merge was expected to conflict')
    repo.git('checkout', '--theirs', 'chapters/intro.tex')
    repo.edit('chapters/intro.tex',
              'This book is a gentle introduction to the theory of finite graphs.',
              'This book is a gentle and elementary introduction to graph theory.')
    repo.commit(BOB)

    # ** After the merge
    repo.write('appendix.tex', APPENDIX_TEX)
    repo.edit('main.tex', '\\include{chapters/basics}\n',
              '\\include{chapters/basics}\n\\appendix\n\\input{appendix}\n')
    repo.commit(ALICE, 'Add an appendix with open problems')

    repo.edit('appendix.tex', ' ' + APPENDIX_SENTENCE, '')
    repo.commit(BOB, 'Shorten the appendix introduction')

    repo.edit('appendix.tex', 'for the reader.', 'for the reader. ' + APPENDIX_SENTENCE)
    repo.commit(CAROL, 'Restore a sentence in the appendix')

    repo.edit('chapters/basics.tex', 'Hence the sum', 'Hence, the sum')
    repo.commit(CAROL, 'Add a comma')


# * Command line
def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='make_test_repo.py', add_help=False,
        description='Build a small synthetic Git repo with a multi-file LaTeX book (main file'
                    ' main.tex, three authors, a branch, a merge and a tag v0.1), to try the'
                    ' contribution scripts on.')
    parser.add_argument('--dir', metavar='DIR',
                        help='directory to create the repo in; must not exist yet')
    parser.add_argument('--help', action='help', help='show this message and exit')
    if not argv:
        parser.print_help(sys.stderr)
        sys.exit(2)
    args = parser.parse_args(argv)
    if args.dir is None:
        parser.error('--dir is required')
    return args


# * Main
def main():
    args = parse_args(sys.argv[1:])
    path = Path(args.dir).expanduser().resolve()
    if path.exists():
        sys.exit(f'{path} already exists; choose another --dir or remove it first')
    path.mkdir(parents=True)
    print(f'Building {path}:', file=sys.stderr)
    build_history(Repo(path))
    print(f'Done. Try the scripts with --repo {path} --main main.tex', file=sys.stderr)


if __name__ == '__main__':
    main()
