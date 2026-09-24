"""Ustalenia do panelu analityka: walidacje, rozbieżności i weryfikacja UniFlow."""

import html

from core.kwoty import wyciagnij_kwote
from core.tekst import normalizuj_do_szukania
from core.walidacje import czy_wartosc_transakcji_zgodna, waliduj_nrb, waliduj_pesel


# Waga ustalenia dla wartości "złych", zależna od tego, czego dotyczy pole.
# Inna data albo inna osoba to sprzeczność w treści dokumentu — waga wysoka.
# Identyfikator odczytany inaczej to najczęściej wada OCR — waga średnia.
POZIOM_ROZBIEZNOSCI = {
    "data_umowy": "wysoki",
    "termin_przeniesienia_wlasnosci": "wysoki",
    "termin_odrebnej_wlasnosci": "wysoki",
    "nabywca_1": "wysoki",
    "nabywca_2": "wysoki",
    "nazwa_dewelopera": "wysoki",
    "numer_umowy": "sredni",
    "nip_dewelopera": "sredni",
    "pesel_1": "sredni",
    "pesel_2": "sredni",
    "numer_dzialki": "sredni",
    "numer_kw": "sredni",
    "numer_rachunku_powierniczego": "sredni",
    "otwarty_numer_rachunku_powierniczego": "sredni",
}


ETYKIETY_POL_ROZBIEZNOSCI = {
    "numer_umowy": "Numer umowy",
    "nip_dewelopera": "NIP dewelopera",
    "pesel_1": "PESEL nabywcy 1",
    "pesel_2": "PESEL nabywcy 2",
    "numer_dzialki": "Numer działki",
    "numer_kw": "Numer księgi wieczystej",
    "numer_rachunku_powierniczego": "Numer rachunku powierniczego",
    "otwarty_numer_rachunku_powierniczego": "Otwarty numer rachunku powierniczego",
    "data_umowy": "Data umowy",
    "termin_przeniesienia_wlasnosci": "Termin przeniesienia własności",
    "termin_odrebnej_wlasnosci": "Termin ustanowienia odrębnej własności",
    "nabywca_1": "Nabywca 1",
    "nabywca_2": "Nabywca 2",
    "nazwa_dewelopera": "Deweloper",
}


def stan_sekcji(klucze, wynik, problemy):
    """Zlicza pola sekcji: wypełnione, z problemem, brakujące.

    `problemy` to zbiór kluczy pól z rozbieżnością (patrz zbierz_problemy).
    """
    ok = z_problemem = brak = 0

    for klucz in klucze:
        wartosc = wynik.get(klucz)

        if klucz in problemy:
            z_problemem += 1
        elif wartosc and str(wartosc).strip():
            ok += 1
        else:
            brak += 1

    return ok, z_problemem, brak


# Mapowanie tytułów weryfikacji UniFlow na pola, których dotyczą.
# Model zwraca luźne tytuły, więc dopasowujemy po słowach kluczowych —
# dzięki temu ostrzeżenie trafia też do dymka przy konkretnym polu.
SLOWA_KLUCZOWE_POL = {
    "nabywca_1": ["nabywc", "wnioskodawc", "imi", "nazwisk"],
    "pesel_1": ["pesel"],
    "numer_kw": ["ksi", "wieczyst", "kw"],
    "nazwa_dewelopera": ["dewelop"],
    "cena_nieruchomosci": ["cen", "kwot", "warto"],
    "miasto": ["miejscowo", "miast"],
    "ulica": ["ulic", "adres"],
}


def dopasuj_pole(tytul, opis):
    """Zgaduje, którego pola dotyczy wpis weryfikacji."""
    tekst = normalizuj_do_szukania(f"{tytul} {opis}")

    for pole, slowa in SLOWA_KLUCZOWE_POL.items():
        if any(slowo in tekst for slowo in slowa):
            return pole

    return None


