"""Hinweisgebersystem – Passphrase Generation Module.

Provides BIP-39 inspired 6-word passphrase generation for anonymous
report access credentials.  Uses the English BIP-39 wordlist (2048
words), yielding ~2^66 possible combinations — collision probability
is astronomically low.

The passphrase is displayed to the reporter after submission and is
**never stored in plain text** — only a bcrypt hash is persisted.

Usage::

    from app.core.passphrase import generate_passphrase, format_passphrase

    passphrase = generate_passphrase()          # "ocean brick maple verify abstract notable"
    formatted = format_passphrase(passphrase)   # "ocean · brick · maple · verify · abstract · notable"
"""

from __future__ import annotations

import secrets

import structlog
from mnemonic import Mnemonic

logger = structlog.get_logger(__name__)

# Number of words in a generated passphrase.
_WORD_COUNT = 6

# BIP-39 English wordlist (~2048 words).
# Using English because a standard German BIP-39 wordlist does not exist.
_mnemo = Mnemonic("english")
_WORDLIST: list[str] = _mnemo.wordlist

# Display separator for formatted passphrases.
_DISPLAY_SEPARATOR = " · "


def generate_passphrase(*, word_count: int = _WORD_COUNT) -> str:
    """Generate a cryptographically random passphrase.

    Selects *word_count* words uniformly at random from the BIP-39
    English wordlist (2048 words).  With the default 6 words, this
    provides approximately 2^66 possible combinations.

    Parameters
    ----------
    word_count:
        Number of words in the passphrase.  Defaults to 6.

    Returns
    -------
    str
        Space-separated lowercase words, e.g.
        ``"ocean brick maple verify abstract notable"``.

    Raises
    ------
    ValueError
        If *word_count* is less than 1.
    """
    if word_count < 1:
        raise ValueError("word_count must be at least 1.")

    words = [secrets.choice(_WORDLIST) for _ in range(word_count)]
    return " ".join(words)


def format_passphrase(passphrase: str) -> str:
    """Format a passphrase for user display.

    Joins words with a visual separator (``·``) for improved
    readability when displayed on-screen or copied.

    Parameters
    ----------
    passphrase:
        Space-separated passphrase as returned by
        :func:`generate_passphrase`.

    Returns
    -------
    str
        Formatted string, e.g.
        ``"ocean · brick · maple · verify · abstract · notable"``.
    """
    words = passphrase.strip().split()
    return _DISPLAY_SEPARATOR.join(words)


def validate_passphrase_format(passphrase: str) -> bool:
    """Check whether a passphrase has the expected format.

    Validates that the passphrase contains exactly 6 space-separated
    words, each present in the BIP-39 wordlist.  This is a *format*
    check only — authentication is done via bcrypt hash comparison.

    Parameters
    ----------
    passphrase:
        The passphrase string to validate.

    Returns
    -------
    bool
        ``True`` if the format is valid, ``False`` otherwise.
    """
    words = passphrase.strip().split()
    if len(words) != _WORD_COUNT:
        return False

    wordlist_set = set(_WORDLIST)
    return all(word in wordlist_set for word in words)
