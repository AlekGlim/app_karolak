"""Twarde walidacje liczone w Pythonie: PESEL, NRB, suma harmonogramu."""

from datetime import datetime

from core.kwoty import wyciagnij_kwote


def waliduj_nrb(numer):

    if not numer:
        return "Brak numeru"

    nrb = "".join(filter(str.isdigit, str(numer)))

    if len(nrb) != 26:
        return "❌ Niepoprawna długość"

    try:
        liczba = nrb[2:] + "2521" + nrb[:2]

        if int(liczba) % 97 == 1:
            return "Poprawny strukturalnie"

        return "Niepoprawna suma kontrolna"

    except Exception:
        return "Błąd walidacji"


def waliduj_pesel(pesel):

    if not pesel:
        return "⚪"

    pesel = "".join(filter(str.isdigit, str(pesel)))

    if len(pesel) != 11:
        return "❌"

    try:

        rok = int(pesel[0:2])
        miesiac = int(pesel[2:4])
        dzien = int(pesel[4:6])

        if 1 <= miesiac <= 12:
            rok += 1900

        elif 21 <= miesiac <= 32:
            rok += 2000
            miesiac -= 20

        elif 41 <= miesiac <= 52:
            rok += 2100
            miesiac -= 40

        elif 61 <= miesiac <= 72:
            rok += 2200
            miesiac -= 60

        elif 81 <= miesiac <= 92:
            rok += 1800
            miesiac -= 80

        else:
            return "❌"

        datetime(rok, miesiac, dzien)

        wagi = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]

        suma = sum(
            int(c) * w
            for c, w in zip(pesel[:10], wagi)
        )

        kontrolna = (10 - (suma % 10)) % 10

        if kontrolna != int(pesel[10]):
            return "❌"

        return "✅"

    except Exception:
        return "❌"


def czy_wartosc_transakcji_zgodna(wynik):

    cena = wyciagnij_kwote(
        wynik.get("laczna_wartosc_transakcji")
        or wynik.get("cena_nieruchomosci")
    )

    if cena == 0:
        return "⚪"

    suma = sum(
        wyciagnij_kwote(t.get("kwota"))
        for t in wynik.get("harmonogram_transz", [])
    )

    return "✅" if cena == suma else "❌"
