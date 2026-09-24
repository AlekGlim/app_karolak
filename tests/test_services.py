import importlib
import sys
import types
from datetime import datetime

import pandas as pd
import pytest

from app import czy_poprawny_numer_wniosku
import app
from app import analizuj
from app import SZABLON_PROMPTU, klucz_wersji, wczytaj_schema, zbuduj_prompt

UNIFLOW = {"numer_wniosku": "KHB1553044", "wnioskodawcy": [{"IMIE": "Adam", "NAZWISKO": "Nowak"}]}


# --- numer wniosku ---

@pytest.mark.parametrize("numer", ["KHB1553044", "WN/2026/00184521", "a-b_c.d"])
def test_poprawny_numer_wniosku(numer):
    assert czy_poprawny_numer_wniosku(numer)


@pytest.mark.parametrize("numer", ["", None, "KHB' OR '1'='1", "KHB;DROP", "KHB 1", "/KHB", "x" * 65])
def test_niepoprawny_numer_wniosku(numer):
    assert not czy_poprawny_numer_wniosku(numer)


# --- schematy i prompt ---

def test_prompt_identyczny_z_wczesniejszym_f_stringiem():
    tekst_uniflow = '{\n  "a": 1\n}'
    ocr_z_numerami_stron = "[STRONA_1]\ntreść {z klamrami}"
    # dokładnie ten f-string stał wcześniej w uruchom_analize
    oczekiwany = f"""
        DANE KLIENTÓW Z SYSTEMU UNIFLOW:

        {tekst_uniflow}

        PONIŻEJ ZNAJDUJE SIĘ TREŚĆ DOKUMENTU.

        Porównuj dane klientów z UniFlow z danymi nabywców
        występującymi w dokumencie.

        TREŚĆ DOKUMENTU:

        {ocr_z_numerami_stron}
        """
    assert zbuduj_prompt({"a": 1}, ocr_z_numerami_stron) == oczekiwany


def test_klucz_wersji_zalezy_od_uniflow_i_schematu():
    schema = wczytaj_schema("umowa_deweloperska")
    bazowy = klucz_wersji(schema, UNIFLOW)

    assert klucz_wersji(schema, UNIFLOW) == bazowy
    assert klucz_wersji(schema, {**UNIFLOW, "wnioskodawcy": []}) != bazowy
    assert klucz_wersji({**schema, "title": "inny"}, UNIFLOW) != bazowy
    assert len(bazowy) == 64
    assert "{ocr_text}" in SZABLON_PROMPTU


def test_nieznany_typ_dokumentu():
    with pytest.raises(ValueError):
        wczytaj_schema("umowa_kupna_sprzedazy")


# --- analiza ---

class Zrodla:
    """Atrapa hurtowni i API, która zapisuje wywołania."""
    NAZWA = "Atrapa"

    def __init__(self, cache=None, blad_zapisu=None):
        self.cache = cache
        self.blad_zapisu = blad_zapisu
        self.zapisy = []
        self.prompty = []

    def get_document_cache(self, pdf_hash, nr_wniosku, hash_schematu):
        return self.cache

    def save_document_cache(self, **kwargs):
        if self.blad_zapisu:
            raise self.blad_zapisu
        self.zapisy.append(kwargs)

    def wywolaj_ocr(self, plik_bajty, token, document_group_id):
        return "strona pierwsza&lt;!-- PageBreak --&gt;strona druga"

    def wywolaj_extract(self, tekst, token, document_id, schema):
        self.prompty.append(tekst)
        return {"numer_umowy": "1/2026"}


def _analizuj(zrodla, **kwargs):
    return analizuj(
        plik_bajty=b"%PDF-demo",
        nazwa_pliku="umowa.pdf",
        nr_wniosku="KHB1553044",
        token="t",
        dane_uniflow=UNIFLOW,
        typ_dokumentu="umowa_deweloperska",
        zrodla=zrodla,
        **kwargs,
    )


def test_pelna_analiza_zapisuje_cache_z_markerami_stron():
    zrodla = Zrodla()
    kroki = []
    analiza = _analizuj(zrodla, postep=lambda p, opis: kroki.append(p))

    assert analiza.wynik_surowy == {"numer_umowy": "1/2026"}
    assert analiza.ocr_text == "\n\n[STRONA_1]\nstrona pierwsza\n\n[STRONA_2]\nstrona druga"
    assert analiza.zrodlo == "Atrapa"
    assert analiza.ostrzezenia == []
    assert kroki == [20, 70, 100]
    assert zrodla.zapisy[0]["ocr_text"] == analiza.ocr_text
    assert "Nowak" in zrodla.prompty[0]


