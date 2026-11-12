# SPDX-License-Identifier: GPL-3.0-or-later
# * Overview
"""A single pass over the rewritten history, following every word from commit to commit.

In the rewritten history every .tex file has one word per line, so a line diff is a word
diff.  The state of a commit is, per file, a list of word records; each record says who
wrote the word, whether it was typed as a rewrite of someone else's words, and who last
moved it (if that was not the writer).  Applying each commit's diff to its parent's state
gives the state at the measured commit, plus what happened along the way: words removed
from someone else's text, and words typed.

Authors are keys returned by an `author_key` function, so that a script can merge every
identity of one person (after .mailmap, or by a regex) into one key.
"""

# * Imports
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from contrib import latex, workcopy
from contrib.cli import ContribError

# * Constants
MIN_MOVE = 8            # this many words in a row, removed and re-added in one commit, move
PATHSPEC = ':(icase)*.tex'
HUNK = re.compile(rb'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
# C escapes git uses in quoted paths, as byte values.
C_ESCAPES = {ord('n'): ord('\n'), ord('t'): ord('\t'), ord('"'): ord('"'),
             ord('\\'): ord('\\'), ord('a'): 7, ord('b'): 8, ord('f'): 12,
             ord('r'): ord('\r'), ord('v'): 11}


# * Records
@dataclass(frozen=True)
class Word:
    text: str
    writer: object          # author key
    is_rewrite: bool        # typed in place of words by someone else
    mover: object = None    # last author other than the writer who moved it


@dataclass
class Removal:
    """A run of consecutive words by one watched writer, removed in one commit -- by the
    writer or by someone else (compare REMOVER with WRITER)."""
    commit: str             # rewritten hash
    remover: object
    path: str
    words: list
    writer: object
    section: str


@dataclass
class Commit:
    hash: str
    parents: list
    author: object          # author key
    identity: str           # "Name <email>" after .mailmap
    raw_identity: str       # "Name <email>" as recorded
    time: int
    subject: str


@dataclass
class Result:
    state: dict                                         # path -> [Word] at the target
    commits: dict                                       # hash -> Commit
    removed_by_others: Counter = field(default_factory=Counter)  # writer -> words
    typed: Counter = field(default_factory=Counter)     # author -> words ever typed
    removals: list = field(default_factory=list)        # [Removal] of watched writers


# * Reading git output
def unquote(raw):
    """A path as git prints it, possibly C-quoted, as bytes without the quotes."""
    if raw.startswith(b'"') and raw.endswith(b'"'):
        body = raw[1:-1]
        out = bytearray()
        index = 0
        while index < len(body):
            char = body[index]
            if char == ord('\\') and index + 1 < len(body):
                following = body[index + 1]
                if ord('0') <= following <= ord('7'):
                    out.append(int(body[index + 1:index + 4], 8))
                    index += 4
                    continue
                out.append(C_ESCAPES.get(following, following))
                index += 2
                continue
            out.append(char)
            index += 1
        raw = bytes(out)
    return raw


def unquote_path(raw):
    """A path from a ---/+++ line, without its a/ or b/ prefix; None for /dev/null."""
    if raw == b'/dev/null':
        return None
    return latex.decode(unquote(raw)[2:])


def parse_diff(output):
    """Changed files as (old_path, new_path, hunks); a hunk is
    (old_start, old_length, removed_words, added_words)."""
    files = []
    current = None
    hunk = None
    for line in output.split(b'\n'):
        if line.startswith(b'diff --git '):
            current = {'old': None, 'new': None, 'rename': [None, None], 'hunks': [],
                       'has_paths': False, 'header': line[11:], 'mode': None}
            files.append(current)
            hunk = None
        elif current is None:
            continue
        elif line.startswith(b'@@ '):
            match = HUNK.match(line)
            old_start, old_length = int(match.group(1)), match.group(2)
            hunk = (old_start, 1 if old_length is None else int(old_length), [], [])
            current['hunks'].append(hunk)
        elif hunk is not None:
            if line.startswith(b'-'):
                hunk[2].append(latex.decode(line[1:]))
            elif line.startswith(b'+'):
                hunk[3].append(latex.decode(line[1:]))
        elif line.startswith((b'new file mode ', b'deleted file mode ')):
            current['mode'] = 'new' if line.startswith(b'new') else 'deleted'
        elif line.startswith(b'rename from '):
            current['rename'][0] = latex.decode(unquote(line[12:]))
        elif line.startswith(b'rename to '):
            current['rename'][1] = latex.decode(unquote(line[10:]))
        elif line.startswith(b'--- '):
            current['old'] = unquote_path(line[4:].rstrip(b'\t'))
            current['has_paths'] = True
        elif line.startswith(b'+++ '):
            current['new'] = unquote_path(line[4:].rstrip(b'\t'))
    changes = []
    for item in files:
        if item['has_paths']:
            changes.append((item['old'], item['new'], item['hunks']))
        elif item['rename'][0] is not None:
            changes.append((item['rename'][0], item['rename'][1], []))
        elif item['mode'] is not None:
            # An empty file is created or deleted: no ---/+++ lines.  Both names in the
            # header are the same then, so the first half of the header is "a/<path>".
            header = item['header']
            path = unquote_path(header[:(len(header) - 1) // 2])
            changes.append((None, path, []) if item['mode'] == 'new' else (path, None, []))
    return changes


# * Applying a diff
def transform(state, changes):
    """STATE with CHANGES applied.

    Returns (new state, removed, added): removed = [(Word, path, index in the old list,
    hunk number)], added = [(text, list, index, hunk number, path)], where the new lists hold
    None at every added word.  Lists shared with STATE are never modified."""
    new = dict(state)
    removed = []
    added = []
    hunk_number = 0
    for old_path, new_path, hunks in changes:
        source = state.get(old_path, []) if old_path is not None else []
        if old_path is not None:
            new.pop(old_path, None)
        result = []
        position = 0
        for old_start, old_length, removed_words, added_words in hunks:
            hunk_number += 1
            cut = old_start - 1 if old_length else old_start
            if len(removed_words) != old_length or cut + old_length > len(source):
                raise ContribError(f'internal error: a diff does not fit the tracked state of'
                                   f' {old_path!r}')
            result.extend(source[position:cut])
            for offset, word in enumerate(source[cut:cut + old_length]):
                removed.append((word, old_path, cut + offset, hunk_number))
            position = cut + old_length
            for text in added_words:
                added.append((text, result, len(result), hunk_number, new_path))
                result.append(None)
        result.extend(source[position:])
        if new_path is not None:
            new[new_path] = result
    return new, removed, added


def find_moves(removed_texts, added_texts, length):
    """Greedily match runs of at least LENGTH equal words; yields (i, j, run length)."""
    if len(removed_texts) < length or len(added_texts) < length:
        return
    index = {}
    for i in range(len(removed_texts) - length + 1):
        index.setdefault(tuple(removed_texts[i:i + length]), []).append(i)
    used = bytearray(len(removed_texts))
    j = 0
    while j <= len(added_texts) - length:
        for i in index.get(tuple(added_texts[j:j + length]), ()):
            if any(used[i:i + length]):
                continue
            run = length
            while (i + run < len(removed_texts) and j + run < len(added_texts)
                   and removed_texts[i + run] == added_texts[j + run] and not used[i + run]):
                run += 1
            used[i:i + run] = b'\x01' * run
            yield i, j, run
            j += run
            break
        else:
            j += 1


# * Sections at the time of a removal
HEADING_WINDOW = 40     # words to look at for a heading's title


def section_before(words, index):
    """Title of the last \\part, \\chapter, \\section or \\subsection before word INDEX of a
    rewritten file, recognized as in contrib.latex."""
    for start in range(min(index, len(words)) - 1, -1, -1):
        if not words[start].text.startswith('\\'):
            continue
        text = ' '.join(word.text for word in words[start:start + HEADING_WINDOW])
        match = latex.SECTIONING.match(text)
        if not match or latex.SECTION_LEVELS[match.group(1)] > latex.DEEPEST_SECTION:
            continue
        found = latex.heading_at(text, match)
        if found is not None:
            return found[1]
    return ''


# * Checking the result
def check_state(book, state):
    """Make sure the replayed STATE has exactly the words of BOOK's files."""
    for path in book.counted:
        words = state.get(path)
        expected = book.files[path].words()
        if words is None or [word.text for word in words] != expected:
            raise ContribError(f'internal error: the replayed history of {path} does not'
                               ' match the file; delete the working copy and try again')


# * The replay
class Replay:
    """Replays the history of a working copy up to its target commit."""

    def __init__(self, workcopy, author_key, mailmap, progress, *, excluded_files=(),
                 include_preamble=False, watched=()):
        self.copy = workcopy
        self.author_key = author_key
        self.mailmap = mailmap
        self.progress = progress
        self.excluded_files = set(excluded_files)
        self.include_preamble = include_preamble
        self.watched = set(watched)
        self.blob_cache = {}    # (commit, path) -> words, for conflict resolutions

    # ** Git
    def git(self, *args):
        return self.copy.git(*workcopy.mailmap_options(self.mailmap), *args)

    def diff(self, old, new):
        output = self.git('diff', '-U0', '-M', '--histogram', '--no-color', '--no-ext-diff',
                          '--no-textconv', '--text', '--src-prefix=a/', '--dst-prefix=b/', old, new,
                          '--', PATHSPEC)
        return parse_diff(output)

    def read_commits(self):
        fields = '%x00'.join(['%H', '%P', '%aN <%aE>', '%an <%ae>', '%at', '%s'])
        output = self.git('log', '--topo-order', '--reverse', f'--format={fields}%x01',
                          self.copy.rewritten_hash)
        commits = []
        for record in output.decode('utf-8', errors='replace').split('\x01'):
            record = record.strip('\n')
            if not record:
                continue
            hash_, parents, identity, raw, time, subject = record.split('\x00')
            key = self.author_key(identity, raw)
            commits.append(Commit(hash_, parents.split(), key, identity, raw, int(time),
                                  subject))
        return commits

    # ** Preamble
    def counted_from(self, path, words):
        """Index of the first word of PATH that counts as text (len(words) if none does).

        Words before \\begin{document} are preamble in any file, so that the preamble of
        the main file is recognized under every name it had in the history."""
        if path in self.excluded_files:
            return len(words)
        if self.include_preamble:
            return 0
        for index, word in enumerate(words):
            if word is None or not word.text.startswith('\\begin'):
                continue
            following = words[index + 1] if index + 1 < len(words) else None
            pair = word.text + ' ' + (following.text if following is not None else '')
            match = latex.BEGIN_DOCUMENT.match(pair)
            if match:
                return index + 1 if match.end() <= len(word.text) else index + 2
        return 0

    # ** One commit
    def ordinary(self, commit, parent_state, parent, empty_tree, result):
        author = commit.author
        changes = self.diff(parent or empty_tree, commit.hash)
        state, removed, added = transform(parent_state, changes)
        moved_removed = set()
        moved_added = set()
        if removed and added:
            removed_texts = [word.text for word, _, _, _ in removed]
            added_texts = [text for text, _, _, _, _ in added]
            for i, j, run in find_moves(removed_texts, added_texts, MIN_MOVE):
                for k in range(run):
                    word = removed[i + k][0]
                    _, target, index, _, _ = added[j + k]
                    mover = author if author != word.writer else word.mover
                    target[index] = Word(word.text, word.writer, word.is_rewrite, mover)
                    moved_removed.add(i + k)
                    moved_added.add(j + k)
        old_starts = {}
        others_removed = Counter()      # hunk -> removed words written by someone else
        for i, (word, path, index, hunk) in enumerate(removed):
            if i in moved_removed:
                continue
            if path not in old_starts:
                old_starts[path] = self.counted_from(path, parent_state.get(path, []))
            if index < old_starts[path]:
                continue
            if word.writer != author:
                others_removed[hunk] += 1
                result.removed_by_others[word.writer] += 1
        for j, (text, target, index, hunk, _) in enumerate(added):
            if j in moved_added:
                continue
            is_rewrite = others_removed[hunk] > 0
            if is_rewrite:
                others_removed[hunk] -= 1
            target[index] = Word(text, author, is_rewrite)
        new_starts = {}
        for j, (_, target, index, _, path) in enumerate(added):
            if j in moved_added or path is None:
                continue
            if path not in new_starts:
                new_starts[path] = self.counted_from(path, target)
            if index >= new_starts[path]:
                result.typed[author] += 1
        if self.watched:
            self.collect_removals(commit, removed, moved_removed, parent_state, old_starts,
                                  result)
        return state

    def collect_removals(self, commit, removed, moved_removed, parent_state, old_starts,
                         result):
        """Group the watched writers' removed words into runs."""
        run = None
        previous_index = -2
        for i, (word, path, index, _) in enumerate(removed):
            is_watched = (i not in moved_removed and word.writer in self.watched
                          and index >= old_starts.get(path, 0))
            if not is_watched:
                run = None
                continue
            is_continuation = (run is not None and run.path == path
                               and run.writer == word.writer and previous_index + 1 == index)
            if not is_continuation:
                section = section_before(parent_state.get(path, []), index)
                run = Removal(commit.hash, commit.author, path, [], word.writer, section)
                result.removals.append(run)
            run.words.append(word.text)
            previous_index = index

    def merge(self, commit, states, parents, result):
        """Words keep their records from whichever parent had them; the rest (conflict
        resolutions) are typed by the merge's author.  Merges earn no removal credit."""
        self.blob_cache.clear()
        views = [transform(states[parent], self.diff(parent, commit.hash))[0]
                 for parent in parents]
        merged = views[0]
        for path, words in merged.items():
            if None not in words:
                continue
            for view in views[1:]:
                other = view.get(path)
                if other is None or len(other) != len(words):
                    continue
                for index, word in enumerate(words):
                    if word is None and other[index] is not None:
                        words[index] = other[index]
            typed = [index for index, word in enumerate(words) if word is None]
            for index in typed:
                words[index] = Word(self.git_text_of(commit, path, index), commit.author,
                                    False)
            counted_from = self.counted_from(path, words)
            result.typed[commit.author] += sum(1 for index in typed if index >= counted_from)
        return merged

    def git_text_of(self, commit, path, index):
        """Word INDEX of PATH at COMMIT (needed for conflict resolutions only)."""
        key = (commit.hash, path)
        if key not in self.blob_cache:
            blob = self.git('show', f'{commit.hash}:{path}')
            self.blob_cache[key] = latex.decode(blob).split('\n')
        return self.blob_cache[key][index]

    # ** The whole history
    def run(self):
        commits = self.read_commits()
        result = Result(state={}, commits={c.hash: c for c in commits})
        empty_tree_output = self.git('hash-object', '-t', 'tree', os.devnull)
        empty_tree = empty_tree_output.decode().strip()
        children = Counter(parent for c in commits for parent in c.parents)
        states = {}
        total = len(commits)
        step = max(1, total // 20)
        for number, commit in enumerate(commits, 1):
            if len(commit.parents) <= 1:
                parent = commit.parents[0] if commit.parents else None
                parent_state = states[parent] if parent else {}
                state = self.ordinary(commit, parent_state, parent, empty_tree, result)
            else:
                state = self.merge(commit, states, commit.parents, result)
            if children[commit.hash]:
                states[commit.hash] = state
            for parent in commit.parents:
                children[parent] -= 1
                if children[parent] == 0:
                    del states[parent]
            if commit.hash == self.copy.rewritten_hash:
                result.state = state
            if number % step == 0 or number == total:
                self.progress.log(f'replayed {number}/{total} commits')
        return result
