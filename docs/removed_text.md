# `removed_text.py`: one author's text that did not survive

## In plain words

This script lists the text one author wrote that is no longer in the project: deleted, or
replaced by different words.  Git, which keeps the project, records every change anybody made;
the script follows every word through that record, and whenever a word the author wrote
disappears, it notes who removed it and when.

The report starts with statistics:

- how many words the author ever typed, how many are still in the project, and how many were
  removed or replaced (also counting only words other than common ones like "the" or
  "let");
- who removed them: the author themselves (usually redrafting) or a co-author (usually
  rewriting or cutting), and how many words each.

Then comes the removed text itself, commit by commit, in the order of the history.  Each
commit shows its date, its identifier, its description and who made it; under it, each
removed piece shows the file and the section it was in, and the words themselves.

### An example

Alice wrote

    This lemma is due to Euler and was first proved in 1736.

and Bob later shortened it to

    This lemma is due to Euler.

Alice's report then lists, under Bob's commit, the piece
`Euler and was first proved in 1736.`  The words that stayed (`This lemma is due to`) are
not listed: they were not removed.  `Euler` is listed because `Euler` and `Euler.` are
different words: the new one, with the period, is Bob's.

**Moving is not removing.**  A block of at least 8 words taken out and put back elsewhere
in one change -- a paragraph moved to another chapter, say -- does not appear here.

### Caveats

- Only what Git records counts: text the author wrote but someone else saved into the
  repository is not theirs here.
- A "word" is anything between spaces, so changing `word` to `word,` lists `word` as
  removed.
- When two lines of work are combined (a merge), text dropped while reconciling them by
  hand is not listed, and text one line of work removed but the merge brought back is
  listed although it is in the project again.
- Text moved in two steps (taken out in one change, put back in a later one), or in blocks
  of fewer than 8 words, is listed as removed.
- Removals from the preamble are not listed unless `--include-preamble` is given.

## Usage

    ./removed_text.py --repo ~/books/graphs --main book.tex --author 'kowalski'
    ./removed_text.py --repo ~/books/graphs --main book.tex --author 'kowalski' \
        --commit v1.0 --format latex

Options common to all scripts are described by `--help`; `--author` is required.

## How it works

The working copy, the replay of the history and the definition of a word are those of
`author_shares.py` (see `docs/author_shares.md`).

During the replay, every word removed by an ordinary commit is checked: if it was written
by the author and the removal is not part of a move (a run of at least 8 equal words
removed and re-added in the same commit), it is recorded.  Consecutive removed words of
the author in the same file and commit form one **piece**.  Its section is the last
`\part`, `\chapter`, `\section` or `\subsection` before it in the file at that time.

Removals in the preamble -- the part of any `.tex` file before `\begin{document}`, and
the files input from the preamble -- are not recorded unless `--include-preamble` is
given.  Removals from `.tex` files that are not part of the project (old drafts, for example)
are recorded.  Merges record no removals: what a merge drops was usually removed on one
of the merged branches, where it is recorded.  Conversely, a removal recorded on a branch
stays listed even if the merge brings the words back.

The statistics:

- **ever typed**: every word the author typed in any commit, including words later
  removed and conflict resolutions in the author's merges; moved words are not typed
  again;
- **still in the project**: the author's words at the measured commit;
- **removed or replaced**: the words in all pieces; also without common words
  (`common-words.txt` or `--common-words`);
- the number of pieces and of commits, and the words per remover.

The three word counts need not add up: words can leave the project by being moved into a file
that is no longer included, or into the preamble.

Commits are shown with their original hashes (the measured repository's, not the working
copy's).

### Trade-offs

- A word diff can match common words across a rewrite, so a few small words of a heavily
  rewritten sentence may count as kept rather than removed.
- Pieces are cut wherever another author's word or a kept word sits between two removed
  words, so one rewritten sentence can give several short pieces.
