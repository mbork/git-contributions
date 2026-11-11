# `author_shares.py`: every author's fair share

## In plain words

The project is kept in Git, which records every change anybody made, who made it and when.
This script reads that whole record and estimates, for every author, what part of the project
is theirs, in percent.

It works **word by word**.  For every word in the project as it is now, it finds out who
typed it.  It also follows the words that are no longer there: who wrote them, and who later
deleted or replaced them.  Each kind of contribution earns points:

| What happened                                                        | Points per word | To whom |
|----------------------------------------------------------------------|-----------------|---------|
| You wrote a word that is in the project                              | 1               | you     |
| You typed a word in place of someone else's words                    | 0.75            | you     |
| You moved someone else's words (say, a paragraph to another chapter) | 0.1             | you     |
| You wrote a word that someone else later deleted or replaced         | 0.5             | you     |
| You deleted your own word                                            | 0               | nobody  |

Your fair share is your part of all points.  The numbers 0.75, 0.1 and 0.5 are the
defaults; they can be changed on the command line.

Why these rules:

- **Writing counts most.**  The words in the project are the result.
- **Rewriting counts a little less.**  If Bob rewrites a sentence Alice wrote, the new words
  are Bob's, but they build on Alice's sentence.
- **Moving counts little.**  Moving a paragraph is a real editorial decision, but it creates
  no text.
- **A replaced draft still counts, at half.**  If Alice wrote a paragraph and Bob later
  rewrote it, Alice's draft shaped Bob's version.  Without this, a co-author who rewrote
  everything would erase every trace of the first drafts.
- **Deleting your own text counts nothing.**  Otherwise writing and rewriting your own
  paragraphs five times would earn five times the credit.

### An example

Alice writes a paragraph of 100 words.  Later Bob replaces 20 of them with 25 words of his
own, and Carol moves the whole paragraph to another chapter.

- Alice: 80 surviving words (80 points) plus 20 replaced words at 0.5 (10 points) = 90.
- Bob: 20 words typed in place of Alice's (15 points) plus 5 more words (5 points) = 20.
- Carol: 105 moved words at 0.1 = 10.5.

Shares: Alice 74.7%, Bob 16.6%, Carol 8.7% (of 120.5 points).

### What the report shows

- **Fair share** -- the main figure, as above.
- **Share of the text** -- simply who typed the words that are in the project now.  The
  easiest figure to check, but it gives nothing for drafts that others rewrote.
- The words behind the points: written, rewritten, moved, removed by others.
- **Sensitivity**: the fair share with each weight set to 0 and to 1.  The weights are a
  judgment call; a share that barely changes there does not depend on them.
- The same per chapter (without removed drafts, which are no longer in any chapter).
- Which names and e-mail addresses each author used.

### Caveats

- Only what Git records counts.  Text one person wrote but another committed counts for
  the one who committed it.  Ideas, proofs worked out in a discussion, reviewing and
  editorial decisions do not show up at all.
- A "word" is anything between spaces, so `\emph{word},` or `$x^2$` is one word, and a long
  formula written without spaces is one word too.
- When someone heavily rewrites a sentence, small words such as "the" or "of" that happen to
  stay put keep their original author, which favors the original author slightly.
- Mechanical bulk changes (reformatting, renaming a macro everywhere) count like any edit.
- Text dropped while resolving a merge conflict earns nobody anything.

## Usage

    ./author_shares.py --repo ~/books/graphs --main book.tex
    ./author_shares.py --repo ~/books/graphs --main book.tex --commit v1.0 --format latex
    ./author_shares.py --repo ~/books/graphs --main book.tex --weight-removed 0 \
        --output shares-final-text-only.md

Options common to all scripts (`--repo`, `--main`, `--commit`, `--format`, `--output`,
`--mailmap`, `--include-preamble`, `--common-words`) are described by `--help`.  Specific to
this script: `--weight-rewrite`, `--weight-move`, `--weight-removed` (defaults 0.75, 0.1,
0.5).  With `--weight-rewrite 1 --weight-move 0 --weight-removed 0` the fair share is
the share of the text.

## How it works

### Words and the working copy

The measured repository is never modified.  The first run copies its `.git` directory to a
sibling directory `<repo>--contrib--<ref>-<hash7>` (a plain copy, not a clone: no remotes,
fresh configuration) and rewrites the copy's history with `git filter-repo`: in every
`.tex` file of every commit, comments are dropped and every word goes on its own line.  A
line diff of the rewritten history is then a word diff.  Later runs (of any script, for the
same commit) reuse the copy.

A word is a maximal run of non-whitespace characters outside comments; `%` inside `\verb`
and verbatim environments is not a comment.

### What counts as the text

The files reachable from `--main` through `\input` and `\include` at the measured commit.
The preamble (the main file before `\begin{document}` and files input from there) is left
out, from the text and from the history, unless `--include-preamble` is given.  In the
history, the part of any `.tex` file before `\begin{document}` counts as preamble, so a
main file that was renamed is still recognized.  The history
covers all `.tex` files, so text moved in from a file that is no longer included keeps its
author.

### Following the words

The history is replayed once, in topological order.  The state of a commit is, for every
file, a list of word records: writer, whether the word was typed as a rewrite, and the last
author other than the writer who moved it.  For an ordinary commit the diff from its parent
(`git diff -U0 -M --histogram`) is applied to the parent's state:

- unchanged words keep their records;
- **moves**: a run of at least 8 equal words removed and added in the same commit (same or
  another file) keeps its records; the commit's author becomes the mover if they are not
  the writer;
- **rewrites**: in a hunk that removes *r* words written by others and adds *a* words, the
  first min(*a*, *r*) added words are rewrites, the rest fresh writing;
- every other removed word written by someone other than the commit's author earns its
  writer removal credit;
- merges: each word of the result keeps its record from the parent that had it; words in
  no parent (conflict resolutions) are fresh writing by the merge's author; merges earn no
  removal credit (removals are credited on the branch where they happened).

Text deleted in one commit and re-added in a later one is new writing by whoever re-added
it.  At the end, the state of the measured commit is checked word for word against its
files.

### Points

For author *X*: written + 0.75 rewritten + 0.1 moved (as mover) + 0.5 removed by others,
with the weights from the command line.  Fair share = *X*'s points / everybody's points.
Per chapter, only the words in the chapter count (removal credit has no place in the
current text).  Chapters are `\chapter`s, or `\section`s in a project without chapters; text
before the first one is a chapter of its own.

### Authors

Authors are the names recorded in the commits after `.mailmap` (by default the `.mailmap`
of the measured commit; `--mailmap` overrides it).  Two identities with the same name after
`.mailmap` are one author.

### Trade-offs

- **Word-level matching** credits a typo fix with one word, not a paragraph, and ignores
  re-wrapping; but a word diff can match common words across a heavy rewrite, leaving them
  with the original author (the histogram algorithm reduces, but does not remove, this).
- **Moves** need at least 8 equal words in a row in one commit; shorter moved fragments
  count as removal plus rewriting.  A move spread over two commits (cut, commit, paste,
  commit) counts as removal plus new writing.
- **Removal credit** counts words removed from any `.tex` file, including drafts that were
  never part of the project.
