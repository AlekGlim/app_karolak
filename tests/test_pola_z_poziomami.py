"""Pola z trzema poziomami: spłaszczanie wyniku i podział "ok"/"złe" liczony w Pythonie."""

import json

import pytest

from app import (
    SCHEMY_DIR,
    rodzaj_zapisu,
    rozstrzygnij_podzial,
    splaszcz_wynik,
)


def _pole(glowna, ok=(), zle=(), uzasadnienie=""):
    return {"wartosc_glowna": glowna, "wartosci_ok": list(ok),
            "wartosci_zle": list(zle), "uzasadnienie": uzasadnienie}


def test_splaszcz_zamienia_pole_na_wartosc_glowna():
    wynik = splaszcz_wynik({
        "data_umowy": _pole("2026-03-14", ok=["14 marca 2026"], zle=["15 marca 2026"], uzasadnienie="s. 1 i 9"),
        "pesel_1": _pole("89052112345"),
        "miasto": "Warszawa",
    })

    assert wynik["data_umowy"] == "2026-03-14"
    assert wynik["pesel_1"] == "89052112345"
    assert wynik["miasto"] == "Warszawa"
    assert wynik["rozbieznosci"] == [{
        "pole": "data_umowy",
        "wartosc_glowna": "2026-03-14",
        "wartosci_ok": ["14 marca 2026"],
        "wartosci_zle": ["15 marca 2026"],
        "uzasadnienie": "s. 1 i 9",
    }]


def test_splaszcz_puste_pole_to_brak_wartosci():
    wynik = splaszcz_wynik({"nabywca_2": _pole("")})
    assert wynik["nabywca_2"] is None
    assert wynik["rozbieznosci"] == []


def test_splaszcz_przepuszcza_stary_ksztalt_wyniku():
    stary = {"data_umowy": "14-03-2026", "rozbieznosci": [{"pole": "data_umowy"}]}
    assert splaszcz_wynik(stary) == stary


def test_splaszcz_nie_zmienia_wejscia():
    wejscie = {"data_umowy": _pole("2026-03-14")}
    splaszcz_wynik(wejscie)
    assert wejscie == {"data_umowy": _pole("2026-03-14")}


@pytest.mark.parametrize("pole, glowna, zapis, rodzaj", [
    ("data_umowy", "2026-03-14", "14 marca 2026", "ok"),
    ("data_umowy", "2026-03-14", "14.03.2026 r.", "ok"),
    ("data_umowy", "2026-03-14", "15 marca 2026", "zla"),
    ("data_umowy", "2026-03-14", "14 marca", None),                 # bez roku — decyduje model
    ("numer_kw", "WA1M/00123456/7", "WA1M 00123456 7", "ok"),
    ("numer_kw", "WA1M/00123456/7", "WA1M/0O123456/7", "zla"),       # O zamiast zera
    ("numer_kw", "WA1M/00123456/7, WA1M/00654321/3", "WA1M/00123456/7", None),  # kilka ksiąg
    ("pesel_1", "89052112345", "89052112346", "zla"),
    ("numer_dzialki", "12/5", "12 / 5", "ok"),
    ("numer_dzialki", "12/5", "dz. 12/5", None),                     # różnią się tylko litery
    ("otwarty_numer_rachunku_powierniczego", "03 1090 1234 0000 0001 2345 1234",
     "03109012340000000123451234", "ok"),
    ("nabywca_1", "Adam Nowak", "Nowaka", None),                     # osoby — zawsze model
    ("numer_umowy", "Repertorium A Nr 1123/2026", "Rep. A nr 1123/2026", None),
])
def test_rodzaj_zapisu(pole, glowna, zapis, rodzaj):
    assert rodzaj_zapisu(pole, glowna, zapis) == rodzaj


def test_rozstrzygnij_podzial_poprawia_model():
    potwierdzone = [{
        "pole": "data_umowy",
        "wartosc_glowna": "2026-03-14",
        "wartosci_ok": ["14 marca 2026", "15 marca 2026"],   # model pomylił się przy drugiej
        "wartosci_zle": [],
        "uzasadnienie": "",
    }, {
        "pole": "nabywca_2",
        "wartosc_glowna": "Maria Nowak",
        "wartosci_ok": ["Marii Nowak"],
        "wartosci_zle": ["Kowalska"],
        "uzasadnienie": "",
    }]

    wynik = rozstrzygnij_podzial(potwierdzone)

    assert wynik[0]["wartosci_ok"] == ["14 marca 2026"]
    assert wynik[0]["wartosci_zle"] == ["15 marca 2026"]
    assert wynik[1]["wartosci_ok"] == ["Marii Nowak"]
    assert wynik[1]["wartosci_zle"] == ["Kowalska"]


def test_schemat_pola_z_poziomami():
    schema = json.loads((SCHEMY_DIR / "umowa_deweloperska.json").read_text(encoding="utf-8"))
    wlasciwosci = schema["properties"]

    assert "rozbieznosci" not in wlasciwosci

    z_poziomami = [k for k, v in wlasciwosci.items() if v.get("type") == "object"]
    assert "data_umowy" in z_poziomami and "numer_kw" in z_poziomami
    for klucz in z_poziomami:
        pola = wlasciwosci[klucz]["properties"]
        assert set(pola) == {"wartosc_glowna", "wartosci_ok", "wartosci_zle", "uzasadnienie"}, klucz
        assert pola["wartosci_ok"]["type"] == pola["wartosci_zle"]["type"] == "array"