def zbierz_problemy(wynik, lista_weryfikacji, potwierdzone=None):
    """Buduje listę ustaleń wymagających decyzji analityka.

    Łączy dwa źródła o różnej wiarygodności:
      - weryfikację UniFlow zwróconą przez model (miękka, opisowa)
      - twarde walidacje liczone w Pythonie (suma kontrolna, arytmetyka)

    Te drugie są pewniejsze, więc idą na górę listy.

    `potwierdzone` (wynik potwierdzone_rozbieznosci) dodaje ustalenia o polach,
    które w dokumencie występują w niezgodnych wartościach (inna data, inna
    osoba, identyfikator odczytany inaczej) — tylko dla wartości, które
    naprawdę stoją w tekście OCR. Waga zależy od kategorii.

    Zgodności NIE trafiają do wyniku — panel, który potwierdza oczywistości,
    przestaje być czytany po kilku analizach.
    """
    ustalenia = []

    # --- twarde walidacje ---
    for numer in ("1", "2"):
        pesel = wynik.get(f"pesel_{numer}")
        if pesel and waliduj_pesel(pesel) == "❌":
            ustalenia.append({
                "pole": f"pesel_{numer}",
                "poziom": "wysoki",
                "tytul": f"PESEL nabywcy {numer} — błędna suma kontrolna",
                "opis": f"Odczytana wartość: {pesel}. Numer jest wewnętrznie niespójny.",
                "krok": "Sprawdź numer w dokumencie — prawdopodobny błąd odczytu OCR.",
            })

    rachunek = wynik.get("numer_rachunku_powierniczego")
    if rachunek:
        status = waliduj_nrb(rachunek)
        if status not in ("Poprawny strukturalnie", "Brak numeru"):
            ustalenia.append({
                "pole": "numer_rachunku_powierniczego",
                "poziom": "wysoki",
                "tytul": "Rachunek powierniczy — błędny numer",
                "opis": f"{status}. Odczytana wartość: {rachunek}",
                "krok": "Zweryfikuj numer przed uruchomieniem transz.",
            })

    if czy_wartosc_transakcji_zgodna(wynik) == "❌":
        cena = wyciagnij_kwote(
            wynik.get("laczna_wartosc_transakcji") or wynik.get("cena_nieruchomosci")
        )
        suma = sum(
            wyciagnij_kwote(t.get("kwota"))
            for t in wynik.get("harmonogram_transz", [])
        )
        roznica = abs(cena - suma) / 100
        ustalenia.append({
            "pole": "laczna_wartosc_transakcji",
            "poziom": "sredni",
            "tytul": "Suma transz nie zgadza się z wartością transakcji",
            "opis": (
                f"Wartość transakcji: {cena / 100:,.2f} zł. "
                f"Suma transz: {suma / 100:,.2f} zł. "
                f"Różnica: {roznica:,.2f} zł."
            ).replace(",", " "),
            "krok": "Sprawdź harmonogram — możliwy błąd odczytu kwoty transzy.",
        })

    # --- rozbieżności w dokumencie, potwierdzone w tekście OCR ---
    # Ustalenie tworzą tylko wartości "złe". Wartości "ok" (ta sama data
    # w innym zapisie, odmiana nazwiska) to zwykła umowa i panel ma o nich
    # milczeć — służą wyłącznie do szukania stron.
    #
    # Tytuł i opis zawierają tekst z OCR i od modelu, a panel_ustalen renderuje
    # HTML bez escapowania — dlatego escapujemy tutaj. Gdy naprawisz to w samym
    # panel_ustalen (błąd nr 4 z listy), usuń stąd html.escape, żeby nie
    # escapować dwa razy.
    for wpis in (potwierdzone or []):
        if not wpis["wartosci_zle"]:
            continue

        pole = wpis["pole"]
        etykieta = ETYKIETY_POL_ROZBIEZNOSCI.get(pole, pole)

        opis = (
            f"Przyjęta wartość: {wpis['wartosc_glowna']}. "
            f"W dokumencie występuje też: {', '.join(wpis['wartosci_zle'])}."
        )
        if wpis["uzasadnienie"]:
            opis += f" {wpis['uzasadnienie']}"

        ustalenia.append({
            "pole": pole,
            "poziom": POZIOM_ROZBIEZNOSCI.get(pole, "sredni"),
            "tytul": html.escape(f"Pole „{etykieta}” — niezgodne wartości w dokumencie"),
            "opis": html.escape(opis),
            "krok": "Sprawdź na skanie, która wartość jest prawidłowa (możliwa pomyłka OCR albo niespójność dokumentu).",
        })

    # --- weryfikacja UniFlow z modelu: tylko to, co NIE jest zgodne ---
    for wpis in (lista_weryfikacji or []):
        status = str(wpis.get("status", "")).lower().strip()

        if status == "zgodne":
            continue

        tytul = wpis.get("tytul", "")
        opis = wpis.get("opis", "")

        ustalenia.append({
            "pole": dopasuj_pole(tytul, opis),
            "poziom": "wysoki" if status == "niezgodne" else "sredni",
            "tytul": tytul,
            "opis": opis,
            "krok": (
                "Ustal przyczynę rozbieżności i udokumentuj."
                if status == "niezgodne"
                else "Uzupełnij brakujące dane przed zakończeniem analizy."
            ),
        })

    kolejnosc = {"wysoki": 0, "sredni": 1}
    ustalenia.sort(key=lambda u: kolejnosc.get(u["poziom"], 2))
    return ustalenia


def problemy_wg_pola(ustalenia):
    """Mapa pole -> ustalenie, do dymków przy polach."""
    mapa = {}
    for ustalenie in ustalenia:
        if ustalenie.get("pole"):
            mapa.setdefault(ustalenie["pole"], ustalenie)
    return mapa
