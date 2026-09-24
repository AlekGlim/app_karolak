"""Weryfikacja rozbieżności zgłoszonych przez model z tekstem OCR."""

import re

from core.tekst import normalizuj_do_porownania


def wariant_stoi_w_tekscie(znorm_ocr, znorm_wariant):
    """Czy wariant występuje w tekście jako osobny token.

    Sprawdzamy, czy tuż przed i tuż po trafieniu nie stoi litera ani cyfra —
    bez tego wariant "123" zostałby potwierdzony przez "1234" albo "A123",
    a to inny numer.
    """
    if not znorm_wariant:
        return False

    wzor = r"(?<!\w)" + re.escape(znorm_wariant) + r"(?!\w)"
    return re.search(wzor, znorm_ocr) is not None


def zweryfikuj_warianty(ocr_text, rozbieznosci):
    """Odsiewa wartości, których nie ma w tekście OCR.

    Zwraca dwie listy:
      potwierdzone — elementy w formacie z modelu, ale wyłącznie z wartościami
                     potwierdzonymi w tekście; element bez żadnej potwierdzonej
                     wartości znika w całości
      odrzucone    — [{"pole": ..., "wartosc": ...}] — wartości zmyślone
                     przez model; ich liczba to tania miara jakości promptu

    Zachowujemy podział modelu na `wartosci_ok` i `wartosci_zle` — nie
    poprawiamy go. Sprawdzamy wyłącznie obecność: wartość musi stać w tekście
    dosłownie, jako osobny token (wielkość liter i układ spacji nie mają
    znaczenia). Prompt każe modelowi przepisywać wartości dokładnie z tekstu,
    więc wartość, której tam nie ma, jest błędem modelu, a nie innym zapisem.

    Wartość identyczna z wartością główną (po normalizacji) i powtórzenia są
    pomijane po cichu — to nie halucynacja, tylko szum, więc nie zawyżają
    licznika odrzuconych. Wartość obecna zarazem w "ok" i w "złe" liczy się
    jako "złe": lepiej pokazać analitykowi za dużo niż przemilczeć.

    Bez tekstu OCR nic nie da się potwierdzić, więc zwracamy puste listy
    (a nie "wszystko odrzucone" — brak tekstu to nie wina modelu).
    """
    potwierdzone = []
    odrzucone = []

    if not ocr_text or not isinstance(rozbieznosci, list):
        return potwierdzone, odrzucone

    znorm_ocr = normalizuj_do_porownania(ocr_text)

    def lista_wartosci(surowa):
        # model bywa niedbały — zamiast listy może dać napis albo nic
        if not surowa:
            return []
        if isinstance(surowa, str):
            return [surowa]
        return list(surowa)

    for wpis in rozbieznosci:
        if not isinstance(wpis, dict):
            continue

        pole = wpis.get("pole")
        glowna = str(wpis.get("wartosc_glowna") or "").strip()

        widziane = {normalizuj_do_porownania(glowna)}
        potwierdzone_ok = []
        potwierdzone_zle = []

        # "złe" przetwarzamy pierwsze, żeby wartość obecna w obu listach
        # została w "złe" (patrz docstring)
        for wartosc in lista_wartosci(wpis.get("wartosci_zle")):
            wartosc = str(wartosc).strip()
            znorm = normalizuj_do_porownania(wartosc)

            if not znorm or znorm in widziane:
                continue
            widziane.add(znorm)

            if wariant_stoi_w_tekscie(znorm_ocr, znorm):
                potwierdzone_zle.append(wartosc)
            else:
                odrzucone.append({"pole": pole, "wartosc": wartosc})

        for wartosc in lista_wartosci(wpis.get("wartosci_ok")):
            wartosc = str(wartosc).strip()
            znorm = normalizuj_do_porownania(wartosc)

            if not znorm or znorm in widziane:
                continue
            widziane.add(znorm)

            if wariant_stoi_w_tekscie(znorm_ocr, znorm):
                potwierdzone_ok.append(wartosc)
            else:
                odrzucone.append({"pole": pole, "wartosc": wartosc})

        if potwierdzone_ok or potwierdzone_zle:
            potwierdzone.append({
                "pole": pole,
                "wartosc_glowna": glowna,
                "wartosci_ok": potwierdzone_ok,
                "wartosci_zle": potwierdzone_zle,
                "uzasadnienie": str(wpis.get("uzasadnienie") or "").strip(),
            })

    return potwierdzone, odrzucone
