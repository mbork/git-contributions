# * Overview
"""The fair measure: points per author for writing, rewriting, moving and removed drafts.

- a surviving word written fresh: 1 point to its writer;
- a surviving word typed in place of someone else's words: REWRITE points to its writer;
- a surviving word moved by someone other than its writer: MOVE points to the last such
  mover;
- a word removed by someone other than its writer: REMOVED points to the writer;
- a word removed by its own writer: nothing.
"""

# * Imports
import dataclasses
import math
from collections import Counter
from dataclasses import dataclass

# * Weights
CATEGORIES = ('written', 'rewritten', 'moved', 'removed')
# The weight of each category, by name of the field of Weights (writing is always 1).
CATEGORY_WEIGHTS = {'written': None, 'rewritten': 'rewrite', 'moved': 'move',
                    'removed': 'removed'}


@dataclass(frozen=True)
class Weights:
    rewrite: float = 0.75
    move: float = 0.1
    removed: float = 0.5

    def of(self, category):
        name = CATEGORY_WEIGHTS[category]
        return 1.0 if name is None else getattr(self, name)


WEIGHT_NAMES = tuple(f.name for f in dataclasses.fields(Weights))


def add_weight_options(parser):
    group = parser.add_argument_group('weights of the fair measure (writing a word is 1)')
    defaults = Weights()
    group.add_argument('--weight-rewrite', metavar='W', type=float, default=defaults.rewrite,
                       help='a surviving word typed in place of someone else\'s words'
                            ' (default: %(default)s)')
    group.add_argument('--weight-move', metavar='W', type=float, default=defaults.move,
                       help='a surviving word of someone else, moved (default: %(default)s)')
    group.add_argument('--weight-removed', metavar='W', type=float, default=defaults.removed,
                       help='a word removed or replaced by someone else (default:'
                            ' %(default)s)')


def weights_from(args, parser):
    weights = Weights(args.weight_rewrite, args.weight_move, args.weight_removed)
    for name in WEIGHT_NAMES:
        value = getattr(weights, name)
        if not math.isfinite(value) or value < 0:
            parser.error(f'--weight-{name} must be a non-negative number')
    return weights


def weight_fields(weights):
    """Report header fields naming the weights."""
    return [('weight_rewrite', 'Weight of rewriting', f'{weights.rewrite:g}'),
            ('weight_move', 'Weight of moving', f'{weights.move:g}'),
            ('weight_removed', 'Weight of removed drafts', f'{weights.removed:g}')]


# * Tallies
def tally(book, result, tokens=None):
    """Author -> Counter of words per category, over TOKENS (default: the whole project).

    Removal credit belongs to the history, not to a place in the text, so it is only
    counted for the whole project."""
    counts = {}
    is_whole_book = tokens is None
    for token in (book.tokens if is_whole_book else tokens):
        word = result.state[token.path][token.index]
        category = 'rewritten' if word.is_rewrite else 'written'
        counts.setdefault(word.writer, Counter())[category] += 1
        if word.mover is not None:
            counts.setdefault(word.mover, Counter())['moved'] += 1
    if is_whole_book:
        for author, removed in result.removed_by_others.items():
            counts.setdefault(author, Counter())['removed'] += removed
    return counts


def in_text(counts):
    """Words of an author in the current text."""
    return counts['written'] + counts['rewritten']


def points(counts, weights):
    return sum(weights.of(category) * counts[category] for category in CATEGORIES)


def percent(part, whole):
    return 100.0 * part / whole if whole else 0.0


def shares(tallies, weights):
    """Author -> percent of all points under WEIGHTS."""
    author_points = {author: points(counts, weights) for author, counts in tallies.items()}
    total = sum(author_points.values())
    return {author: percent(value, total) for author, value in author_points.items()}


def ranked(tallies, author_shares):
    """The authors of TALLIES, largest share first."""
    return sorted(tallies, key=lambda author: (-author_shares[author], str(author)))


def sensitivity(tallies, weights):
    """(key, label, {author: share}) with each weight set to 0 and to 1, the others as
    given."""
    variants = []
    for name in WEIGHT_NAMES:
        for value in (0, 1):
            changed = dataclasses.replace(weights, **{name: float(value)})
            variants.append((f'{name}_{value}', f'{name}={value}', shares(tallies, changed)))
    return variants
