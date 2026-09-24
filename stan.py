"""Stan sesji Streamlita — wszystkie dane analizy trzymane pod jednym kluczem.

Analiza jest przypisana do pary (hash dokumentu, numer wniosku). Wcześniej
wynik był zapisany pod samą nazwą pliku, a tekst OCR pod jednym kluczem
na całą sesję, przez co:
  - po zmianie numeru wniosku na ekranie zostawała weryfikacja UniFlow
    policzona dla poprzedniego wniosku,
  - inny plik o tej samej nazwie pokazywał stary wynik,
  - po wgraniu drugiego pliku szukajka działała na tekście pierwszego.
"""

import streamlit as st

from services.schemy import policz_hash_pdf

_ANALIZY = "analizy"
_UNIFLOW = "uniflow"


def _klucz(pdf_hash, nr_wniosku):
    return f"{pdf_hash}:{nr_wniosku}"


# --- analizy ---

def zapisz_analize(analiza):
    st.session_state.setdefault(_ANALIZY, {})[
        _klucz(analiza.pdf_hash, analiza.nr_wniosku)
    ] = analiza


def biezaca_analiza(pdf_hash, nr_wniosku):
    """Analiza bieżącego dokumentu dla bieżącego wniosku albo None."""
    if not pdf_hash or not nr_wniosku:
        return None
    return st.session_state.get(_ANALIZY, {}).get(_klucz(pdf_hash, nr_wniosku))


def usun_analize(pdf_hash, nr_wniosku):
    st.session_state.get(_ANALIZY, {}).pop(_klucz(pdf_hash, nr_wniosku), None)


# --- dane wniosku z UniFlow ---

def ustaw_uniflow(dane):
    st.session_state[_UNIFLOW] = dane


def dane_uniflow(nr_wniosku):
    """Dane UniFlow, ale tylko jeśli dotyczą podanego wniosku.

    Sprawdzenie numeru chroni przed wysłaniem do modelu danych klientów
    z poprzednio wpisanego wniosku.
    """
    dane = st.session_state.get(_UNIFLOW)
    if dane and dane.get("numer_wniosku") == nr_wniosku:
        return dane
    return None


# --- wgrany dokument (osobno dla każdej zakładki) ---

def zapamietaj_plik(typ_dokumentu, nazwa, bajty):
    st.session_state[f"{typ_dokumentu}_plik"] = {
        "nazwa": nazwa,
        "bajty": bajty,
        "hash": policz_hash_pdf(bajty),
    }


def plik(typ_dokumentu):
    return st.session_state.get(f"{typ_dokumentu}_plik")
