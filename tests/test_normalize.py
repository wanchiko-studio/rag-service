"""The font-encoding repair, and the reason it is not a lookup table.

Guards the first of the two silent defects this project has hit: a PDF whose font
claimed «ĸ» (U+0138) for every Cyrillic «к». Nothing errored. The text looked almost
right. It embedded to the wrong vectors and retrieval quietly stopped working.
"""

from __future__ import annotations

from app.normalize import normalize_text


def test_repairs_kra_to_cyrillic_ka():
    """The damage actually seen in the wild: «ĸ» is never legitimate in either language."""
    text, report = normalize_text("обрабоĸа даннных и обработĸа таблиц")

    assert "ĸ" not in text
    assert text.count("к") == 2
    assert report.unconditional == 2
    assert report.total_fixed == 2


def test_english_words_survive_a_bilingual_line():
    """The whole reason repair is context-aware rather than a substitution table.

    A blanket Latin→Cyrillic map would rewrite the `a`, `c`, `e`, `o` and `p` in every
    English word. On a bilingual tender — which is the normal case here — that destroys
    half the document to fix the other half.
    """
    text, report = normalize_text("The process is fine. Обработĸа тоже.")

    assert "The process is fine." in text  # untouched: no Cyrillic in these words
    assert "Обработка" in text  # repaired: the word is already mostly Cyrillic
    assert report.contextual == 0  # nothing here needed a homoglyph decision


def test_latin_homoglyph_inside_a_cyrillic_word_is_repaired():
    """A Latin «c» hiding in a Russian word is exactly the invisible case."""
    # "сервис" written with a Latin "c" at the front.
    text, report = normalize_text("cервис работает")

    assert report.contextual == 1
    assert text.startswith("с")  # Cyrillic es, not Latin c


def test_clean_text_reports_that_it_is_clean():
    """Reporting nothing found is a result, not silence — that is the design."""
    text, report = normalize_text("Обычный русский текст and plain English.")

    assert text == "Обычный русский текст and plain English."
    assert report.total_fixed == 0
    assert "чистая" in report.summary()


def test_surviving_oddities_are_reported_not_swallowed():
    """A new document with new damage must show up, not be silently indexed.

    U+0161 is not in the repair table. The right behaviour is to leave it alone and
    say so, so that the next unknown encoding bug is visible the first time.
    """
    _, report = normalize_text("тест š символ")

    assert "š" in report.remaining
    assert "осталось подозрительных" in report.summary()


def test_empty_input_is_not_a_special_case_for_the_caller():
    text, report = normalize_text("")

    assert text == ""
    assert report.total_fixed == 0
