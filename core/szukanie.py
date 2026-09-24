"""Szukanie wartości w tekście OCR i wyznaczanie numeru strony.

Numery stron są deterministyczne: wartość jest szukana w tekście OCR,
a strona wynika z najbliższego markera [STRONA_X] przed trafieniem.
"""

import re

from core.daty import parsuj_date, szukaj_daty_w_ocr
from core.kwoty import kwota_na_grosze, kwota_z_frazy, wzorzec_kwoty
from core.tekst import (
    DLUGOSC_KONTEKSTU,
    normalizuj_do_porownania,
    normalizuj_do_szukania,
    strona_dla_pozycji,
)


def wzorzec_z_odmiana(fraza):
    """Regex tolerujący polską odmianę: dłuższe słowa skracamy o końcówkę.

    W akcie notarialnym stoi "w Warszawie", a w polu mamy "Warszawa".
    Bez tego połowa pól tekstowych nie znalazłaby się w dokumencie.
    """
    slowa = normalizuj_do_szukania(fraza).split()
    if not slowa:
        return None

    czesci = []
    for slowo in slowa:
        rdzen = re.escape(slowo[:-2]) if len(slowo) > 5 else re.escape(slowo)
        czesci.append(rdzen + r"\w*")

    return r"\b" + r"\s+".join(czesci)


def szukaj_w_ocr(ocr_text, fraza):
    """Trafienia frazy w tekście OCR, z numerem strony i fragmentem kontekstu."""
    if not ocr_text or not fraza or not str(fraza).strip():
        return []

    znorm = normalizuj_do_szukania(ocr_text)
    trafienia = []

    def zbierz(wzor, dokladne):
        for dop in re.finditer(wzor, znorm):
            start, koniec = dop.span()
            od = max(0, start - DLUGOSC_KONTEKSTU)
            do = min(len(ocr_text), koniec + DLUGOSC_KONTEKSTU)
            trafienia.append({
                "pozycja": start,
                "strona": strona_dla_pozycji(ocr_text, start),
                "przed": ocr_text[od:start],
                "trafienie": ocr_text[start:koniec],
                "po": ocr_text[koniec:do],
                "dokladne": dokladne,
            })

    wzor_doslowny = re.escape(normalizuj_do_szukania(fraza).strip())
    if wzor_doslowny:
        zbierz(wzor_doslowny, True)

    # Odmiana dopiero jako zapas — inaczej "Nowak" łapałoby "Nowakowski".
    if not trafienia:
        wzor_odmiana = wzorzec_z_odmiana(fraza)
        if wzor_odmiana:
            zbierz(wzor_odmiana, False)

    widziane, unikalne = set(), []
    for t in sorted(trafienia, key=lambda t: t["pozycja"]):
        if t["pozycja"] not in widziane:
            widziane.add(t["pozycja"])
            unikalne.append(t)

    return unikalne


def warianty_do_szukania(fraza, potwierdzone):
    """Zapisy do wyszukania: [{"fraza": ..., "rodzaj": ...}].

    Gdy wpisana fraza jest jednym z zapisów pola z rozbieżnością, szukamy
    wszystkich jego zapisów — także niezgodnych, bo analityk chce zobaczyć,
    gdzie w dokumencie one stoją. Rodzaj pozwala je potem rozróżnić kolorem;
    bez tego "Nowak" wyglądałby na liście trafień tak samo jak "Kowalski".

    Gdy fraza nie należy do żadnego pola z rozbieżnością, zwraca samą frazę —
    szukajka działa wtedy jak dotychczas.
    """
    znorm_fraza = normalizuj_do_porownania(fraza)

    for wpis in (potwierdzone or []):
        zapisy = [{"fraza": wpis["wartosc_glowna"], "rodzaj": "glowna"}]

        for wartosc in wpis["wartosci_ok"]:
            zapisy.append({"fraza": wartosc, "rodzaj": "ok"})

        for wartosc in wpis["wartosci_zle"]:
            zapisy.append({"fraza": wartosc, "rodzaj": "zla"})

        if znorm_fraza in [normalizuj_do_porownania(z["fraza"]) for z in zapisy]:
            return zapisy

    return [{"fraza": fraza, "rodzaj": "szukana"}]


def szukaj_w_ocr_z_wariantami(ocr_text, zapisy):
    """Trafienia dla kilku zapisów naraz, posortowane po pozycji w tekście.

    `zapisy` w formacie z warianty_do_szukania. Każdy zapis szukamy osobno
    przez szukaj_w_ocr, więc reguły (dosłownie, odmiana tylko jako zapas)
    zostają te same. Rodzaj zapisu przechodzi na trafienie.

    Gdy dwa zapisy trafią w to samo miejsce, wygrywa ten wcześniejszy na
    liście — dlatego warianty_do_szukania zwraca najpierw wartość główną,
    potem "ok", a na końcu niezgodne.
    """
    wszystkie = []

    for zapis in zapisy:
        # Kwotę szukamy wyłącznie wzorcem kwoty: łapie każdy zapis i pilnuje
        # granic liczby. Szukanie dosłowne znalazłoby "685 000,00" także
        # w środku "1 685 000,00".
        grosze = kwota_z_frazy(zapis["fraza"])
        if grosze is not None:
            trafienia_zapisu = szukaj_kwoty_w_ocr(ocr_text, grosze)
        else:
            trafienia_zapisu = szukaj_w_ocr(ocr_text, zapis["fraza"])

        # fraza będąca pełną datą znajduje ją w każdym zapisie
        # ("22-03-2000" znajdzie też "22 marca 2000") — patrz 2B
        data = parsuj_date(zapis["fraza"])
        if data:
            trafienia_zapisu += szukaj_daty_w_ocr(ocr_text, data)

        for trafienie in trafienia_zapisu:
            trafienie["fraza"] = zapis["fraza"]
            trafienie["rodzaj"] = zapis["rodzaj"]
            wszystkie.append(trafienie)

    widziane, unikalne = set(), []
    for t in sorted(wszystkie, key=lambda t: t["pozycja"]):
        if t["pozycja"] not in widziane:
            widziane.add(t["pozycja"])
            unikalne.append(t)

    return unikalne


