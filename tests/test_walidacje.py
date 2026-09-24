import pytest

from app import czy_wartosc_transakcji_zgodna, kwota_transzy, waliduj_nrb, waliduj_pesel


@pytest.mark.parametrize("pesel", ["44051401359", "02070803628", "440 514 013 59"])
def test_pesel_poprawny(pesel):
    assert waliduj_pesel(pesel) == "✅"


@pytest.mark.parametrize("pesel", [
    "44051401358",   # zła cyfra kontrolna
    "4405140135",    # za krótki
    "44023001359",   # 30 lutego
    "44131401359",   # miesiąc 13
])
def test_pesel_niepoprawny(pesel):
    assert waliduj_pesel(pesel) == "❌"


def test_pesel_pusty():
    assert waliduj_pesel(None) == "⚪"


def test_nrb():
    assert waliduj_nrb("61 1090 1014 0000 0712 1981 2874") == "Poprawny strukturalnie"
    assert waliduj_nrb("PL61109010140000071219812874") == "Poprawny strukturalnie"
    assert waliduj_nrb("61 1090 1014 0000 0712 1981 2875") == "Niepoprawna suma kontrolna"
    assert waliduj_nrb("61 1090 1014") == "❌ Niepoprawna długość"
    assert waliduj_nrb(None) == "Brak numeru"


def _wynik(wartosc, *kwoty):
    return {
        "laczna_wartosc_transakcji": wartosc,
        "harmonogram_transz": [{"kwota": k} for k in kwoty],
    }


def test_suma_transz_zgodna():
    assert czy_wartosc_transakcji_zgodna(_wynik("450 000,00 zł", "150 000,00", "300 000,00")) == "✅"


def test_suma_transz_niezgodna():
    assert czy_wartosc_transakcji_zgodna(_wynik("450 000,00 zł", "150 000,00", "299 000,00")) == "❌"


def test_brak_wartosci_transakcji():
    assert czy_wartosc_transakcji_zgodna({"harmonogram_transz": []}) == "⚪"


def test_cena_nieruchomosci_gdy_brak_wartosci_lacznej():
    wynik = {"cena_nieruchomosci": "100 000,00", "harmonogram_transz": [{"kwota": "100 000,00"}]}
    assert czy_wartosc_transakcji_zgodna(wynik) == "✅"


def test_suma_transz_z_kwota_bez_groszy():
    assert czy_wartosc_transakcji_zgodna(_wynik("450 000,00 zł", "150 000,00", "300 000 zł")) == "✅"


def test_transza_procentem_liczona_od_ceny():
    wynik = _wynik("720 000,00 zł", "20% ceny", "216 000,00", "216 000,00", "144 000,00")
    assert czy_wartosc_transakcji_zgodna(wynik) == "✅"


def test_transza_procentem_z_kwota_bierze_kwote():
    assert kwota_transzy("20%, tj. 144 000,00 zł", 72_000_000) == 14_400_000
    assert kwota_transzy("12,5 % ceny", 80_000_000) == 10_000_000


def test_nieczytelna_transza_nie_daje_falszywego_alarmu():
    assert czy_wartosc_transakcji_zgodna(_wynik("450 000,00 zł", "150 000,00", "reszta ceny")) == "⚪"


def test_pusty_harmonogram_nie_do_porownania():
    assert czy_wartosc_transakcji_zgodna(_wynik("450 000,00 zł")) == "⚪"
