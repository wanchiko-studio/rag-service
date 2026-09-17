"""Repairing text that the PDF's own font encoding damaged.

Found on the first real document this was pointed at: a five-page Russian PDF where
**every** Cyrillic «к» came out as «ĸ» (U+0138, the Latin letter kra, used in
Greenlandic and essentially nowhere else). 57 occurrences, zero real «к». The font's
encoding table was wrong and pdfplumber faithfully reported what the font claimed.

Left alone this breaks retrieval rather than just looking untidy: «обработĸа» and
«обработка» are different strings, so they embed to different vectors and a search
for one will not find the other.

⚠️ The obvious fix is the wrong one. A blanket Latin→Cyrillic lookup table would map
every Latin "a", "e", "o", "c" and "p" to its Cyrillic twin — and destroy every
English word in a bilingual document. So substitution is context-aware: a Latin
homoglyph is only repaired when it sits inside a word that is already mostly Cyrillic.

Nothing here is silent. `normalize_text` returns a report of what it changed and what
suspicious characters are still present, so the problem stays measurable instead of
being assumed solved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Characters that are never legitimate in Russian or English text, so they can be
# repaired unconditionally. Add to this list only with a real document as evidence.
UNCONDITIONAL: dict[str, str] = {
    "ĸ": "к",  # ĸ  Latin small letter kra      -> к
    "ӏ": "і",  # ӏ  Palochka (lowercase)        -> і
    "Ƅ": "б",  # Ƅ  Latin letter tone six       -> б
}

# Latin letters that look identical to a Cyrillic letter. Only substituted inside a
# word that already contains Cyrillic — otherwise English words would be mangled.
CONTEXTUAL: dict[str, str] = {
    "a": "а", "c": "с", "e": "е", "o": "о",
    "p": "р", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е",
    "H": "Н", "K": "К", "M": "М", "O": "О",
    "P": "Р", "T": "Т", "X": "Х", "Y": "У",
}

CYRILLIC = re.compile(r"[Ѐ-ӿ]")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Anything in these ranges is worth reporting if it survives normalisation: Latin
# Extended blocks are where broken font encodings usually dump their substitutes.
_SUSPICIOUS_RANGES = ((0x0100, 0x024F), (0x02B0, 0x02FF), (0x1E00, 0x1EFF))


@dataclass(slots=True)
class NormalizationReport:
    unconditional: int = 0
    contextual: int = 0
    remaining: dict[str, int] = field(default_factory=dict)

    @property
    def total_fixed(self) -> int:
        return self.unconditional + self.contextual

    def summary(self) -> str:
        if not self.total_fixed and not self.remaining:
            return "кодировка чистая, правок не потребовалось"
        bits = []
        if self.unconditional:
            bits.append(f"{self.unconditional} подменённых символов исправлено")
        if self.contextual:
            bits.append(f"{self.contextual} латинских омоглифов в русских словах исправлено")
        if self.remaining:
            shown = ", ".join(f"{ch!r}×{n}" for ch, n in sorted(self.remaining.items()))
            bits.append(f"осталось подозрительных: {shown}")
        return "; ".join(bits)


def normalize_text(text: str) -> tuple[str, NormalizationReport]:
    """Repair font-encoding damage, and report exactly what was done."""
    report = NormalizationReport()
    if not text:
        return text, report

    # Pass 1: characters that are always wrong.
    for bad, good in UNCONDITIONAL.items():
        hits = text.count(bad)
        if hits:
            text = text.replace(bad, good)
            report.unconditional += hits

    # Pass 2: Latin homoglyphs, but only inside words that are already Cyrillic.
    def repair_word(match: re.Match[str]) -> str:
        word = match.group(0)
        if not CYRILLIC.search(word):
            return word  # pure Latin — an English word, leave it alone
        out = []
        for ch in word:
            replacement = CONTEXTUAL.get(ch)
            if replacement:
                out.append(replacement)
                report.contextual += 1
            else:
                out.append(ch)
        return "".join(out)

    text = WORD.sub(repair_word, text)

    # Pass 3: what is still odd? Report it rather than guessing.
    for ch in text:
        code = ord(ch)
        if any(low <= code <= high for low, high in _SUSPICIOUS_RANGES):
            report.remaining[ch] = report.remaining.get(ch, 0) + 1

    return text, report