def szukaj_kwoty_w_ocr(ocr_text, grosze):
    """Trafienia danej kwoty w tekście OCR — w każdym zapisie.

    Ten sam kształt wyniku co szukaj_w_ocr.
    """
    if not ocr_text:
        return []

    znorm = normalizuj_do_szukania(ocr_text)
    trafienia = []

    for dop in re.finditer(wzorzec_kwoty(grosze), znorm):
        start, koniec = dop.span()
        od = max(0, start - DLUGOSC_KONTEKSTU)
        do = min(len(ocr_text), koniec + DLUGOSC_KONTEKSTU)
        trafienia.append({
            "pozycja": start,
            "strona": strona_dla_pozycji(ocr_text, start),
            "przed": ocr_text[od:start],
            "trafienie": ocr_text[start:koniec],
            "po": ocr_text[koniec:do],
            "dokladne": True,
        })

    return trafienia


def strona_dla_wartosci(ocr_text, wartosc, potwierdzone=None, rodzaj=None):
    """Strona pierwszego trafienia wartości w tekście OCR albo None.

    W pełni deterministyczne: ta sama wartość i ten sam tekst dają zawsze
    tę samą stronę. Trafienia bez markera strony pomijamy — to tekst sprzed
    pierwszego markera albo wynik z cache zapisany bez markerów; zwrócenie
    None jest wtedy uczciwsze niż zgadywanie.

    `rodzaj` ("data" albo "kwota") włącza szukanie odporne na zapis: data
    zwrócona jako 22-03-2000 zostanie znaleziona jako "22 marca 2000",
    a kwota "450 000,00 zł" jako "450.000,00". Gdy to nie da trafienia
    (albo wartości nie da się odczytać), szukamy zwykłym tekstem.

    Pierwsze trafienie to świadomy wybór: wartości powtarzają się w całym
    dokumencie (miasto, nazwa dewelopera), a analityk zwykle chce zobaczyć,
    gdzie wartość pojawia się po raz pierwszy. Kolejne strony znajdzie
    w szukajce.

    `ocr_text` przychodzi parametrem, a nie z session_state — dzięki temu
    funkcja działa na tekście właściwego dokumentu i da się ją przetestować.
    """
    if rodzaj == "data":
        data = parsuj_date(wartosc)
        if data:
            for trafienie in szukaj_daty_w_ocr(ocr_text, data):
                if trafienie["strona"]:
                    return trafienie["strona"]

    if rodzaj == "kwota":
        strona = strona_dla_kwoty(ocr_text, wartosc)
        if strona:
            return strona

    zapisy = warianty_do_szukania(str(wartosc), potwierdzone)
    trafienia = szukaj_w_ocr_z_wariantami(ocr_text, zapisy)

    # Najpierw wartość przyjęta i jej inne zapisy: klik w pole ma pokazać to,
    # co w polu stoi. Na wartość niezgodną skaczemy dopiero, gdy nic innego
    # nie znaleziono — inaczej analityk trafiłby na "Nowaka" bez ostrzeżenia.
    for trafienie in trafienia:
        if trafienie["strona"] and trafienie["rodzaj"] != "zla":
            return trafienie["strona"]

    for trafienie in trafienia:
        if trafienie["strona"]:
            return trafienie["strona"]

    return None


POLA_DAT = {
    "data_umowy",
    "termin_przeniesienia_wlasnosci",
    "termin_odrebnej_wlasnosci",
}


POLA_KWOT = {
    "cena_nieruchomosci",
    "laczna_wartosc_transakcji",
    "laczna_suma_harmonogramu",
}


def strona_dla_kwoty(ocr_text, kwota, ktora=0):
    """Strona `ktora`-tego (od zera) trafienia kwoty w tekście OCR albo None.

    Gdy trafień jest mniej niż `ktora`+1, bierzemy ostatnie.
    """
    grosze = kwota_na_grosze(kwota)
    if grosze is None or not ocr_text:
        return None

    znorm = normalizuj_do_szukania(ocr_text)

    strony = []
    for dop in re.finditer(wzorzec_kwoty(grosze), znorm):
        strona = strona_dla_pozycji(ocr_text, dop.start())
        if strona:
            strony.append(strona)

    if not strony:
        return None

    return strony[min(ktora, len(strony) - 1)]


def strona_dla_tokenu(ocr_text, token):
    """Strona pierwszego trafienia krótkiego oznaczenia (A3, G26, numer KW).

    Szukamy jako osobnego tokenu, bo zwykłe szukanie podciągu znalazłoby
    "A3" w "A30" i w "KA3" — a tak krótkie oznaczenia to główna zawartość
    elementów tablic.
    """
    if not token or not str(token).strip() or not ocr_text:
        return None

    wzor = r"(?<!\w)" + re.escape(normalizuj_do_szukania(token).strip()) + r"(?!\w)"

    for dop in re.finditer(wzor, normalizuj_do_szukania(ocr_text)):
        strona = strona_dla_pozycji(ocr_text, dop.start())
        if strona:
            return strona

    return None
