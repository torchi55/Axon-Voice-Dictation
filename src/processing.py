"""Processing pipeline (PLAN step 5).

Fixed order: Whisper → Filler Cleanup (if enabled) → Snippet expansion.
Snippets run LAST so filler-stripping never mutates an expansion.

Filler Cleanup is conservative and OFF by default:
  - `um` / `uh` (and variants) are stripped globally — they are never real words.
  - `like` / `you know` / `I mean` are stripped ONLY in interjection position (set
    off by a clause boundary and a following comma / end).
  - `you know what I mean` is stripped globally — it is never content.
  - `does that make sense` / `so yeah` are stripped only at the end of the utterance.
  - `right` is stripped only when it follows a comma at the end (", right").
"""
import re

# Standalone disfluencies — safe to strip anywhere.
_UM_UH = re.compile(r"\b(?:u+m+|u+h+|er+m+|hm+)\b[,.]?", re.IGNORECASE)

# Whole-phrase fillers safe to strip anywhere in the utterance.
_GLOBAL = re.compile(r"\byou know what I mean\b[,.]?", re.IGNORECASE)

# Sentence-ender fillers — only stripped at the very end of the utterance.
# "right" only when preceded by a comma (", right") — bare "right" is ambiguous.
_ENDERS = re.compile(
    r"(?:[,.]?\s*\b(?:does that make sense\??|so yeah)\b[?!.]?|,\s*\bright\b[?!.]?)\s*$",
    re.IGNORECASE,
)

# Interjection "like" / "you know" / "I mean": a clause boundary (start / , . ! ? ; :),
# the filler, then a following comma or end-of-string. Keeps the boundary char.
_INTERJ = re.compile(
    r"(^|[,.!?;:])\s*(?:like|you know|I mean)\s*(?=,|$)",
    re.IGNORECASE,
)


def _tidy(text: str) -> str:
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)       # space before punctuation
    text = re.sub(r"([,.!?;:])(\s*\1)+", r"\1", text)  # collapsed dup punctuation
    text = re.sub(r"^[\s,;:]+", "", text)              # leading filler punctuation
    text = re.sub(r"\s{2,}", " ", text)                # collapse whitespace
    return text.strip()


def apply_filler_cleanup(text: str) -> str:
    text = _UM_UH.sub("", text)
    text = _GLOBAL.sub("", text)
    text = _ENDERS.sub("", text)
    text = _INTERJ.sub(r"\1", text)
    return _tidy(text)


def apply_snippets(text: str, snippets: dict) -> str:
    # Longest keyword first so "api key" wins over "api".
    for keyword, expansion in sorted(
        snippets.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if not keyword.strip():
            continue
        esc = re.escape(keyword)
        # Insert the expansion via a function replacement, NOT as a string. A
        # string replacement interprets backslashes and group refs (\1, \g<n>)
        # inside the user's expansion — a Windows path, "\n", or an email
        # signature would corrupt the output or raise re.error. A callable
        # returns the text literally. (Default-arg binds expansion per-iteration.)
        def _repl(_m, _e=expansion):
            return _e
        # A snippet spoken alone (or ending the utterance) inherits Whisper's
        # auto sentence-punctuation ("email" -> "email."). Eat that trailing
        # mark so the expansion is exactly the snippet, no stray period. Only
        # at end-of-string — mid-sentence snippets keep their punctuation.
        text = re.sub(
            rf"\b{esc}\b\s*[.!?,]?\s*$", _repl, text, flags=re.IGNORECASE
        )
        text = re.sub(
            rf"\b{esc}\b", _repl, text, flags=re.IGNORECASE
        )
    return text


def process(raw: str, snippets: dict, filler_cleanup: bool) -> str:
    text = raw
    if filler_cleanup:
        text = apply_filler_cleanup(text)
    text = apply_snippets(text, snippets)
    return text
