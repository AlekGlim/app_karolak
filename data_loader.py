"""Hurtownia (Impala/Hadoop): dane wniosku z UniFlow i cache wyników ekstrakcji.

Moduły helpers, config i impala_connector istnieją wyłącznie na serwerze,
dlatego app.py importuje ten plik dopiero w funkcji zrodla(). Lokalnie
aplikacja działa w trybie offline (HIPOTEKA_OFFLINE=1) i tego pliku nie używa.

Zapytania są budowane z f-stringów, bo hadoop_execute_df nie przyjmuje
parametrów. Każda wartość wstawiana do SQL przechodzi przez _numer_wniosku()
albo _hash(), które przepuszczają wyłącznie bezpieczne znaki — wpisanie
w pole numeru wniosku apostrofu albo średnika kończy się błędem, a nie
zapytaniem.
"""

import json
import re
from datetime import datetime

import pandas as pd
import streamlit as st

from config import database, database_result, domena, username
from config import param_bs_params_impala_host, param_bs_params_krb_host
from helpers import hadoop_execute_df
from impala_connector.impala_connector import ImpalaConnector

TABELA_CACHE = "gen_ai_extract_cache"

_HASH = re.compile(r"[0-9a-f]{64}")

# Ta sama reguła co WZORZEC_NUMERU_WNIOSKU w app.py (tam: komunikat dla
# analityka, tu: ostatnia bramka przed SQL). Zmieniając jedną, zmień obie.
_NUMER_WNIOSKU = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.\-]{0,63}")


def _numer_wniosku(nr_wniosku):
    nr = str(nr_wniosku or "").strip()
    if not _NUMER_WNIOSKU.fullmatch(nr):
        raise ValueError(f"Niepoprawny numer wniosku: {nr!r}")
    return nr


def _hash(wartosc, nazwa):
    if not _HASH.fullmatch(str(wartosc)):
        raise ValueError(f"Niepoprawny {nazwa}: {wartosc!r}")
    return wartosc


def _zapytanie(query):
    return hadoop_execute_df(
        username=username,
        domena=domena,
        database=database,
        query=query,
    )


@st.cache_data(show_spinner=False, ttl=600)
def load_wnioskodawcy(nr_wniosku):
    """Wnioskodawcy jednego wniosku.

    Filtr po numerze w SQL zamiast wczytywania całej tabeli, a ttl sprawia,
    że wniosek dodany po starcie serwera pojawi się najpóźniej po 10 minutach
    (wcześniej cache bez ttl trzymał tabelę aż do restartu).
    trim/cast odwzorowuje wcześniejsze porównanie .astype(str).str.strip().
    """
    nr = _numer_wniosku(nr_wniosku)

    return _zapytanie(f"""
    SELECT *
    FROM edhp_sbox_dzr_wml_99_client_ex.gen_ai_uniflow_wnioskodawcy
    WHERE trim(cast(nr_wniosku AS STRING)) = '{nr}'
    """)


@st.cache_data(show_spinner=False, ttl=600)
def load_kwoty_kredytu(nr_wniosku):
    nr = _numer_wniosku(nr_wniosku)

    df = _zapytanie(f"""
    SELECT kw_kredytu_wn
    FROM edhp_onl_uniflow_uno_99_data.wn_par_kredytu_wniosek
    WHERE nr_wniosku = '{nr}'
    ORDER BY modifieddate DESC
    LIMIT 1
    """)

    if df.empty:
        return None

    return df.iloc[0]["KW_KREDYTU_WN"]


def get_document_cache(pdf_hash, nr_wniosku, hash_schematu):
    """Wynik z cache dla konkretnego dokumentu, wniosku i wersji schematu.

    Klucz musi zawierać wszystkie trzy człony, bo każdy z nich zmienia wynik:
      pdf_hash       — treść dokumentu
      nr_wniosku     — dane UniFlow wchodzą do promptu, więc ten sam dokument
                       przy innym wniosku daje inną weryfikacja_uniflow
      hash_schematu  — wersja schematu, szablonu promptu i danych UniFlow
                       (patrz services.schemy.klucz_wersji)

    Zwraca None, gdy nie ma trafienia — wtedy aplikacja robi pełną analizę.
    """
    pdf_hash = _hash(pdf_hash, "hash dokumentu")
    hash_schematu = _hash(hash_schematu, "hash schematu")
    nr = _numer_wniosku(nr_wniosku)

    df = _zapytanie(f"""
    SELECT extracted_json, ocr_text
    FROM edhp_sbox_dzr_wml_99_client_ex.{TABELA_CACHE}
    WHERE pdf_hash = '{pdf_hash}'
      AND nr_wniosku = '{nr}'
      AND hash_schematu = '{hash_schematu}'
    ORDER BY godzina_pobrania DESC
    LIMIT 1
    """)

    if df.empty:
        return None

    return {
        "wynik": json.loads(df.iloc[0]["EXTRACTED_JSON"]),
        "ocr_text": df.iloc[0]["OCR_TEXT"],
    }


def impala_connect(database_name: str,
                   param_bs_params_principal=username,
                   param_bs_params_principal_with_domain=username + domena,
                   param_bs_params_impala_host=param_bs_params_impala_host,
                   param_bs_params_krb_host=param_bs_params_krb_host) -> ImpalaConnector:
    ic = ImpalaConnector()
    ic.kinit(user_name=param_bs_params_principal, user_name_with_domain=param_bs_params_principal_with_domain)
    ic.connect(host=param_bs_params_impala_host, krb_host=param_bs_params_krb_host, database=database_name)
    return ic


def insert_to_hadoop(dataframe, database_name, table_name, partition, batch_size=1000):
    """Zapis DataFrame przez connector Impali; połączenie zamykane także przy błędzie."""
    ic = impala_connect(database_name)
    try:
        ic.execute(f"invalidate metadata {database_name}.{table_name}")
        ic.insert_df(dataframe, database_name, table_name, partition, batch_size)
        ic.execute(f"invalidate metadata {database_name}.{table_name}")
    finally:
        ic.close()


def save_document_cache(
    pdf_hash,
    nr_wniosku,
    hash_schematu,
    id_analizy,
    document_type,
    ocr_text,
    extracted_data
):
    """Zapis wyniku ekstrakcji do cache.

    Kolejność kolumn w DataFrame musi odpowiadać kolejności kolumn w tabeli —
    insert_df wstawia je pozycyjnie.

    ocr_text zapisujemy z markerami [STRONA_X]: bez nich odczyt z cache
    pozbawiłby szukajkę i klik w pole numerów stron.

    Partycja liczona przy każdym zapisie. Wcześniej była liczona przy imporcie
    modułu, czyli raz na życie procesu Streamlita — po północy zapisy trafiały
    do partycji z dnia startu serwera.
    """
    teraz = datetime.now()

    df = pd.DataFrame([{
        "pdf_hash": _hash(pdf_hash, "hash dokumentu"),
        "nr_wniosku": _numer_wniosku(nr_wniosku),
        "hash_schematu": _hash(hash_schematu, "hash schematu"),
        "id_analizy": id_analizy,
        "document_type": document_type,
        "ocr_text": ocr_text,
        "extracted_json": json.dumps(extracted_data, ensure_ascii=False),
        "godzina_pobrania": teraz.strftime("%Y-%m-%d %H:%M:%S"),
    }])

    insert_to_hadoop(
        dataframe=df,
        database_name=database_result,
        table_name=TABELA_CACHE,
        partition=teraz.strftime("%Y-%m-%d"),
        batch_size=1000,
    )
