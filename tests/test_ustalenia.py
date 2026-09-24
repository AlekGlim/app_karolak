from core.ustalenia import dopasuj_pole, problemy_wg_pola, stan_sekcji, zbierz_problemy


def test_bledny_pesel_daje_ustalenie_wysokie():
    ustalenia = zbierz_problemy({"pesel_1": "44051401358"}, [])
    assert [(u["pole"], u["poziom"]) for u in ustalenia] == [("pesel_1", "wysoki")]


def test_poprawny_wynik_bez_ustalen():
    wynik = {
        "pesel_1": "44051401359",
        "numer_rachunku_powierniczego": "61 1090 1014 0000 0712 1981 2874",
        "laczna_wartosc_transakcji": "100 000,00",
        "harmonogram_transz": [{"kwota": "100 000,00"}],
    }
    assert zbierz_problemy(wynik, [{"status": "zgodne", "tytul": "x", "opis": "y"}]) == []


def test_bledny_rachunek_i_suma_transz():
    wynik = {
        "numer_rachunku_powierniczego": "61 1090 1014 0000 0712 1981 2875",
        "laczna_wartosc_transakcji": "100 000,00",
        "harmonogram_transz": [{"kwota": "90 000,00"}],
    }
    ustalenia = zbierz_problemy(wynik, [])
    assert [u["pole"] for u in ustalenia] == ["numer_rachunku_powierniczego", "laczna_wartosc_transakcji"]
    assert "Różnica: 10 000.00 zł" in ustalenia[1]["opis"]


def test_sortowanie_wysokie_przed_srednimi():
    weryfikacja = [
        {"status": "brak_danych", "tytul": "Brak danych", "opis": "brak"},
        {"status": "niezgodne", "tytul": "Niezgodność nazwiska", "opis": "inne nazwisko"},
    ]
    ustalenia = zbierz_problemy({}, weryfikacja)
    assert [u["poziom"] for u in ustalenia] == ["wysoki", "sredni"]


def test_rozbieznosc_tylko_dla_zlych_wartosci_i_escapowana():
    potwierdzone = [
        {"pole": "data_umowy", "wartosc_glowna": "22-03-2026", "wartosci_ok": ["22 marca 2026"],
         "wartosci_zle": [], "uzasadnienie": ""},
        {"pole": "nabywca_1", "wartosc_glowna": "Jan Kowalski", "wartosci_ok": [],
         "wartosci_zle": ["<b>Nowak</b>"], "uzasadnienie": "Strona 3."},
    ]
    ustalenia = zbierz_problemy({}, [], potwierdzone)
    assert len(ustalenia) == 1
    assert ustalenia[0]["pole"] == "nabywca_1"
    assert ustalenia[0]["poziom"] == "wysoki"
    assert "&lt;b&gt;Nowak&lt;/b&gt;" in ustalenia[0]["opis"]
    assert "Strona 3." in ustalenia[0]["opis"]


def test_dopasuj_pole_nazwisko():
    assert dopasuj_pole("Niezgodność nazwiska", "Nazwisko różni się od UniFlow") == "nabywca_1"
    assert dopasuj_pole("Coś innego", "opis") is None

import pytest


@pytest.mark.parametrize("tytul, opis, pole", [
    ("Niezgodność imienia", "Imię drugiego nabywcy różni się od UniFlow", "nabywca_2"),
    ("Niezgodność PESEL", "PESEL nabywcy różni się od UniFlow", "pesel_1"),
    ("Numer KW", "Brak numeru KW w UniFlow", "numer_kw"),
    ("Księga wieczysta", "Inny numer księgi", "numer_kw"),
    ("Nabywca 2", "Nazwisko różni się od UniFlow", "nabywca_2"),
    ("Liczba wnioskodawców", "W dokumencie 2 nabywców, w UniFlow 1 wnioskodawca", "nabywca_1"),
])
def test_dopasuj_pole_przypadki(tytul, opis, pole):
    assert dopasuj_pole(tytul, opis) == pole


def test_dopasuj_pole_pesel_drugiego_nabywcy():
    assert dopasuj_pole("Niezgodność PESEL", "PESEL drugiego nabywcy różni się") == "pesel_2"


def test_dopasuj_pole_kwota():
    assert dopasuj_pole("Niezgodna kwota", "Kwota ceny różni się") == "cena_nieruchomosci"


def test_problemy_wg_pola_pierwsze_wygrywa():
    ustalenia = [{"pole": "a", "n": 1}, {"pole": "a", "n": 2}, {"pole": None}, {"pole": "b", "n": 3}]
    assert problemy_wg_pola(ustalenia) == {"a": {"pole": "a", "n": 1}, "b": {"pole": "b", "n": 3}}


def test_stan_sekcji():
    wynik = {"a": "x", "b": "  ", "c": "y"}
    assert stan_sekcji(["a", "b", "c", "d"], wynik, {"c"}) == (1, 1, 2)
