"""Kwoty w złotych: odczyt z tekstu i wzorce do szukania w OCR."""

import re


def wyciagnij_kwote(tekst):
    """Kwota w groszach z tekstu pola albo 0.

    Kolejno próbujemy:
      1. kwoty z groszami gdziekolwiek w tekście ("transza 1: 150 000,00 zł")
      2. całego pola jako kwoty ("450 000", "450 000 zł")
      3. kwoty bez groszy zakończonej walutą ("50 000 zł (zadatek)")

    Bez kroków 2-3 kwota zapisana bez ",00" dawała 0 i suma transz
    fałszywie nie zgadzała się z wartością transakcji.
    """
    if not tekst:
        return 0

    tekst = str(tekst)

    match = re.search(r'(\d[\d .]*,\d{2})', tekst)
    if match:
        return int(re.sub(r"[ .,]", "", match.group(1)))

    cale_pole = kwota_na_grosze(tekst)
    if cale_pole is not None:
        return cale_pole

    match = re.search(r"(\d{1,3}(?:[ .]\d{3})+|\d+)\s*(?:zł|zl|pln)", tekst, re.IGNORECASE)
    if match:
        return kwota_na_grosze(match.group(1)) or 0

    return 0


def kwota_na_grosze(tekst):
    """Kwota jako liczba groszy albo None.

    Rozumie "450 000,00 zł", "450.000,00", "450000", "450 000". Ostatni
    separator z 1-2 cyframi po nim to część ułamkowa; z trzema cyframi —
    separator tysięcy ("45.000" to 45 tysięcy, nie 45 zł).
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
    pilnują, żeby 500 nie dopasowało się do środka "45 500,00" ani "500 000",
    a kwota bez groszy nie złapała "450 000,50".
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

    return r"(?<![\d,.])(?<!\d[ .])" + calkowita + ulamek + r"(?!\d|,\d|[ .]\d{3})"


# Zapis, który na pewno jest kwotą: z separatorem tysięcy albo z groszami.
# Same cyfry ("2026", PESEL, numer działki) kwotą nie są.
WZORZEC_ZAPISU_KWOTY = re.compile(r"\d{1,3}(?:[ .]\d{3})+(?:,\d{1,2})?|\d+,\d{1,2}")


def kwota_z_frazy(tekst):
    """Grosze, gdy fraza wygląda na kwotę; w przeciwnym razie None."""
    if tekst is None:
        return None

    czysty = re.sub(r"(?i)\s*(?:z[łl]|pln)\.?\s*$", "", str(tekst).strip())
    if not WZORZEC_ZAPISU_KWOTY.fullmatch(czysty):
        return None

    return kwota_na_grosze(czysty)
