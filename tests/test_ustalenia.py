import pytest

from app import (
    _znacznik_pola,
    dopasuj_pole,
    etykieta_sekcji,
    problemy_wg_pola,
    stan_do_naglowka,
    stan_sekcji,
    zbierz_problemy,
    zweryfikuj_zrodla,
)


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


def test_rozbieznosc_tylko_dla_zlych_wartosci():
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
    # surowy tekst — escapuje dopiero miejsce, które wstawia go do HTML
    assert "<b>Nowak</b>" in ustalenia[0]["opis"]
    assert "Strona 3." in ustalenia[0]["opis"]


def test_dymek_rozbieznosci_escapowany_raz():
    problem = {"opis": 'litera "O" zamiast zera', "krok": "Sprawdź <b>skan</b>."}
    znacznik = _znacznik_pola(problem)
    assert "&quot;O&quot;" in znacznik
    assert "&amp;" not in znacznik
    assert "&lt;b&gt;skan" in znacznik


def test_pole_wskazane_przez_model_wygrywa_ze_zgadywaniem():
    wpis = {
        "status": "niezgodne",
        "pole": "nabywca_2",
        "tytul": "Niezgodność nazwiska",
        "opis": "Nazwisko drugiego nabywcy w umowie (Nowak) różni się od danych UniFlow (Kowalska); PESEL zgodny.",
    }
    assert zbierz_problemy({}, [wpis])[0]["pole"] == "nabywca_2"


def test_puste_pole_od_modelu_nie_przypina_ostrzezenia():
    wpis = {"status": "niezgodne", "pole": "", "tytul": "Liczba nabywców",
            "opis": "W umowie 2 nabywców, w UniFlow 1 wnioskodawca."}
    assert zbierz_problemy({}, [wpis])[0]["pole"] is None


def test_bez_pola_nazwisko_wygrywa_z_pesel_zgodny():
    # wynik z cache sprzed klucza "pole" — zgadywanie po słowach
    opis = "Nazwisko drugiego nabywcy w umowie (Nowak) różni się od danych UniFlow (Kowalska); PESEL zgodny."
    assert dopasuj_pole("Niezgodność nazwiska", opis) == "nabywca_2"


@pytest.mark.parametrize("status, fragment", [
    ("niezgodne", "Ustal przyczynę"),
    ("do_wyjasnienia", "ta sama osoba"),
    ("brak_danych", "Uzupełnij brakujące dane"),
])
def test_krok_zalezy_od_statusu(status, fragment):
    wpis = {"status": status, "pole": "nabywca_1", "tytul": "t", "opis": "o"}
    assert fragment in zbierz_problemy({}, [wpis])[0]["krok"]


def test_dopasuj_pole_nazwisko():
    assert dopasuj_pole("Niezgodność nazwiska", "Nazwisko różni się od UniFlow") == "nabywca_1"
    assert dopasuj_pole("Coś innego", "opis") is None


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
    stany = ["ok", "odmiana", "rozbieznosc", "niepewne", "brak", "brak"]
    assert stan_sekcji(stany) == (2, 1, 1, 2)


def test_naglowek_liczy_brak_zrodla_jak_znacznik_przy_polu():
    ocr = "[STRONA_1]\nCena lokalu wynosi 685 000,00 zł."
    zrodla = zweryfikuj_zrodla(ocr, [
        {"pole": "cena_nieruchomosci", "strona": 1, "cytat": "Cena lokalu wynosi 685 000,00 zł"},
        {"pole": "numer_lokalu", "strona": 1, "cytat": "lokal mieszkalny nr 42"},
    ])
    wynik = {"cena_nieruchomosci": "685 000,00 zł", "numer_lokalu": "42", "numer_kw": ""}

    stany = [stan_do_naglowka(k, wynik.get(k), {}, ocr, None, zrodla)
             for k in ("cena_nieruchomosci", "numer_lokalu", "numer_kw")]

    assert stany == ["ok", "brak", "brak"]
    assert etykieta_sekcji("💰", "Transakcja", stany) == ("💰 TRANSAKCJA　✕ 2  ✓ 1", True)