def test_trafienie_w_cache_pomija_ocr_i_ekstrakcje():
    zrodla = Zrodla(cache={"wynik": {"z": "cache"}, "ocr_text": "[STRONA_1]\nx"})
    analiza = _analizuj(zrodla)

    assert analiza.wynik_surowy == {"z": "cache"}
    assert analiza.zrodlo == "Cache Impala"
    assert zrodla.prompty == []


def test_wymuszona_analiza_ignoruje_cache():
    zrodla = Zrodla(cache={"wynik": {"z": "cache"}, "ocr_text": ""})
    assert _analizuj(zrodla, wymus=True).wynik_surowy == {"numer_umowy": "1/2026"}


def test_blad_zapisu_do_cache_nie_kasuje_wyniku():
    zrodla = Zrodla(blad_zapisu=RuntimeError("Kerberos"))
    analiza = _analizuj(zrodla)

    assert analiza.wynik_surowy == {"numer_umowy": "1/2026"}
    assert len(analiza.ostrzezenia) == 1
    assert "Kerberos" in analiza.ostrzezenia[0]


def test_blad_ekstrakcji_przerywa_analize():
    zrodla = Zrodla()
    zrodla.wywolaj_extract = lambda *a: (_ for _ in ()).throw(TimeoutError("limit"))
    with pytest.raises(TimeoutError):
        _analizuj(zrodla)
    assert zrodla.zapisy == []


# --- tryb offline ---

def test_offline_wnioskodawcy_i_ocr_z_pdf():
    assert len(app.offline_load_wnioskodawcy("KHB1553044")) == 2
    assert app.offline_load_wnioskodawcy("INNY").empty

    with open("dev/umowa_demo.pdf", "rb") as f:
        ocr = app.offline_wywolaj_ocr(f.read(), "t", "KHB1553044")

    assert ocr.count(app.ZNACZNIK_STRONY) == 2
    assert "Repertorium A Nr 1123/2026" in ocr


def test_offline_wynik_zgodny_ze_schematem():
    schema = wczytaj_schema("umowa_deweloperska")
    wynik = app.offline_wywolaj_extract("", "t", "x", schema)
    assert set(wynik) <= set(schema["properties"])
    assert set(schema["required"]) <= set(wynik)
    for klucz, definicja in schema["properties"].items():
        if definicja.get("type") == "object":
            assert set(wynik[klucz]) == set(definicja["properties"]), klucz


# --- hurtownia, data_loader.py (moduły serwera podstawione atrapami) ---

@pytest.fixture
def hurtownia(monkeypatch):
    zapytania, inserty = [], []

    config = types.SimpleNamespace(
        username="u", domena="@d", database="db", database_result="dbr",
        param_bs_params_impala_host="h", param_bs_params_krb_host="k",
    )

    def hadoop_execute_df(username, domena, database, query):
        zapytania.append(query)
        return pd.DataFrame()

    class ImpalaConnector:
        def kinit(self, **k): pass
        def connect(self, **k): pass
        def execute(self, sql): pass
        def insert_df(self, df, db, tabela, partycja, batch):
            inserty.append(partycja)
            raise RuntimeError("insert padł")
        def close(self): inserty.append("zamknięte")

    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))
    sys.modules["config"].__dict__.update(vars(config))
    monkeypatch.setitem(sys.modules, "helpers", types.SimpleNamespace(hadoop_execute_df=hadoop_execute_df))
    monkeypatch.setitem(sys.modules, "impala_connector", types.ModuleType("impala_connector"))
    monkeypatch.setitem(
        sys.modules, "impala_connector.impala_connector",
        types.SimpleNamespace(ImpalaConnector=ImpalaConnector),
    )
    monkeypatch.delitem(sys.modules, "data_loader", raising=False)

    modul = importlib.import_module("data_loader")
    modul.load_wnioskodawcy.clear()
    modul._zapytania, modul._inserty = zapytania, inserty
    yield modul
    sys.modules.pop("data_loader", None)


def test_hurtownia_odrzuca_sql_injection(hurtownia):
    with pytest.raises(ValueError):
        hurtownia.load_wnioskodawcy("KHB' OR '1'='1")
    with pytest.raises(ValueError):
        hurtownia.get_document_cache("a" * 64, "KHB1", "zly'hash")
    assert hurtownia._zapytania == []


def test_hurtownia_filtruje_po_numerze(hurtownia):
    hurtownia.load_wnioskodawcy("KHB1553044")
    assert "= 'KHB1553044'" in hurtownia._zapytania[0]


def test_hurtownia_partycja_z_chwili_zapisu_i_zamkniecie_polaczenia(hurtownia):
    with pytest.raises(RuntimeError):
        hurtownia.save_document_cache(
            pdf_hash="a" * 64, nr_wniosku="KHB1", hash_schematu="b" * 64,
            id_analizy="id", document_type="umowa_deweloperska",
            ocr_text="", extracted_data={},
        )
    assert hurtownia._inserty == [datetime.now().strftime("%Y-%m-%d"), "zamknięte"]
