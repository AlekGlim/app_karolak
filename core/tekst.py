"""Tekst OCR: normalizacja do porównań i znaczniki stron [STRONA_X]."""

import html
import re
import unicodedata
from functools import lru_cache


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


DLUGOSC_KONTEKSTU = 200


@lru_cache(maxsize=None)
def _znak_do_szukania(znak):
    """Jeden znak bez diakrytyku i wielkości liter — zawsze jeden znak.

    NFKD rozwija też znaki złożone ("…" -> "...", "ﬁ" -> "fi", "№" -> "No"),
    a "İ".lower() daje dwa znaki. Taki znak zostaje bez zmian: wynik ma mieć
    tę samą długość co wejście.
    """
    bez_diakrytyku = "".join(
        z for z in unicodedata.normalize("NFKD", znak)
        if not unicodedata.combining(z)
    ).lower()

    if len(bez_diakrytyku) == 1:
        return bez_diakrytyku

    maly = znak.lower()
    return maly if len(maly) == 1 else znak


def normalizuj_do_szukania(tekst):
    """Bez diakrytyków i wielkości liter — analityk wpisuje frazę z pamięci.

    Wynik ma zawsze tę samą długość co wejście: pozycje trafień w tekście
    znormalizowanym służą do wycinania fragmentów i szukania markera strony
    w tekście oryginalnym. Przy normalizacji całego tekstu naraz jeden "…"
    przesuwał wszystkie dalsze trafienia o dwa znaki.
    """
    return "".join(map(_znak_do_szukania, str(tekst)))


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


def tekst_do_wyswietlenia(fragment):
    """Fragment tekstu OCR w postaci do pokazania analitykowi.

    Endpoint OCR (prebuilt-layout) zwraca markdown z encjami zamiast < i >:
    tabele jako &lt;table&gt;&lt;tr&gt;&lt;td&gt;…, komentarze stron
    (&lt;!-- PageHeader=… --&gt;), nagłówki "# ", znaczniki pól wyboru.
    Tu zostaje sam tekst: komórki tabeli rozdzielone " · ", wiersze " | ", reszta znaczników
    usunięta. Fragment jest wycinkiem, więc obcięte znaczniki na jego
    brzegach też są usuwane.

    Wynik to zwykły tekst — przed wstawieniem do HTML trzeba go escapować.
    """
    tekst = str(fragment)

    # encja przecięta brzegiem wycinka ("&l" na końcu, "t;" na początku)
    tekst = re.sub(r"&[a-zA-Z#0-9]{0,7}$", "", tekst)
    tekst = re.sub(r"^(?:l?t|g?t|a?m?p|q?u?o?t);", "", tekst)

    tekst = html.unescape(tekst)

    # komentarze, także obcięte na brzegach wycinka
    tekst = re.sub(r"<!--.*?-->", " ", tekst, flags=re.DOTALL)
    tekst = re.sub(r"^[^<]*?-->", " ", tekst, flags=re.DOTALL)
    tekst = re.sub(r"<!--.*$", " ", tekst, flags=re.DOTALL)

    # tabele: granica komórek -> separator, pozostałe znaczniki -> odstęp
    tekst = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " · ", tekst)
    tekst = re.sub(r"</t[dh]>\s*</tr>\s*<tr[^>]*>\s*<t[dh][^>]*>", " | ", tekst)
    tekst = re.sub(r"</tr>\s*<tr[^>]*>", " | ", tekst)
    tekst = re.sub(r"</?[a-zA-Z][^>]*>", " ", tekst)
    tekst = re.sub(r"^\s*/?[a-zA-Z]{1,10}>", " ", tekst)   # "td>" na początku wycinka
    tekst = re.sub(r"</?[a-zA-Z]{0,10}$", " ", tekst)       # "</t" na końcu wycinka

    tekst = re.sub(r"(?m)^\s*#{1,6}\s+", "", tekst)
    tekst = re.sub(r":(?:un)?selected:", " ", tekst)

    return re.sub(r"\s+", " ", tekst)
