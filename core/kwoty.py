"""Kwoty w złotych: odczyt z tekstu i wzorce do szukania w OCR."""

import re


def wyciagnij_kwote(tekst):

    if not tekst:
        return 0

    tekst = str(tekst)

    match = re.search(r'(\d[\d .]*,\d{2})', tekst)

    if not match:
        return 0

    kwota = match.group(1)

    kwota = kwota.replace(" ", "")
    kwota = kwota.replace(".", "")
    kwota = kwota.replace(",", "")

    return int(kwota)


def kwota_na_grosze(tekst):
    """Kwota jako liczba groszy albo None.

    Rozumie "450 000,00 zł", "450.000,00", "450000", "450 000". Ostatni
    separator z 1-2 cyframi po nim to część ułamkowa; z trzema cyframi —
    separator tysięcy ("45.000" to 45 tysięcy, nie 45 zł).

    Własna funkcja, a nie wyciagnij_kwote z aplikacji: tamta wymaga groszy
    w zapisie (kwota bez ",00" daje 0 — błąd z listy).
    """
    if tekst is None:
        return None

    czysty = re.sub(r"(?i)z[łl]\b|pln|\s", "", str(tekst))
    dop = re.fullmatch(r"(\d+(?:[.,]\d{3})*)(?:[.,](\d{1,2}))?", czysty)
    if not dop:
        return None

    zlote = int(re.sub(r"[.,]", "", dop.group(1)))
    grosze = int(dop.group(2).ljust(2, "0")) if dop.group(2) else 0

    return zlote * 100 + grosze


def wzorzec_kwoty(grosze):
    """Wyrażenie regularne dopasowujące daną kwotę w każdym zapisie.

    Separator tysięcy może być spacją, kropką albo go nie być; część
    ułamkowa jest opcjonalna, gdy grosze są zerowe. Lookbehind i lookahead
    pilnują, żeby 500 nie dopasowało się do środka "45 500,00" ani "500 000".
    """
    zlote, gr = divmod(grosze, 100)

    cyfry = str(zlote)
    grupy = []
    while len(cyfry) > 3:
        grupy.insert(0, cyfry[-3:])
        cyfry = cyfry[:-3]
    grupy.insert(0, cyfry)

    calkowita = r"[ .]?".join(grupy)
    ulamek = r"(?:,00)?" if gr == 0 else f",{gr:02d}"

    return r"(?<![\d,.])(?<!\d[ .])" + calkowita + ulamek + r"(?!\d|[ .]\d{3})"
