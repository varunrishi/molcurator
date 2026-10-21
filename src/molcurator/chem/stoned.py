# STONED SELFIES operators: random edits and crossover on SELFIES token lists.
# Pure chemistry helpers with no Candidate/settings knowledge; tools/generate.py drives them.
import random

import selfies

# Elements the edits may introduce by default: common in organic emitters and benchmark sets.
# The robust SELFIES alphabet also has B, P, I, H and charged tokens, which mostly give odd structures.
DEFAULT_ELEMENTS = ("C", "N", "O", "F", "S", "Cl", "Br")
PARENT_WEIGHT = 3  # parent tokens appear this many times in the pool, so edits favour the parent's chemistry
_STRUCTURE = ("Branch", "Ring")


def _keep(token: str, elements: tuple[str, ...]) -> bool:
    """True for structure tokens and neutral atoms of the allowed elements (any bond order)."""
    body = token.strip("[]").lstrip("=#")
    if body.startswith(_STRUCTURE):
        return True
    return body in elements  # charged tokens ("N+1") and other elements are not in the set


def alphabet(*token_lists: list[str], elements: tuple[str, ...] = DEFAULT_ELEMENTS) -> list[str]:
    """Sorted edit pool: allowed SELFIES tokens, plus the given molecules' own tokens (weighted).

    The molecules' tokens are always allowed, even charged or unusual ones, so a seed's own
    chemistry (a nitro group, a phosphine) can be kept and reused. Repeats set the weights.
    """
    pool = [t for t in selfies.get_semantic_robust_alphabet() if _keep(t, elements)]
    own = [t for tokens in token_lists for t in set(tokens)]
    return sorted(pool + own * PARENT_WEIGHT)


def mutate(tokens: list[str], alphabet: list[str], n_edits: int, rng: random.Random) -> list[str]:
    """Apply n_edits random token insertions, replacements or deletions."""
    tokens = list(tokens)
    for _ in range(n_edits):
        op = rng.choice(("insert", "replace", "delete"))
        if op == "delete" and len(tokens) > 1:
            del tokens[rng.randrange(len(tokens))]
        elif op == "replace" and tokens:
            tokens[rng.randrange(len(tokens))] = rng.choice(alphabet)
        else:
            tokens.insert(rng.randint(0, len(tokens)), rng.choice(alphabet))
    return tokens


def crossover(a: list[str], b: list[str], rng: random.Random) -> list[str]:
    """Join the start of one molecule to the end of another (interpolation between two parents)."""
    return a[:rng.randint(1, len(a))] + b[rng.randrange(len(b)):]
