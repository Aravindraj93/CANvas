"""Literal-first, separator-insensitive search with bounded typo matching."""
from functools import lru_cache
import unicodedata


@lru_cache(maxsize=32768)
def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


@lru_cache(maxsize=32768)
def _bigrams(text):
    return frozenset(text[i:i+2] for i in range(len(text)-1))


def _near_substring(query, text, errors, query_bigrams):
    """Bounded Damerau-Levenshtein distance, allowing a free prefix/suffix."""
    if len(text) < len(query) - errors:
        return None
    # Cheap rejection before constructing edit-distance rows.
    if len(query_bigrams & _bigrams(text)) < max(1, len(query_bigrams) - 3 * errors):
        return None
    previous = [0] * (len(text) + 1)
    older = None
    for i, char in enumerate(query, 1):
        current = [i]
        for j, other in enumerate(text, 1):
            value = min(current[j-1] + 1, previous[j] + 1, previous[j-1] + (char != other))
            if older is not None and j > 1 and char == text[j-2] and query[i-2] == other:
                value = min(value, older[j-2] + 1)
            current.append(value)
        older, previous = previous, current
    distance = min(previous)
    return distance if distance <= errors else None


class SearchQuery:
    def __init__(self, text):
        self.query = normalize(text)
        self.allow_fuzzy = len(self.query) >= 4
        self._bigrams = _bigrams(self.query)
        self._cache = {}

    def matches(self, fields, fuzzy=False):
        if not self.query:
            return True
        if any(self.query in field for field in fields):
            return True
        return self.distance(fields) is not None if fuzzy and self.allow_fuzzy else False

    def distance(self, fields):
        best = None
        for field in fields:
            if self.query in field:
                return 0
            if field not in self._cache:
                self._cache[field] = _near_substring(self.query, field, 1 if len(self.query) < 8 else 2, self._bigrams)
            distance = self._cache[field]
            if distance is not None:
                best = distance if best is None else min(best, distance)
        return best

    def rank(self, fields):
        ranks = [(self.distance((field,)), abs(len(field) - len(self.query))) for field in fields]
        return min((distance, length) for distance, length in ranks if distance is not None)
