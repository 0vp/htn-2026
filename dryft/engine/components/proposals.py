"""Request-local, weight-free proposals and exact prefix acceptance."""


def accepted_prefix(draft: list[int], predictions: list[int]) -> int:
    accepted = 0
    while accepted < len(draft) and draft[accepted] == predictions[accepted]:
        accepted += 1
    return accepted


class SuffixLookup:
    """Bounded suffix index; no prompt state survives a generation call."""

    def __init__(self, history: list[int], max_draft: int = 6):
        self.history = list(history)
        self.index: dict[tuple[int, ...], int] = {}
        self.max_draft = max_draft
        self.budget = min(2, max_draft)
        self.misses = 0
        self.cooldown = 0
        for end in range(2, len(self.history)):
            self._index(end)

    def _index(self, end: int) -> None:
        for width in range(2, min(8, end) + 1):
            self.index[tuple(self.history[end - width:end])] = end

    def append(self, tokens: list[int]) -> None:
        for token in tokens:
            self.history.append(token)
            self._index(len(self.history) - 1)

    def propose(self, limit: int) -> list[int]:
        if self.cooldown:
            self.cooldown -= 1
            return []
        limit = min(limit, self.budget)
        if limit <= 0:
            return []
        for width in range(min(8, len(self.history)), 1, -1):
            end = self.index.get(tuple(self.history[-width:]))
            if end is not None:
                return self.history[end:end + limit]
        return []

    def feedback(self, proposed: int, accepted: int) -> None:
        if not proposed:
            return
        if proposed == accepted:
            self.budget = min(self.max_draft, self.budget + 1)
            self.misses = 0
        else:
            self.budget = max(1, self.budget - 1)
            self.misses = self.misses + 1 if accepted == 0 else 0
            if self.misses >= 2:
                self.cooldown = 4
                self.misses = 0
