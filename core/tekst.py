"""Tekst OCR: normalizacja do porównań i znaczniki stron [STRONA_X]."""

import re
import unicodedata


def dodaj_markery_stron(ocr_text):

    strony = re.split(
        r'&lt;!--\s*PageBreak\s*--&gt;',
        ocr_text
    )

    wynik = []

    for nr, tresc in enumerate(
        strony,
        start=1
    ):
        wynik.append(
            f"\n\n[STRONA_{nr}]\n{tresc}"
        )

    return "".join(wynik)


DLUGOSC_KONTEKSTU = 110


def normalizuj_do_szukania(tekst):
    """Bez diakrytyków i wielkości liter — analityk wpisuje frazę z pamięci."""
    rozlozony = unicodedata.normalize("NFKD", str(tekst))
    return "".join(z for z in rozlozony if not unicodedata.combining(z)).lower()


def strona_dla_pozycji(ocr_text, pozycja):
    """Numer strony dla znalezionej pozycji — po ostatnim markerze [STRONA_X].

    Zwraca None, gdy tekst nie ma markerów (np. wynik z cache zapisany
    przed ich dodaniem).
    """
    fragment = ocr_text[:pozycja]
    markery = re.findall(r"\[STRONA_(\d+)\]", fragment)
    return int(markery[-1]) if markery else None


def normalizuj_do_porownania(tekst):
    """Wielkość liter i układ białych znaków nie mają znaczenia — reszta tak.

    Celowo NIE zdejmujemy diakrytyków ani nie skracamy końcówek (jak robi to
    normalizuj_do_szukania). Tu pytamy "czy ten zapis naprawdę tam stoi",
    więc im ostrzejsze porównanie, tym mniej fałszywych potwierdzeń.
    """
    return re.sub(r"\s+", " ", str(tekst)).strip().lower()
