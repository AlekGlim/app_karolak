# data_loader.py
import json
import pandas as pd
import streamlit as st
import hashlib
from datetime import datetime
from helpers import hadoop_execute_df
from config import username, domena, database, database_result
from impala_connector.impala_connector import ImpalaConnector, impala_execute, impala_fetchall
from config import bs_params_hdb_namestamp
from config import param_bs_params_impala_host
from config import param_bs_params_krb_host

@st.cache_data(show_spinner=False)
def load_wnioskodawcy():
    query = """
    SELECT *
    FROM edhp_sbox_dzr_wml_99_client_ex.gen_ai_uniflow_wnioskodawcy
    """

    df = hadoop_execute_df(
        username=username,
        domena=domena,
        database=database,
        query=query
    )

    return df

@st.cache_data(show_spinner=False)
def load_kwoty_kredytu(nr_wniosku):

    query = f"""
    SELECT kw_kredytu_wn
    FROM edhp_onl_uniflow_uno_99_data.wn_par_kredytu_wniosek
    WHERE nr_wniosku = '{nr_wniosku}'
    ORDER BY modifieddate DESC
    LIMIT 1
    """

    df = hadoop_execute_df(
        username=username,
        domena=domena,
        database=database,
        query=query
    )

    if df.empty:
        return None

    return df.iloc[0]["KW_KREDYTU_WN"]


def get_document_cache(pdf_hash, nr_wniosku, hash_schematu):
    """Wynik z cache dla konkretnego dokumentu, wniosku i wersji schematu.

    Klucz musi zawierać wszystkie trzy człony, bo każdy z nich zmienia wynik:
      pdf_hash       — treść dokumentu
      nr_wniosku     — dane UniFlow wchodzą do promptu, więc ten sam dokument
                       przy innym wniosku daje inną weryfikacja_uniflow
                       (wcześniej kluczem był sam pdf_hash i analityk widział
                       weryfikację policzoną dla cudzego wniosku)
      hash_schematu  — po zmianie schematu stary wynik nie odpowiada już temu,
                       o co prosimy model (brakuje nowych pól, są nieaktualne)

    Zwraca None, gdy nie ma trafienia — wtedy aplikacja robi pełną analizę.
    """

    query = f"""
    SELECT extracted_json, ocr_text
    FROM edhp_sbox_dzr_wml_99_client_ex.gen_ai_extract_cache
    WHERE pdf_hash = '{pdf_hash}'
      AND nr_wniosku = '{nr_wniosku}'
      AND hash_schematu = '{hash_schematu}'
    ORDER BY godzina_pobrania DESC
    LIMIT 1
    """

    df = hadoop_execute_df(
        username=username,
        domena=domena,
        database=database,
        query=query
    )

    if df.empty:
        return None

    return {
        "wynik": json.loads(
            df.iloc[0]["EXTRACTED_JSON"]
        ),
        "ocr_text": df.iloc[0]["OCR_TEXT"]
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



# funkcja zapisuje dane do Hadoopa przy pomocy connectora Impali
def insert_to_hadoop(dataframe, database_name, table_name, partition, batch_size=1000):
    ic = impala_connect(database_name)
    ic.execute(f"invalidate metadata {database_name}.{table_name}")
    ic.insert_df(dataframe, database_name, table_name, partition, batch_size)
    ic.execute(f"invalidate metadata {database_name}.{table_name}")
    ic.close()

partition = datetime.now().strftime("%Y-%m-%d")
    
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
    """

    df = pd.DataFrame([{
        "pdf_hash": pdf_hash,
        "nr_wniosku": nr_wniosku,
        "hash_schematu": hash_schematu,
        "id_analizy": id_analizy,
        "document_type": document_type,
        "ocr_text": ocr_text,
        "extracted_json": json.dumps(
            extracted_data,
            ensure_ascii=False
        ),
        "godzina_pobrania": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }])

    insert_to_hadoop(
        dataframe=df,
        database_name=database_result,
        table_name="gen_ai_extract_cache",
        partition=partition,
        batch_size=1000
    )
