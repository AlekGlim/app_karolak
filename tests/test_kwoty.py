import re

import pytest

from app import kwota_na_grosze, wyciagnij_kwote, wzorzec_kwoty


@pytest.mark.parametrize("tekst, grosze", [
    ("450 000,00 zł", 45_000_000),
    ("450.000,00", 45_000_000),
    ("450000", 45_000_000),
    ("450 000 PLN", 45_000_000),
    ("45.000", 4_500_000),       # trzy cyfry po kropce to tysiące
    ("12,5", 1_250),
    ("1 234,56 zł", 123_456),
])
def test_kwota_na_grosze(tekst, grosze):
    assert kwota_na_grosze(tekst) == grosze


@pytest.mark.parametrize("tekst", [None, "", "abc", "12,3456"])
def test_kwota_na_grosze_nieczytelna(tekst):
    assert kwota_na_grosze(tekst) is None


@pytest.mark.parametrize("zapis", ["450 000,00", "450.000,00", "450000", "450 000"])
def test_wzorzec_kwoty_lapie_rozne_zapisy(zapis):
    assert re.search(wzorzec_kwoty(45_000_000), f"cena {zapis} zł")


@pytest.mark.parametrize("tekst", ["1 450 000,00", "4 500 000", "450 0001"])
def test_wzorzec_kwoty_nie_lapie_innej_kwoty(tekst):
    assert not re.search(wzorzec_kwoty(45_000_000), tekst)


def test_wzorzec_kwoty_nie_lapie_kwoty_z_innymi_groszami():
    assert not re.search(wzorzec_kwoty(45_000_000), "450 000,50")


def test_wyciagnij_kwote_z_groszami():
    assert wyciagnij_kwote("450 000,00 zł") == 45_000_000
    assert wyciagnij_kwote(None) == 0


@pytest.mark.parametrize("tekst, grosze", [
    ("450 000 zł", 45_000_000),
    ("450000", 45_000_000),
    ("50 000 zł (zadatek)", 5_000_000),
    ("transza 1: 150 000,00 zł", 15_000_000),
    ("brak kwoty", 0),
])
def test_wyciagnij_kwote_bez_groszy(tekst, grosze):
    assert wyciagnij_kwote(tekst) == grosze
