"""
Hipoteka AI - Proof of Concept (Sprint 1)
Aplikacja Streamlit dla analityków hipotecznych.

Działa niezależnie od notatnika `analiza_prawna_umowa_dew.ipynb` (ten służy do
ad hoc testowania promptów i endpointów). Obydwa wywołują te same endpointy,
ale każde ma własną, osobną implementację.

Przepływ:
1. Upload PDF + podgląd dokumentu (lewa kolumna).
2. OCR dokumentu.
3. Jedno wywołanie endpointu Extract ze schematem zwracającym kluczowe pola,
   podsumowanie i listę ryzyk (prawa kolumna + sekcje na dole).

Token pobierany jest z pliku `token.txt` (klucz "access_token") leżącego obok
tego skryptu. BASE_URL i CA_CERT są stałe. Trybu demo nie ma — aplikacja
działa wyłącznie na prawdziwym API.

Numery stron nie pochodzą od modelu: wartość pola jest szukana w tekście OCR,
a strona wynika z najbliższego markera [STRONA_X]. Rozbieżności w dokumencie
(to samo pole wskazane niejednolicie) zgłasza model w liście `rozbieznosci`,
a Python weryfikuje, czy każda zgłoszona wartość naprawdę stoi w tekście.

MOTYW: aplikacja podąża za motywem przeglądarki (jasny/ciemny). Aby to działało,
NIE ustawiaj base="light" w .streamlit/config.toml - jeśli taki plik istnieje,
usuń go albo usuń z niego sekcję [theme].
"""

import json
import time
import tempfile
from pathlib import Path
from datetime import datetime
import html
import base64
import streamlit as st
import pandas as pd
import requests
import hashlib
import uuid

from data_loader import (
    load_wnioskodawcy,
    load_kwoty_kredytu,
    get_document_cache,
    save_document_cache
    )
from core.rozbieznosci import zweryfikuj_warianty
from core.szukanie import szukaj_w_ocr_z_wariantami, warianty_do_szukania
from core.tekst import dodaj_markery_stron
from core.ustalenia import problemy_wg_pola, stan_sekcji, zbierz_problemy
from core.walidacje import czy_wartosc_transakcji_zgodna, waliduj_nrb, waliduj_pesel


# Przycisk kopiowania wartości do UniFlow. Gdy pakietu nie ma w środowisku,
# aplikacja działa dalej — tylko bez przycisków (wymaga: pip install st-copy).
try:
    from st_copy import copy_button
    MA_KOPIOWANIE = True
except ImportError:
    copy_button = None
    MA_KOPIOWANIE = False


with open("logo_mbank.jpg", "rb") as f:
    logo_base64 = base64.b64encode(f.read()).decode()

# =====================================================================
# KONFIGURACJA STRONY
# =====================================================================

st.set_page_config(
    page_title="Hipoteka AI - Analiza Umowy Deweloperskiej",
    page_icon="🏦",
    layout="wide",
)

if "wybrana_strona_pdf" not in st.session_state:
    st.session_state["wybrana_strona_pdf"] = 1

# =====================================================================
# STYLE - kolory jako zmienne CSS, z osobnym wariantem dla motywu ciemnego
# =====================================================================

CUSTOM_CSS = """
<style>
    /* ---------- Motyw jasny (domyślny) ---------- */
    :root {
        --akcent: #E4032E;
        --akcent-ciemny: #B00224;
        --tlo-strony: #F5F6F8;
        --tlo-karty: #FFFFFF;
        --obramowanie: #EAEAEE;
        --tekst: #1F2937;
        --tekst-przygaszony: #6B7280;
        --cien: 0 1px 3px rgba(0, 0, 0, 0.05);

        --ryzyko-wysokie: #C0392B;
        --ryzyko-wysokie-tlo: #FDECEA;
        --ryzyko-srednie: #B25E00;
        --ryzyko-srednie-tlo: #FFF4E5;
        --ryzyko-niskie: #1E7C34;
        --ryzyko-niskie-tlo: #E6F4EA;

    }

    /* ---------- Motyw ciemny ---------- */
    @media (prefers-color-scheme: dark) {
        :root {
            --akcent: #FF4D6A;
            --akcent-ciemny: #E4032E;
            --tlo-strony: #0E1117;
            --tlo-karty: #1A1D24;
            --obramowanie: #2E323C;
            --tekst: #E8EAED;
            --tekst-przygaszony: #9BA1AC;
            --cien: 0 1px 3px rgba(0, 0, 0, 0.35);

            --ryzyko-wysokie: #FF7A85;
            --ryzyko-wysokie-tlo: #3A1D22;
            --ryzyko-srednie: #E0A458;
            --ryzyko-srednie-tlo: #3A2E1C;
            --ryzyko-niskie: #6BCB8B;
            --ryzyko-niskie-tlo: #1B3325;

        }
    }

    /* ---------- Tła kontenerów Streamlita ---------- */
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .stApp {
        background-color: var(--tlo-strony);
    }
    [data-testid="stHeader"] {
        background: transparent;
    }

    /* ---------- Baner nagłówkowy ---------- */
    .banner-naglowek {
        background: linear-gradient(135deg, var(--akcent) 0%, var(--akcent-ciemny) 100%);
        color: #FFFFFF;
        padding: 28px 32px;
        border-radius: 14px;
        margin-bottom: 24px;
    }
    .banner-naglowek h1 {
        margin: 0;
        font-size: 1.7rem;
        font-weight: 700;
        color: #FFFFFF;
    }
    .banner-naglowek p {
        margin: 4px 0 0 0;
        opacity: 0.92;
        font-size: 0.95rem;
        color: #FFFFFF;
    }

    /* ---------- Nagłówki sekcji ---------- */
    .naglowek-sekcji {
        color: var(--tekst);
        font-weight: 700;
        font-size: 1.05rem;
        margin: 4px 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid var(--akcent);
    }

    /* ---------- Kafelki danych klienta ---------- */
    .kafelek {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-left: 4px solid var(--akcent);
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: var(--cien);
        height: 100%;
    }
    .kafelek-etykieta {
        color: var(--tekst-przygaszony);
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 4px;
    }
    .kafelek-wartosc {
        color: var(--tekst);
        font-size: 1.12rem;
        font-weight: 700;
    }

    /* ---------- Karty z wynikami ekstrakcji ---------- */
    .karta {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-left: 4px solid var(--akcent);
        border-radius: 10px;
        box-shadow: var(--cien);
        padding: 16px 20px 10px 20px;
        margin-bottom: 14px;
    }
    .karta-tytul {
        color: var(--tekst);
        font-weight: 700;
        font-size: 0.95rem;
        margin-bottom: 12px;
    }
    .wiersz {
        display: grid;
        grid-template-columns: 45% 1fr auto;
        gap: 0 14px;
        align-items: baseline;
        padding: 7px 0;
        font-size: 0.9rem;
        border-bottom: 1px solid var(--obramowanie);
    }
    .wiersz:last-child {
        border-bottom: none;
    }
    .wiersz-etykieta {
        color: var(--tekst-przygaszony);
        font-size: 0.84rem;
    }
    .wiersz-wartosc {
        color: var(--tekst);
        font-weight: 600;
        word-break: break-word;
    }
    .wiersz-wartosc.pusto {
        color: var(--tekst-przygaszony);
        font-weight: 400;
        font-style: italic;
    }

    /* ---------- Podsumowanie ---------- */
    .podsumowanie {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-left: 4px solid var(--akcent);
        border-radius: 10px;
        box-shadow: var(--cien);
        padding: 20px 24px;
        font-size: 0.97rem;
        line-height: 1.7;
        color: var(--tekst);
    }

    /* ---------- Ryzyka ---------- */
    .karta-ryzyko {
        background-color: var(--tlo-karty);
        border: 1px solid var(--obramowanie);
        border-radius: 10px;
        box-shadow: var(--cien);
        padding: 13px 18px;
        margin-bottom: 10px;
        color: var(--tekst);
        font-size: 0.93rem;
        line-height: 1.6;
    }
    .karta-ryzyko-wysoka { border-left: 4px solid var(--ryzyko-wysokie); }
    .karta-ryzyko-srednia { border-left: 4px solid var(--ryzyko-srednie); }
    .karta-ryzyko-niska { border-left: 4px solid var(--ryzyko-niskie); }

    .badge-waga-wysoka {
        background-color: var(--ryzyko-wysokie-tlo);
        color: var(--ryzyko-wysokie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.78em;
        font-weight: 700;
    }
    .badge-waga-srednia {
        background-color: var(--ryzyko-srednie-tlo);
        color: var(--ryzyko-srednie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.78em;
        font-weight: 700;
    }
    .badge-waga-niska {
        background-color: var(--ryzyko-niskie-tlo);
        color: var(--ryzyko-niskie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.78em;
        font-weight: 700;
    }

    /* ---------- Plakietki trybu ---------- */
    .badge-tryb-api {
        background-color: var(--ryzyko-niskie-tlo);
        color: var(--ryzyko-niskie);
        padding: 2px 10px;
        border-radius: 10px;
        font-size: 0.8em;
        font-weight: 600;
    }

    .info-pliku {
        color: var(--tekst-przygaszony);
        font-size: 0.85rem;
        margin-bottom: 8px;
    }
    .tekst-pomocniczy {
        color: var(--tekst-przygaszony);
        font-size: 0.92rem;
        margin-bottom: 14px;
    }
    

    /* ---------- Kontrolki Streamlita ---------- */
    div.stButton > button:first-child {
    background-color: var(--tlo-karty);
    color: var(--tekst);
    border: 1px solid var(--obramowanie);
    font-weight: 600;
    border-radius: 8px;
    padding: 0.5rem 1.2rem;
    }

    div.stButton > button:first-child:hover {
        border-color: var(--akcent);
        color: var(--akcent);
        background-color: var(--tlo-karty);
    }
    
    div.stButton > button:first-child:focus-visible {
        outline: 2px solid var(--akcent);
        outline-offset: 2px;
    }
    [data-testid="stFileUploader"] {
        border: 1.5px dashed var(--obramowanie);
        border-radius: 10px;
        padding: 6px;
        background-color: var(--tlo-karty);
    }

    @media (prefers-reduced-motion: reduce) {
        * { transition: none !important; animation: none !important; }
    }
    /* ---------- Dodatkowe---------- */
    .haslo-ryzyka {
    color: var(--akcent);
    font-weight: 800;
    font-size: 1.02rem;
    }
    
    /* Logo mBanku w lewym dolnym rogu sidebara */

   section[data-testid="stSidebar"]::after {
        content: "";

        position: absolute;
        left: 49%;
        bottom: 20px;

        transform: translateX(-50%);

        width: 180px;
        height: 70px;

        background-image: url("data:image/jpeg;base64,LOGO_PLACEHOLDER");
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;

        pointer-events: none;
    }
    
    [data-testid="stExpander"] details {
    border: 1px solid var(--obramowanie) !important;
    border-left: 4px solid var(--akcent) !important;
    border-radius: 10px !important;
    overflow: hidden;
    }

    [data-testid="stExpander"] summary {
        font-weight: 800 !important;
        letter-spacing: 0.05em;
    }

    [data-testid="stExpander"] {
        margin-bottom: 10px;
    }
    [data-testid="stExpander"] summary {
    background: var(--tlo-karty) !important;
    padding: 12px 16px !important;
    }

    [data-testid="stExpander"] summary:hover {
        background: var(--tlo-strony) !important;
    }
    [data-testid="stExpander"] details > div {
        padding: 12px !important;
    }


    /* --- panel ustaleń --- */
    .ustalenie {
        display: flex;
        gap: 12px;
        align-items: flex-start;
        background: var(--tlo-karty, #FFF);
        border: 1px solid var(--obramowanie, #E5E7EB);
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 7px;
    }
    .ustalenie-wysokie { border-left: 4px solid #C0392B; }
    .ustalenie-srednie { border-left: 4px solid #B25E00; }
    .ustalenie-ikona { font-size: 1.05rem; line-height: 1.4; }
    .ustalenie-tresc { flex: 1; }
    .ustalenie-tytul {
        font-size: 0.92rem;
        font-weight: 800;
        color: var(--tekst, #1F2937);
        margin-bottom: 2px;
    }
    .ustalenie-opis {
        font-size: 0.86rem;
        color: var(--tekst, #1F2937);
        line-height: 1.5;
    }
    .ustalenie-krok {
        font-size: 0.83rem;
        color: var(--tekst-przygaszony, #6B7280);
        margin-top: 4px;
    }
    .bez-ustalen {
        background: #E6F4EA;
        color: #1E7C34;
        border-radius: 8px;
        padding: 11px 16px;
        font-size: 0.88rem;
        font-weight: 700;
        margin-bottom: 14px;
    }

    /* --- szukajka: nawigacja i bieżące trafienie --- */
    .legenda-trafien {
        display: flex;
        flex-wrap: wrap;
        gap: 14px;
        margin: 6px 0 8px;
        font-size: 0.76rem;
        color: var(--tekst-przygaszony, #6B7280);
    }
    .legenda-wpis { display: flex; align-items: center; gap: 5px; }
    .legenda-kropka {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 4px;
    }
    .licznik-trafien {
        text-align: center;
        font-size: 0.84rem;
        font-weight: 700;
        color: var(--tekst, #1F2937);
        padding-top: 6px;
    }
    .biezace-trafienie {
        background: var(--tlo-karty, #FFF);
        border: 1px solid var(--obramowanie, #E5E7EB);
        border-left: 4px solid #2C3E50;
        border-radius: 8px;
        padding: 12px 15px;
        margin-bottom: 8px;
        font-size: 0.86rem;
        line-height: 1.6;
        color: var(--tekst, #1F2937);
    }
    .biezace-slowo {
        font-size: 1.05rem;
        font-weight: 800;
        margin: 2px 0 7px;
        word-break: break-word;
    }
    .fragment-ocr.biezacy {
        box-shadow: 0 0 0 2px var(--akcent, #E4032E) inset;
    }

    /* --- fragmenty z szukajki --- */
    .fragment-ocr {
        background: var(--tlo-karty, #FFF);
        border: 1px solid var(--obramowanie, #E5E7EB);
        border-left: 3px solid var(--akcent, #E4032E);
        border-radius: 8px;
        padding: 11px 15px;
        margin-bottom: 6px;
        font-size: 0.86rem;
        line-height: 1.6;
        color: var(--tekst, #1F2937);
    }
    .fragment-meta {
        color: var(--tekst-przygaszony, #6B7280);
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 5px;
    }
    .fragment-ocr mark {
        background: #FEF08A;
        color: #1F2937;
        padding: 1px 3px;
        border-radius: 3px;
        font-weight: 600;
    }

    /* --- nagłówek pola z dymkiem --- */
    .pole-naglowek {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 2px;
    }
    .pole-etykieta {
        color: var(--tekst-przygaszony, #6B7280);
        font-size: 0.8rem;
    }
    .znacznik {
        font-size: 0.75rem;
        font-weight: 800;
        padding: 2px 8px;
        border-radius: 20px;
        cursor: help;
    }
    .znacznik-rozbieznosc { background: #FFF4E5; color: #B25E00; }

    /* komponent st-copy renderuje się jako iframe — domyślnie rezerwuje
       za dużo pionu i rozpycha komórki siatki */
    iframe[title="st_copy.copy_button"] {
        height: 30px !important;
        width: auto !important;
        margin-top: 2px;
    }
    div[data-testid="stIFrame"]:has(iframe[title="st_copy.copy_button"]) {
        display: flex;
        justify-content: flex-end;
        width: 100%;
    }
</style>
"""
st.markdown(
    CUSTOM_CSS.replace(
        "LOGO_PLACEHOLDER",
        logo_base64
    ),
    unsafe_allow_html=True
)


# =====================================================================
# STAŁA KONFIGURACJA API
# =====================================================================

BASE_URL = "https://hdspprd1.ux.mbank.pl/sde_service/api"
CA_CERT = "/home/jovyan/security/ca.pem"
PLIK_TOKENU = Path(__file__).parent / "token.txt"
WYSOKOSC_PODGLADU = 900

SCHEMY_DIR = Path(__file__).parent / "schemy"


def wczytaj_schema(nazwa_pliku):
    with open(
        SCHEMY_DIR / f"{nazwa_pliku}.json",
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def przejdz_do_strony(numer_strony):

    if not numer_strony:
        return

    st.session_state["wybrana_strona_pdf"] = int(
        numer_strony
    )
    
    
def rozpoznaj_typ_dokumentu(nazwa_pliku):
    nazwa = nazwa_pliku.lower()

    if "przedwst" in nazwa:
        return "umowa_przedwstepna"

    if "deweloperska" in nazwa:
        return "umowa_deweloperska"

    return "nieznany"

def rozpoznaj_typ_dokumentu(nazwa_pliku):

    nazwa = nazwa_pliku.lower()

    if "dewelopers" in nazwa:
        return "umowa_deweloperska"

    elif "przedwst" in nazwa:
        return "umowa_przedwstepna"

    elif "rezerw" in nazwa:
        return "umowa_rezerwacyjna"

    elif "prospekt" in nazwa:
        return "prospekt"

    elif "zbywc" in nazwa:
        return "oswiadczenie_zbywcy"

    return "umowa_deweloperska"

def pobierz_schema(typ_dokumentu):

    mapa = {
        "umowa_deweloperska": "umowa_deweloperska",
        "umowa_przedwstepna": "umowa_przedwstepna",
        "umowa_rezerwacyjna": "umowa_rezerwacyjna",
        "prospekt": "prospekt",
        "oswiadczenie_zbywcy": "oswiadczenie_zbywcy"
    }

    if typ_dokumentu not in mapa:
        raise ValueError(
            f"Nieznany typ dokumentu: {typ_dokumentu}"
        )

    return wczytaj_schema(
        mapa[typ_dokumentu]
    )


def policz_hash_pdf(plik_bajty):
    return hashlib.sha256(plik_bajty).hexdigest()


def policz_hash_schematu(schema):
    """Skrót schematu ekstrakcji — część klucza cache.

    sort_keys porządkuje klucze, więc samo przestawienie pól w pliku nie
    unieważnia cache; zmiana pola albo jego opisu (czyli tego, o co prosimy
    model) już tak.
    """
    tekst = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True
    )

    return hashlib.sha256(
        tekst.encode("utf-8")
    ).hexdigest()


def wczytaj_token():
    """Wczytuje access_token z pliku token.txt."""
    try:
        with open("/home/jovyan/projects/analiza_prawna_hipoteka/token.txt", "r", encoding="utf-8") as f:
            dane = json.load(f)
        return dane.get("access_token")
    except (FileNotFoundError, json.JSONDecodeError):
        return None

# =====================================================================
# Wczytanie tokenu z pliku json
# =====================================================================

# def wczytaj_token():
#     """Wczytuje access_token z token.json leżącego obok tego skryptu."""
#     try:
#         with open(PLIK_TOKENU, "r", encoding="utf-8") as f:
#             dane = json.load(f)
#         return dane.get("access_token")
#     except (FileNotFoundError, json.JSONDecodeError):
#         return None


# =====================================================================
# DANE Z HURTOWNI (mock - do podmiany na realne źródło)
# =====================================================================

def pobierz_dane_wniosku():
    """TODO: podłączyć pod hurtownię danych. Na razie dane przykładowe."""
    return {
        "numer_wniosku": "WN/2026/00184521",
        "imie": "Katarzyna",
        "nazwisko": "Nowak",
        "pesel": "89052112345",
        "liczba_wnioskodawcow": 2,
    }


# =====================================================================
# TRYB PRAWDZIWEGO API
# =====================================================================


def wywolaj_ocr_api(plik_bajty, token, document_group_id):
    """POST /legal_analysis/ocr + polling statusu + pobranie wyniku."""
    auth_headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(
        f"{BASE_URL}/legal_analysis/ocr",
        headers={**auth_headers, "Content-Type": "application/octet-stream"},
        params={"document_group_id": document_group_id, "document_type": "umowa", "ocr_model" : "prebuilt-layout"},
        data=plik_bajty,
        verify=CA_CERT,
        timeout=60,
    )
    response.raise_for_status()
    run_id = response.json()["run_id"]

    for _ in range(30):
        resp = requests.get(
            f"{BASE_URL}/legal_analysis/ocr/{run_id}/status",
            headers=auth_headers,
            verify=CA_CERT,
            timeout=30,
        )
        status = resp.json().get("job_status")
        if status == "DONE":
            break
        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"OCR zakończony błędem (status={status})")
        time.sleep(3)
    else:
        raise TimeoutError("Przekroczono limit oczekiwania na OCR (90 s).")

    response = requests.get(
        f"{BASE_URL}/legal_analysis/ocr/{run_id}",
        headers=auth_headers,
        verify=CA_CERT,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def wywolaj_extract_api(ocr_text, token, document_id, schema, dane_uniflow):
    """POST /legal_analysis/extract + polling statusu + pobranie wyniku."""
    auth_headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(
        f"{BASE_URL}/legal_analysis/extract",
        headers=auth_headers,
        json={
            "ocr_text": ocr_text,
            "schema": schema,
            "metadata": {"document_id": document_id},
        },
        verify=CA_CERT,
        timeout=60,
    )
    response.raise_for_status()
    run_id = response.json()["run_id"]

    for _ in range(30):
        resp = requests.get(
            f"{BASE_URL}/legal_analysis/extract/{run_id}/status",
            headers=auth_headers,
            verify=CA_CERT,
            timeout=30,
        )
        status = resp.json().get("job_status")
        if status == "DONE":
            break
        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"Ekstrakcja zakończona błędem (status={status})")
        time.sleep(3)
    else:
        raise TimeoutError("Przekroczono limit oczekiwania na ekstrakcję (90 s).")

    response = requests.get(
        f"{BASE_URL}/legal_analysis/extract/{run_id}",
        headers=auth_headers,
        verify=CA_CERT,
        timeout=30,
    )
    response.raise_for_status()

    return response.json()["extracted"]


# =====================================================================
# PODGLĄD PDF
# =====================================================================

def zapisz_pdf_tymczasowo(plik_bajty, nazwa_pliku):
    """Zapisuje PDF do pliku tymczasowego (raz na dokument) i zwraca ścieżkę."""
    klucz = f"tmp_pdf_{nazwa_pliku}_{len(plik_bajty)}"
    if klucz in st.session_state and Path(st.session_state[klucz]).exists():
        return Path(st.session_state[klucz])

    katalog = Path(tempfile.gettempdir()) / "hipoteka_ai_podglad"
    katalog.mkdir(exist_ok=True)
    sciezka = katalog / nazwa_pliku
    sciezka.write_bytes(plik_bajty)

    st.session_state[klucz] = str(sciezka)
    return sciezka


def podglad_przez_obrazki(plik_bajty, wysokosc):
    """Renderuje strony PDF jako obrazki. Działa w każdej przeglądarce.

    Wymaga: pip install pypdfium2
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return False

    import io

    dokument = pdfium.PdfDocument(plik_bajty)
    liczba_stron = len(dokument)

    numer = st.session_state.get(
        "wybrana_strona_pdf",
        1
    )


    col1, col2, col3 = st.columns([1, 14, 1])

    with col1:
        if st.button(
            "←",
            disabled=(numer <= 1),
            key="pdf_prev"
        ):
            st.session_state["wybrana_strona_pdf"] = numer - 1
            st.rerun()

    with col2:
        st.markdown(
            f"<div style='text-align:center;'>Strona {numer} z {liczba_stron}</div>",
            unsafe_allow_html=True
        )

    with col3:
        if st.button(
            "→",
            disabled=(numer >= liczba_stron),
            key="pdf_next"
        ):
            st.session_state["wybrana_strona_pdf"] = numer + 1
            st.rerun()

    numer = max(
        1,
        min(numer, liczba_stron)
    )
    st.session_state["wybrana_strona_pdf"] = numer

    strona = dokument[numer - 1]

    obrazek = strona.render(scale=2).to_pil()
    bufor = io.BytesIO()
    obrazek.save(bufor, format="PNG")

    with st.container(height=wysokosc, border=True):
        st.image(bufor.getvalue(), use_container_width=True)

    dokument.close()
    return True


def pokaz_podglad_pdf(
    plik_bajty,
    nazwa_pliku,
    wysokosc=WYSOKOSC_PODGLADU
):

    if podglad_przez_obrazki(
        plik_bajty,
        wysokosc
    ):
        return

    st.warning(
        "Brak renderera PDF"
    )

# =====================================================================
# PANEL BOCZNY
# =====================================================================

def panel_konfiguracji():
    """Panel boczny: wyłącznie token do API.

    Tryb demo został usunięty — dublował logikę analizy i rozjeżdżał się ze
    schematem (zwracał pola, których już nie ma, i nie zwracał nowych).
    Aplikacja działa wyłącznie na prawdziwym API.
    """
    st.sidebar.markdown("## ⚙️ Konfiguracja")

    token = wczytaj_token()

    if token:
        st.sidebar.success("Token wczytany z token.txt")

    else:
        st.sidebar.error(
            f"Brak poprawnego tokenu w {PLIK_TOKENU.name}. "
            'Dodaj plik z kluczem "access_token" obok skryptu.'
        )

    return token


# =====================================================================
# NAGŁÓWEK I DANE WNIOSKU
# =====================================================================

def banner_naglowek():
    st.markdown(
        """
        <div class="banner-naglowek">
            <h1>🏦 Hipoteka AI — Analiza Umowy Deweloperskiej</h1>
            <p>Proof of Concept · Sprint 1 · OCR + ekstrakcja i analiza przez LLM</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kafelek(etykieta, wartosc):
    st.markdown(
        f"""
        <div class="kafelek">
            <div class="kafelek-etykieta">{etykieta}</div>
            <div class="kafelek-wartosc">{wartosc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# def sekcja_dane_wniosku(dane):
#     st.markdown('<p class="naglowek-sekcji">📋 Dane Klienta / Dane Wniosku</p>', unsafe_allow_html=True)
#     col1, col2, col3, col4, col5 = st.columns(5)
#     with col1:
#         kafelek("Numer wniosku", dane["numer_wniosku"])
#     with col2:
#         kafelek("Imię", dane["imie"])
#     with col3:
#         kafelek("Nazwisko", dane["nazwisko"])
#     with col4:
#         kafelek("PESEL", dane["pesel"])
#     with col5:
#         kafelek("Stan cywilny", dane["stan_cywilny"])
#     with col6:
#         kafelek("Liczba wnioskodawców", dane["liczba_wnioskodawcow"])


# =====================================================================
# UPLOAD I PODGLĄD
# =====================================================================

def sekcja_numer_wniosku():
    st.markdown(
        '<p class="naglowek-sekcji">🔎 Numer wniosku</p>',
        unsafe_allow_html=True
    )

    st.caption(
        "Wprowadź numer wniosku z UniFlow, aby pobrać dane klienta."
    )

    return st.text_input(
        "Numer wniosku",
        placeholder="np. KHB1553044",
        label_visibility="collapsed"
    )

def sekcja_dane_uniflow(nr_wniosku):

    if not nr_wniosku:
        return

    df_wnioski = load_wnioskodawcy()
    kwota_kredytu = load_kwoty_kredytu(
        nr_wniosku
    )
    st.session_state["kwota_kredytu_wn"] = kwota_kredytu

    rekord = df_wnioski[
        df_wnioski["NR_WNIOSKU"].astype(str).str.strip()
        == nr_wniosku.strip()
    ]

    if rekord.empty:
        st.warning(f"Nie znaleziono wniosku {nr_wniosku}")
        return
    
    st.session_state["uniflow"] = {
        "numer_wniosku": nr_wniosku,
        "wnioskodawcy": rekord[
            ["IMIE", "NAZWISKO", "PESEL", "STAN_CYWILNY"]
        ].to_dict("records")
    }
    

    st.markdown(
        '<p class="naglowek-sekcji">📋 Dane Klienta</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        kafelek("Numer wniosku", nr_wniosku)

    with col2:
        kafelek("Liczba wnioskodawców", len(rekord))
        
    st.markdown(
    "<div style='height:10px;'></div>",
    unsafe_allow_html=True
    )
    
    osoby = list(rekord.iterrows())

    for i in range(0, len(osoby), 2):

        col1, col2 = st.columns(2)

        with col1:
            _, osoba = osoby[i]

            karta(
                f"👤 Wnioskodawca {i+1}",
                [
                    wiersz("Imię", osoba["IMIE"]),
                    wiersz("Nazwisko", osoba["NAZWISKO"]),
                    wiersz("PESEL", osoba["PESEL"]),
                    wiersz("Stan cywilny", osoba["STAN_CYWILNY"]),

                ]
            )

        if i + 1 < len(osoby):
            with col2:
                _, osoba = osoby[i + 1]

                karta(
                    f"👤 Wnioskodawca {i+2}",
                    [
                        wiersz("Imię", osoba["IMIE"]),
                        wiersz("Nazwisko", osoba["NAZWISKO"]),
                        wiersz("PESEL", osoba["PESEL"]),
                        wiersz("Stan cywilny", osoba["STAN_CYWILNY"]),

                    ]
                )

#     for i, (_, osoba) in enumerate(
#         rekord.iterrows(),
#         start=1
#     ):

#         karta(
#             f"👤 Wnioskodawca {i}",
#             [
#                 wiersz("Imię", osoba["IMIE"]),
#                 wiersz("Nazwisko", osoba["NAZWISKO"]),
#                 wiersz("PESEL", osoba["PESEL"]),
#             ]
#         )

        # st.dataframe(
        #     rekord[["IMIE", "NAZWISKO", "PESEL"]],
        #     use_container_width=True,
        #     hide_index=True,
        # )


def sekcja_upload_widget():
    st.markdown('<p class="naglowek-sekcji">📤 Upload Dokumentu</p>', unsafe_allow_html=True)
    st.caption("Wspierany dokument w Sprincie 1: umowa deweloperska (PDF).")
    return st.file_uploader("Wybierz plik PDF", type=["pdf"],  label_visibility="collapsed")


def sekcja_podglad_dokumentu(plik_bajty, nazwa_pliku):
    st.markdown('<p class="naglowek-sekcji">📄 Podgląd Dokumentu</p>', unsafe_allow_html=True)
    rozmiar_kb = len(plik_bajty) / 1024
    st.markdown(
        f'<div class="info-pliku">Plik: <b>{nazwa_pliku}</b> · {rozmiar_kb:.0f} KB</div>',
        unsafe_allow_html=True,
    )
    pokaz_podglad_pdf(plik_bajty, nazwa_pliku)
    st.download_button(
        "⬇ Pobierz plik",
        data=plik_bajty,
        file_name=nazwa_pliku,
        mime="application/pdf",
    )


# =====================================================================
# WYNIKI EKSTRAKCJI
# =====================================================================

# Pola, które analityk przepisuje do UniFlow — tylko one dostają przycisk
# kopiowania. Przy pozostałych polach przycisk byłby szumem.
POLA_DO_PRZEPISANIA = {
    "numer_umowy",
    "data_umowy",
    "nazwa_dewelopera",
    "numer_kw",
    "numer_dzialki",
    "numer_budynku",
    "numer_lokalu",
    "cena_nieruchomosci",
    "laczna_wartosc_transakcji",
    "termin_przeniesienia_wlasnosci",
    "numer_rachunku_powierniczego",
    "otwarty_numer_rachunku_powierniczego",
    "bank_powiernika",
}


def _znacznik_pola(problem):
    """Znacznik stanu w nagłówku pola: rozbieżność lub pusty string.

    Pusty string zamiast braku elementu, żeby .pole-naglowek (min-height)
    wyrównał wysokość pól bez znacznika do tych z nim.
    """
    if not problem:
        return ""

    dymek = f'{problem.get("opis", "")} → {problem.get("krok", "")}'

    return (
        f'<span class="znacznik znacznik-rozbieznosc" '        f'title="{dymek}">⚠ rozbieżność</span>'
    )


def pole_pdf(
    etykieta,
    wartosc,
    key,
    problem=None,
    potwierdzone=None
):
    """Pole z wartością: on_click wkleja do szukajki i skacze do strony.

    Callback on_click (ustaw_fraze_szukania) ustawia fraza_ocr PRZED
    kolejnym renderem — jedyny bezpieczny sposób modyfikacji klucza
    który należy do widgetu text_input. Ręczne
    st.session_state["fraza_ocr"] = ... po wyrenderowaniu widgetu rzuca
    błąd Streamlita ("cannot be modified after widget is instantiated").
    """

    if not wartosc:
        return

    st.markdown(
        f'<div class="pole-naglowek">'
        f'<span class="pole-etykieta">{etykieta}</span>'
        f'{_znacznik_pola(problem)}'
        f'</div>',
        unsafe_allow_html=True
    )

    st.button(
        str(wartosc),
        key=f"pole_{key}",
        use_container_width=True,
        help="Kliknij, aby znaleźć w dokumencie",
        on_click=ustaw_fraze_szukania,
        args=(str(wartosc),),
    )

    if key in POLA_DO_PRZEPISANIA:
        if MA_KOPIOWANIE:
            copy_button(
                str(wartosc),
                tooltip="Kopiuj do UniFlow",
                copied_label="Skopiowano",
                key=f"kopiuj_{key}"
            )
        else:
            with st.popover("⧉ Kopiuj", use_container_width=True):
                st.caption("Kliknij ikonę kopiowania w rogu:")
                st.code(str(wartosc), language=None)


def wiersz(etykieta, wartosc, ikona=""):
    etykieta_html = f"{etykieta} {ikona}" if ikona else etykieta

    if wartosc:
        return (
            f'<div class="wiersz">'
            f'<span class="wiersz-etykieta">{etykieta_html}</span>'
            f'<span class="wiersz-wartosc">{wartosc}</span>'
            f'</div>'
        )

    return (
        f'<div class="wiersz">'
        f'<span class="wiersz-etykieta">{etykieta_html}</span>'
        f'<span class="wiersz-wartosc pusto">brak w dokumencie</span>'
        f'</div>'
    )


def karta(tytul, wiersze):
    st.markdown(
        f'<div class="karta"><div class="karta-tytul">{tytul}</div>{"".join(wiersze)}</div>',
        unsafe_allow_html=True,
    )


# =====================================================================
# SZUKAJKA W TEKŚCIE OCR, ROZBIEŻNOŚCI I PANEL USTALEŃ
# =====================================================================
# Numery stron wyznaczamy deterministycznie: wartość pola jest szukana
# w tekście OCR, a strona wynika z najbliższego markera [STRONA_X] przed
# trafieniem. Rozbieżności (to samo pole wskazane w dokumencie niejednolicie)
# zgłasza model w liście `rozbieznosci`, a Python sprawdza tylko, czy każda
# zgłoszona wartość naprawdę stoi w tekście.


def ustaw_fraze_szukania(wartosc):
    """Callback kliknięcia — wkleja wartość do pola szukajki.

    Musi to być callback: widget text_input ma własny klucz w session_state
    i po pierwszym renderze ignoruje parametr `value`. Callbacki wykonują się
    PRZED ponownym uruchomieniem skryptu, więc ustawiona tu wartość zdąży
    trafić do widgetu.
    """
    st.session_state["fraza_ocr"] = str(wartosc)


def panel_szukajki(potwierdzone=None):
    """Szukajka w tekście OCR ze skokiem do strony.

    Nie podświetla frazy na skanie — to wymagałoby koordynatów z OCR.
    Pokazuje fragment tekstu z kontekstem i pozwala przeskoczyć na stronę,
    na której fraza występuje.

    `potwierdzone` to wynik zweryfikuj_warianty (sekcja 2A). Gdy wpisana fraza
    jest jednym z zapisów pola-identyfikatora, szukamy od razu wszystkich jego
    zapisów — inaczej "123" nie znajdzie strony, na której OCR przeczytał "I23".
    """
    ocr_text = st.session_state.get("ocr_text", "")

    if not ocr_text:
        return

    st.markdown(
        '<p class="naglowek-sekcji">🔍 Szukaj w dokumencie</p>',
        unsafe_allow_html=True,
    )

    st.session_state.setdefault("fraza_ocr", "")

    fraza = st.text_input(
        "Szukana fraza",
        key="fraza_ocr",
        placeholder="np. numer księgi wieczystej, nazwisko, kwota",
        label_visibility="collapsed",
    )

    if not fraza.strip():
        return

    zapisy = warianty_do_szukania(fraza, potwierdzone)
    trafienia = szukaj_w_ocr_z_wariantami(ocr_text, zapisy)

    if len(zapisy) > 1:
        st.caption(
            "Szukam też innych zapisów tego samego pola: "
            + ", ".join(f"`{z['fraza']}`" for z in zapisy[1:])
        )

    if not trafienia:
        st.warning(
            f"Nie znaleziono „{fraza}” w tekście OCR. "
            "Wartość może być błędnie odczytana albo zapisana inaczej."
        )
        return

    trafienia = trafienia[:20]

    # Numer aktualnego trafienia trzymamy w session_state, bo przeżywa
    # przeładowanie skryptu. Zmiana frazy zeruje licznik — inaczej po wpisaniu
    # nowej frazy zostalibyśmy na trafieniu nr 7, którego już nie ma.
    if st.session_state.get("szukajka_ostatnia_fraza") != fraza:
        st.session_state["szukajka_ostatnia_fraza"] = fraza
        st.session_state["szukajka_nr"] = 0

    numer = min(st.session_state.get("szukajka_nr", 0), len(trafienia) - 1)
    biezace = trafienia[numer]

    pokaz_legende_trafien(trafienia)
    pokaz_nawigacje_trafien(numer, len(trafienia))
    pokaz_biezace_trafienie(biezace, numer, len(trafienia))
    pokaz_liste_trafien(trafienia, numer)


def pokaz_legende_trafien(trafienia):
    """Legenda kolorów — tylko dla rodzajów obecnych w wynikach.

    Przy zwykłym szukaniu jest jeden rodzaj i legenda nic nie wnosi, więc
    jej nie pokazujemy.
    """
    obecne = []
    for trafienie in trafienia:
        if trafienie["rodzaj"] not in obecne:
            obecne.append(trafienie["rodzaj"])

    if len(obecne) < 2:
        return

    czesci = []
    for rodzaj in obecne:
        opis = RODZAJE_TRAFIEN[rodzaj]
        czesci.append(
            f'<span class="legenda-wpis">'
            f'<span class="legenda-kropka" style="background:{opis["kolor"]}"></span>'
            f'{opis["etykieta"]}'
            f'</span>'
        )

    st.markdown(
        f'<div class="legenda-trafien">{"".join(czesci)}</div>',
        unsafe_allow_html=True,
    )


def przewin_trafienie(o_ile, ostatni):
    """Callback strzałek — przewija licznik trafień, bez zapętlania."""
    numer = st.session_state.get("szukajka_nr", 0) + o_ile
    st.session_state["szukajka_nr"] = max(0, min(numer, ostatni))


def pokaz_nawigacje_trafien(numer, ile):
    """Strzałki i licznik — analityk przechodzi po trafieniach po kolei."""
    kol_wstecz, kol_licznik, kol_dalej = st.columns([1, 3, 1])

    with kol_wstecz:
        st.button(
            "◀",
            key="szukajka_wstecz",
            disabled=(numer == 0),
            use_container_width=True,
            on_click=przewin_trafienie,
            args=(-1, ile - 1),
        )

    with kol_licznik:
        st.markdown(
            f'<div class="licznik-trafien">{numer + 1} z {ile}</div>',
            unsafe_allow_html=True,
        )

    with kol_dalej:
        st.button(
            "▶",
            key="szukajka_dalej",
            disabled=(numer == ile - 1),
            use_container_width=True,
            on_click=przewin_trafienie,
            args=(1, ile - 1),
        )


def pokaz_biezace_trafienie(trafienie, numer, ile):
    """Aktualne trafienie na wierzchu: co to za słowo, gdzie stoi, jakiego rodzaju.

    Docelowo (gdy OCR zacznie zwracać koordynaty) to samo trafienie będzie
    podświetlane na skanie w tym samym kolorze. Na razie kolorujemy tylko
    tekst — ramka w kolorze rodzaju i nazwa rodzaju w nagłówku.
    """
    opis = RODZAJE_TRAFIEN[trafienie["rodzaj"]]

    opis_strony = (
        f"strona {trafienie['strona']}"
        if trafienie["strona"]
        else "strona nieznana"
    )

    dopisek = "" if trafienie["dokladne"] else " · forma odmieniona"

    st.markdown(
        f'<div class="biezace-trafienie" style="border-left-color:{opis["kolor"]}">'
        f'<div class="fragment-meta">'
        f'<span class="legenda-kropka" style="background:{opis["kolor"]}"></span>'
        f'{opis["etykieta"]} · {opis_strony}{dopisek}'
        f'</div>'
        f'<div class="biezace-slowo" style="color:{opis["kolor"]}">'
        f'{trafienie["trafienie"]}'
        f'</div>'
        f'…{trafienie["przed"]}'
        f'<mark style="background:{opis["kolor"]}22">{trafienie["trafienie"]}</mark>'
        f'{trafienie["po"]}…'
        f'</div>',
        unsafe_allow_html=True,
    )

    if trafienie["strona"]:
        if st.button(
            f"Pokaż stronę {trafienie['strona']}",
            key="skok_biezace",
            use_container_width=True,
        ):
            st.session_state["wybrana_strona_pdf"] = trafienie["strona"]
            st.rerun()


def ustaw_numer_trafienia(numer):
    """Callback kliknięcia w pozycję listy — przeskok wprost do trafienia."""
    st.session_state["szukajka_nr"] = numer


def pokaz_liste_trafien(trafienia, biezacy):
    """Pozostałe trafienia — przegląd całości bez klikania strzałkami.

    Brak markerów stron oznacza tekst z cache zapisany przed ich wprowadzeniem.
    """
    if all(t["strona"] is None for t in trafienia):
        st.caption(
            "Tekst OCR nie zawiera znaczników stron — skok do strony niedostępny. "
            "Uruchom analizę ponownie, aby je dodać."
        )

    with st.container(height=240, border=True):
        for indeks, trafienie in enumerate(trafienia):
            opis = RODZAJE_TRAFIEN[trafienie["rodzaj"]]

            opis_strony = (
                f"strona {trafienie['strona']}"
                if trafienie["strona"]
                else "strona nieznana"
            )

            klasa = "fragment-ocr biezacy" if indeks == biezacy else "fragment-ocr"

            st.markdown(
                f'<div class="{klasa}" style="border-left-color:{opis["kolor"]}">'
                f'<div class="fragment-meta">'
                f'<span class="legenda-kropka" style="background:{opis["kolor"]}"></span>'
                f'{indeks + 1} z {len(trafienia)} · {opis_strony}'
                f'</div>'
                f'…{trafienie["przed"]}'
                f'<mark style="background:{opis["kolor"]}22">{trafienie["trafienie"]}</mark>'
                f'{trafienie["po"]}…'
                f'</div>',
                unsafe_allow_html=True,
            )

            if indeks != biezacy:
                st.button(
                    "Pokaż to trafienie",
                    key=f"wybierz_trafienie_{indeks}",
                    on_click=ustaw_numer_trafienia,
                    args=(indeks,),
                )


def potwierdzone_rozbieznosci(wynik):
    """Skrót: potwierdzone rozbieżności dla wyniku, z tekstem OCR z session_state.

    Weryfikacja jest liczona przy każdym wyświetleniu, a nie zapisywana
    w cache — kosztuje kilka wyrażeń regularnych, a dzięki temu wpis w cache
    zostaje surowym wynikiem modelu. Wyniki zapisane przed zmianą schematu
    nie mają `rozbieznosci` — wtedy dostajemy po prostu pustą listę.
    """
    potwierdzone, _ = zweryfikuj_warianty(
        st.session_state.get("ocr_text", ""),
        wynik.get("rozbieznosci"),
    )
    return potwierdzone


# Rodzaje trafień — określają kolor w szukajce. Gdy OCR zacznie zwracać
# koordynaty słów, ten sam rodzaj posłuży do kolorowania tekstu na skanie;
# dlatego rodzaj jest przypisany do pojedynczego trafienia, nie do całej listy.
RODZAJE_TRAFIEN = {
    "szukana": {"etykieta": "szukana fraza", "kolor": "#2C3E50"},
    "glowna": {"etykieta": "wartość przyjęta", "kolor": "#2C3E50"},
    "ok": {"etykieta": "inny zapis tej samej wartości", "kolor": "#1E7C34"},
    "zla": {"etykieta": "wartość niezgodna", "kolor": "#C0392B"},
}


def etykieta_sekcji(ikona, nazwa, klucze, wynik, problemy):
    """Nagłówek niosący stan także wtedy, gdy sekcja jest zwinięta.

    Zastępuje sztywne "×2"/"×4" — liczba pól nic nie mówi, a stan mówi,
    czy trzeba tę sekcję w ogóle otwierać.
    """
    ok, z_problemem, brak = stan_sekcji(klucze, wynik, problemy)

    stan = []
    if z_problemem:
        stan.append(f"⚠ {z_problemem}")
    if brak:
        stan.append(f"✕ {brak}")
    if ok:
        stan.append(f"✓ {ok}")

    etykieta = f"{ikona} {nazwa.upper()}"
    if stan:
        etykieta += "　" + "  ".join(stan)

    # sekcja z problemem otwiera się sama — praca do wykonania nie powinna
    # chować się za kliknięciem
    return etykieta, (z_problemem > 0 or brak > 0)


# PODMIEŃ: istniejącą funkcję widok_weryfikacji_uniflow
def panel_ustalen(ustalenia):
    """Wyłącznie rzeczy wymagające decyzji analityka.

    Gdy nie ma rozbieżności — jedna zielona linia zamiast listy potwierdzeń.
    To celowe: panel, który milczy przy zgodnych wnioskach, zostanie
    przeczytany przy niezgodnych.
    """
    if not ustalenia:
        st.markdown(
            '<div class="bez-ustalen">✓ Brak rozbieżności wymagających wyjaśnienia</div>',
            unsafe_allow_html=True,
        )
        return

    wysokie = sum(1 for u in ustalenia if u["poziom"] == "wysoki")

    naglowek = f"Do wyjaśnienia: {len(ustalenia)}"
    if wysokie:
        naglowek += f" · w tym {wysokie} do potwierdzenia przed analizą"

    st.markdown(
        f'<p class="naglowek-sekcji">⚠️ {naglowek}</p>',
        unsafe_allow_html=True,
    )

    for ustalenie in ustalenia:
        klasa = (
            "ustalenie-wysokie"
            if ustalenie["poziom"] == "wysoki"
            else "ustalenie-srednie"
        )
        ikona = "🛑" if ustalenie["poziom"] == "wysoki" else "⚠️"

        st.markdown(
            f'<div class="ustalenie {klasa}">'
            f'<div class="ustalenie-ikona">{ikona}</div>'
            f'<div class="ustalenie-tresc">'
            f'<div class="ustalenie-tytul">{ustalenie["tytul"]}</div>'
            f'<div class="ustalenie-opis">{ustalenie["opis"]}</div>'
            f'<div class="ustalenie-krok">→ {ustalenie["krok"]}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )


def widok_umowy_deweloperskiej(wynik, harmonogram):

    # Rozbieżności zgłoszone przez model, przepuszczone przez weryfikację
    # w tekście OCR — zasilają dymki przy polach, liczniki w nagłówkach sekcji
    # i szukajkę.
    potwierdzone = potwierdzone_rozbieznosci(wynik)

    ustalenia = zbierz_problemy(
        wynik,
        wynik.get("weryfikacja_uniflow", []),
        potwierdzone
    )

    problemy = problemy_wg_pola(ustalenia)

    klucze_problemow = set(problemy.keys())

    adres = " ".join(
        filter(
            None,
            [
                wynik.get("ulica", ""),
                wynik.get("numer_budynku", "")
            ]
        )
    ).strip()

    dodatkowe_nieruchomosci = (
        wynik.get("dodatkowe_nieruchomosci")
        or []
    )

    prawa_przynalezne = (
        wynik.get("prawa_przynalezne")
        or []
    )

    
    if wynik.get("miasto"):
        adres = (
            f"{adres}, {wynik['miasto']}"
            if adres
            else wynik["miasto"]
        )

    pesel_1_status = waliduj_pesel(
        wynik.get("pesel_1")
    )

    pesel_2_status = waliduj_pesel(
        wynik.get("pesel_2")
    )

    status_transakcji = czy_wartosc_transakcji_zgodna(
        wynik
    )

    rachunek = wynik.get(
        "numer_rachunku_powierniczego"
    )

    status_rachunku = waliduj_nrb(
        rachunek
    )

    ikona_rachunku = (
        "✅"
        if status_rachunku == "Poprawny strukturalnie"
        else ""
    )

    # ====================================================
    # DOKUMENT
    # ====================================================

    etykieta_dokument, _ = etykieta_sekcji(
        "📄",
        "Dokument",
        ["numer_umowy", "data_umowy"],
        wynik,
        klucze_problemow
    )

    with st.expander(
        etykieta_dokument,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Numer umowy",
                wynik.get("numer_umowy"),
                "numer_umowy",
                problemy.get("numer_umowy"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                "Data zawarcia",
                wynik.get("data_umowy"),
                "data_umowy",
                problemy.get("data_umowy"),
                potwierdzone
            )

    # ====================================================
    # NABYWCY
    # ====================================================

    etykieta_nabywcy, _ = etykieta_sekcji(
        "👤",
        "Nabywcy",
        ["nabywca_1", "pesel_1", "nabywca_2", "pesel_2"],
        wynik,
        klucze_problemow
    )

    with st.expander(
        etykieta_nabywcy,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Nabywca 1",
                wynik.get("nabywca_1"),
                "nabywca_1",
                problemy.get("nabywca_1"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                f"PESEL 1 {pesel_1_status}",
                wynik.get("pesel_1"),
                "pesel_1",
                problemy.get("pesel_1"),
                potwierdzone
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Nabywca 2",
                wynik.get("nabywca_2"),
                "nabywca_2",
                problemy.get("nabywca_2"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                f"PESEL 2 {pesel_2_status}",
                wynik.get("pesel_2"),
                "pesel_2",
                problemy.get("pesel_2"),
                potwierdzone
            )

    # ====================================================
    # DEWELOPER
    # ====================================================

    etykieta_deweloper, _ = etykieta_sekcji(
        "🏗️",
        "Deweloper",
        ["nazwa_dewelopera", "nip_dewelopera"],
        wynik,
        klucze_problemow
    )

    with st.expander(
        etykieta_deweloper,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Nazwa",
                wynik.get("nazwa_dewelopera"),
                "nazwa_dewelopera",
                problemy.get("nazwa_dewelopera"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                "NIP",
                wynik.get("nip_dewelopera"),
                "nip_dewelopera",
                problemy.get("nip_dewelopera"),
                potwierdzone
            )

    # ====================================================
    # RACHUNEK POWIERNICZY
    # ====================================================

    etykieta_rachunek_powierniczy, _ = etykieta_sekcji(
        "🏦",
        "Rachunek powierniczy",
        ["bank_powiernika", "otwarty_numer_rachunku_powierniczego", "numer_rachunku_powierniczego"],
        wynik,
        klucze_problemow
    )

    with st.expander(
        etykieta_rachunek_powierniczy,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Bank",
                wynik.get("bank_powiernika"),
                "bank_powiernika",
                problemy.get("bank_powiernika")
            )

        with col2:
            pole_pdf(
                "Otwarty rachunek",
                wynik.get("otwarty_numer_rachunku_powierniczego"),
                "otwarty_numer_rachunku_powierniczego",
                problemy.get("otwarty_numer_rachunku_powierniczego"),
                potwierdzone
            )

        pole_pdf(
            f"Rachunek indywidualny ({ikona_rachunku})",
            wynik.get("numer_rachunku_powierniczego"),
            "numer_rachunku_powierniczego",
            problemy.get("numer_rachunku_powierniczego"),
            potwierdzone
        )

    # ====================================================
    # NIERUCHOMOŚĆ
    # ====================================================

    etykieta_nieruchomosc, _ = etykieta_sekcji(
        "🏠",
        "Nieruchomość",
        ["rodzaj_nieruchomosci", "miasto", "ulica", "numer_budynku", "numer_lokalu", "numer_dzialki", "numer_kw"],
        wynik,
        klucze_problemow
    )

    with st.expander(
        etykieta_nieruchomosc,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Adres",
                adres,
                "adres",
                problemy.get("adres")
            )

        with col2:
            pole_pdf(
                "Rodzaj",
                wynik.get("rodzaj_nieruchomosci"),
                "rodzaj_nieruchomosci",
                problemy.get("rodzaj_nieruchomosci")
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Numer budynku",
                wynik.get("numer_budynku"),
                "numer_budynku",
                problemy.get("numer_budynku")
            )

        with col2:
            pole_pdf(
                "Numer lokalu",
                wynik.get("numer_lokalu"),
                "numer_lokalu",
                problemy.get("numer_lokalu")
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Numer działki",
                wynik.get("numer_dzialki"),
                "numer_dzialki",
                problemy.get("numer_dzialki"),
                potwierdzone
            )

        with col2:
            pole_pdf(
                "Księga wieczysta",
                wynik.get("numer_kw"),
                "numer_kw",
                problemy.get("numer_kw"),
                potwierdzone
            )
        # ====================================================
    # PRAWA PRZYNALEŻNE
    # ====================================================

    if prawa_przynalezne:

        for idx, prawo in enumerate(
            prawa_przynalezne,
            start=1
        ):

            with st.expander(
                f"🚗 PRAWO PRZYNALEŻNE {idx}",
                expanded=False
            ):

                col1, col2 = st.columns(2)

                with col1:
                    pole_pdf(
                        "Rodzaj",
                        prawo.get("rodzaj"),
                        f"prawo_rodzaj_{idx}",
                        problemy.get(f"prawo_rodzaj_{idx}")
                    )

                with col2:
                    pole_pdf(
                        "Tytuł prawny",
                        prawo.get("tytul_prawny"),
                        f"prawo_tytul_{idx}",
                        problemy.get(f"prawo_tytul_{idx}")
                    )

                col1, col2 = st.columns(2)

                with col1:
                    pole_pdf(
                        "Oznaczenie",
                        prawo.get("oznaczenie"),
                        f"prawo_oznaczenie_{idx}",
                        problemy.get(f"prawo_oznaczenie_{idx}")
                    )

                with col2:
                    pole_pdf(
                        "Cena zakupu",
                        prawo.get("cena"),
                        f"prawo_cena_{idx}",
                        problemy.get(f"prawo_cena_{idx}")
                    )
    
        # ====================================================
    # DODATKOWE NIERUCHOMOŚCI
    # ====================================================

    for idx, nieruchomosc in enumerate(
        dodatkowe_nieruchomosci,
        start=1
    ):

        adres2 = " ".join(
            filter(
                None,
                [
                    nieruchomosc.get("ulica", ""),
                    nieruchomosc.get("numer_budynku", "")
                ]
            )
        ).strip()

        if nieruchomosc.get("miasto"):

            adres2 = (
                f"{adres2}, {nieruchomosc['miasto']}"
                if adres2
                else nieruchomosc["miasto"]
            )

        with st.expander(
            f"🏘️ DODATKOWA NIERUCHOMOŚĆ {idx}",
            expanded=False
        ):

            col1, col2 = st.columns(2)

            with col1:
                pole_pdf(
                    "Rodzaj",
                    nieruchomosc.get(
                        "rodzaj_nieruchomosci"
                    ),
                    f"dod_rodzaj_{idx}",
                    problemy.get(f"dod_rodzaj_{idx}")
                )

            with col2:
                pole_pdf(
                    "Adres",
                    adres2,
                    f"dod_adres_{idx}",
                    problemy.get(f"dod_adres_{idx}")
                )

            col1, col2 = st.columns(2)

            with col1:
                pole_pdf(
                    "Tytuł prawny",
                    nieruchomosc.get(
                        "tytul_prawny"
                    ),
                    f"dod_tytul_{idx}",
                    problemy.get(f"dod_tytul_{idx}")
                )

            with col2:
                pole_pdf(
                    "Numer lokalu",
                    nieruchomosc.get(
                        "numer_lokalu"
                    ),
                    f"dod_lokal_{idx}",
                    problemy.get(f"dod_lokal_{idx}")
                )

            col1, col2 = st.columns(2)

            with col1:
                pole_pdf(
                    "Oznaczenie",
                    nieruchomosc.get(
                        "oznaczenie"
                    ),
                    f"dod_oznaczenie_{idx}",
                    problemy.get(f"dod_oznaczenie_{idx}")
                )

            with col2:
                pole_pdf(
                    "Księga wieczysta",
                    nieruchomosc.get(
                        "numer_kw"
                    ),
                    f"dod_kw_{idx}",
                    problemy.get(f"dod_kw_{idx}")
                )

            pole_pdf(
                "Cena",
                nieruchomosc.get(
                    "cena_nieruchomosci"
                ),
                f"dod_cena_{idx}",
                problemy.get(f"dod_cena_{idx}")
            )

    # ====================================================
    # TRANSAKCJA
    # ====================================================

    etykieta_transakcja, _ = etykieta_sekcji(
        "💰",
        "Transakcja",
        ["cena_nieruchomosci", "laczna_wartosc_transakcji", "liczba_transz", "termin_przeniesienia_wlasnosci", "termin_odrebnej_wlasnosci"],
        wynik,
        klucze_problemow
    )

    with st.expander(
        etykieta_transakcja,
        expanded=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Cena nieruchomości",
                wynik.get("cena_nieruchomosci"),
                "cena_nieruchomosci",
                problemy.get("cena_nieruchomosci")
            )

        with col2:
            pole_pdf(
                f"Wartość łączna {status_transakcji}",
                wynik.get("laczna_wartosc_transakcji"),
                "laczna_wartosc_transakcji",
                problemy.get("laczna_wartosc_transakcji")
            )

        col1, col2 = st.columns(2)

        with col1:
            pole_pdf(
                "Liczba transz",
                wynik.get("liczba_transz"),
                "liczba_transz",
                problemy.get("liczba_transz")
            )

        with col2:
            pole_pdf(
                "Przeniesienie własności",
                wynik.get("termin_przeniesienia_wlasnosci"),
                "termin_przeniesienia_wlasnosci",
                problemy.get("termin_przeniesienia_wlasnosci"),
                potwierdzone
            )

        pole_pdf(
            "Odrębna własność",
            wynik.get("termin_odrebnej_wlasnosci"),
            "termin_odrebnej_wlasnosci",
            problemy.get("termin_odrebnej_wlasnosci"),
            potwierdzone
        )

    # ====================================================
    # HARMONOGRAM
    # ====================================================

    with st.expander(
        f"📅 HARMONOGRAM   ×{len(harmonogram)}",
        expanded=False
    ):

        if harmonogram:

            df = pd.DataFrame(
                harmonogram
            ).rename(
                columns={
                    "numer_transzy": "Transza",
                    "kwota": "Kwota",
                    "termin_platnosci": "Termin płatności",
                }
            )

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )

        else:
            st.caption(
                "Brak harmonogramu."
            )

        
def widok_json(wynik):

    st.json(
        wynik,
        expanded=True
    )

def widok_ocr():

    ocr_text = st.session_state.get(
        "ocr_text",
        ""
    )

    st.text_area(
        "Treść OCR",
        value=ocr_text,
        height=900
    )

    
def pokaz_wynik_dokumentu(typ_dokumentu, wynik):

    if typ_dokumentu == "umowa_deweloperska":
        widok_umowy_deweloperskiej(
            wynik,
            wynik.get("harmonogram_transz", [])
        )

    elif typ_dokumentu == "umowa_przedwstepna":
        widok_json(wynik)

    elif typ_dokumentu == "umowa_rezerwacyjna":
        widok_json(wynik)

    elif typ_dokumentu == "prospekt":
        widok_json(wynik)

    elif typ_dokumentu == "oswiadczenie_zbywcy":
        widok_json(wynik)
        
        
def widok_podsumowania(tekst):
    st.markdown('<p class="naglowek-sekcji">📝 Podsumowanie</p>', unsafe_allow_html=True)
    st.markdown(f'<div class="podsumowanie">{tekst}</div>', unsafe_allow_html=True)


def widok_ryzyk(lista_ryzyk):
    st.markdown('<p class="naglowek-sekcji">⚠️ Potencjalne ryzyka</p>', unsafe_allow_html=True)

    if not lista_ryzyk:
        st.caption("Nie zidentyfikowano istotnych ryzyk w tym dokumencie.")
        return

    kolejnosc = {"wysoka": 0, "srednia": 1, "niska": 2}
    posortowane = sorted(lista_ryzyk, key=lambda r: kolejnosc.get(r.get("waga", "srednia"), 1))

    for ryzyko in posortowane:
        waga = ryzyko.get("waga", "srednia")
        if waga not in kolejnosc:
            waga = "srednia"

        opis = html.unescape(ryzyko.get("opis", ""))

        st.markdown(
            f'<div class="karta-ryzyko karta-ryzyko-{waga}">'
            f'<span class="badge-waga-{waga}">{waga}</span>'
            f'&nbsp;&nbsp;{opis}</div>',
            unsafe_allow_html=True,
        )

# =====================================================================
# URUCHOMIENIE ANALIZY
# =====================================================================

def uruchom_analize(plik_bajty, nazwa_pliku, numer_wniosku, token, wymus_ponowna_analize=False):
    """Analiza dokumentu: cache -> OCR -> ekstrakcja -> zapis do cache."""
    pasek = st.progress(0, text="Rozpoczynanie analizy...")

    pdf_hash = policz_hash_pdf(plik_bajty)

    id_analizy = str(uuid.uuid4())

    typ_dokumentu = rozpoznaj_typ_dokumentu(nazwa_pliku)

    schema = pobierz_schema(typ_dokumentu)

    # Hash schematu wchodzi do klucza cache: po zmianie schematu (inne pola,
    # inne opisy) stary wynik nie odpowiada już temu, o co prosimy model.
    hash_schematu = policz_hash_schematu(schema)

    cached_result = None

    if not wymus_ponowna_analize:
        cached_result = get_document_cache(
            pdf_hash=pdf_hash,
            nr_wniosku=numer_wniosku,
            hash_schematu=hash_schematu
        )

    if cached_result is not None:

        st.session_state["analiza_z_cache"] = True

        st.info("📦 Dokument znaleziony w cache")

        st.session_state["nazwa_pliku_analizowany"] = nazwa_pliku
        st.session_state["typ_dokumentu"] = typ_dokumentu
        st.session_state["tryb_analizy"] = "Cache Impala"
        st.session_state["czas_analizy"] = datetime.now().strftime("%H:%M:%S")
        st.session_state["id_analizy"] = id_analizy

        if "wyniki_ekstrakcji" not in st.session_state:
            st.session_state["wyniki_ekstrakcji"] = {}

        st.session_state["ocr_text"] = (
            cached_result["ocr_text"]
        )

        st.session_state["wyniki_ekstrakcji"][nazwa_pliku] = (
            cached_result["wynik"]
        )
        st.rerun()

    try:
        pasek.progress(20, text="Krok 1/2: OCR...")

        ocr_raw = wywolaj_ocr_api(
            plik_bajty,
            token,
            numer_wniosku
        )

        ocr_z_numerami_stron = dodaj_markery_stron(
            ocr_raw
        )

        st.session_state["ocr_text"] = ocr_z_numerami_stron

        dane_uniflow = st.session_state.get(
            "uniflow",
            {}
        )

        tekst_uniflow = json.dumps(
            dane_uniflow,
            ensure_ascii=False,
            indent=2
        )

        prompt_extract = f"""
        DANE KLIENTÓW Z SYSTEMU UNIFLOW:

        {tekst_uniflow}

        PONIŻEJ ZNAJDUJE SIĘ TREŚĆ DOKUMENTU.

        Porównuj dane klientów z UniFlow z danymi nabywców
        występującymi w dokumencie.

        TREŚĆ DOKUMENTU:

        {ocr_z_numerami_stron}
        """

        pasek.progress(
            70,
            text=f"Krok 2/2: Ekstrakcja ({typ_dokumentu})..."
        )

        wynik = wywolaj_extract_api(
            prompt_extract,
            token,
            numer_wniosku,
            schema,
            dane_uniflow
        )

        save_document_cache(
            pdf_hash=pdf_hash,
            nr_wniosku=numer_wniosku,
            hash_schematu=hash_schematu,
            id_analizy=id_analizy,
            document_type=typ_dokumentu,
            # markery [STRONA_X] muszą trafić do cache — bez nich
            # szukajka i klik w pole nie wskażą strony
            ocr_text=ocr_z_numerami_stron,
            extracted_data=wynik
        )

        st.info("💾 Zapis wyniku do bazy")

    except Exception as blad:
        pasek.empty()
        st.error(f"Analiza nie powiodła się: {blad}")
        return

    pasek.progress(100, text="Analiza zakończona.")
    time.sleep(0.3)
    pasek.empty()

    st.session_state["nazwa_pliku_analizowany"] = nazwa_pliku
    st.session_state["typ_dokumentu"] = typ_dokumentu
    st.session_state["tryb_analizy"] = "Prawdziwe API"
    st.session_state["czas_analizy"] = datetime.now().strftime("%H:%M:%S")

    if "wyniki_ekstrakcji" not in st.session_state:
        st.session_state["wyniki_ekstrakcji"] = {}

    st.session_state["wyniki_ekstrakcji"][nazwa_pliku] = wynik
    st.session_state["analiza_z_cache"] = False
    st.rerun()


def sekcja_akcja_i_kluczowe_dane(plik_bajty, nazwa_pliku, numer_wniosku, token):
    juz_przeanalizowany = st.session_state.get("nazwa_pliku_analizowany") == nazwa_pliku
     
    if not juz_przeanalizowany:
        st.markdown('<p class="naglowek-sekcji">🔑 Kluczowe dane</p>', unsafe_allow_html=True)
        st.markdown(
            '<div class="tekst-pomocniczy">Dokument jest wczytany. Uruchom analizę, aby odczytać '
            'kluczowe dane, podsumowanie i wykaz ryzyk.</div>',
            unsafe_allow_html=True,
        )
        czy_gotowe = bool(token)
        wymus_ponowna_analize = st.checkbox(
            "🔄 Wymuś ponowną analizę (pomiń cache)",
            value=False
        )
        
        if st.button("▶ Uruchom analizę dokumentu", type="primary", disabled=not czy_gotowe):
            uruchom_analize(plik_bajty, nazwa_pliku, numer_wniosku, token, wymus_ponowna_analize)
        if not czy_gotowe:
            st.caption("Dodaj token.txt, aby korzystać z prawdziwego API.")
        return

    tryb_uzyty = st.session_state.get("tryb_analizy")
    klasa = "badge-tryb-api"

    col_status, col_przycisk = st.columns([3, 1])
    with col_status:
        st.markdown(
            f'<div class="info-pliku" style="margin-top:8px;">✅ Analiza: '
            f'{st.session_state["czas_analizy"]} &nbsp;'
            f'<span class="{klasa}">{tryb_uzyty}</span></div>',
            unsafe_allow_html=True,
        )
    with col_przycisk:
        if st.button("↺ Ponów"):
            del st.session_state["nazwa_pliku_analizowany"]
            st.rerun()

    wynik = st.session_state["wyniki_ekstrakcji"][nazwa_pliku]

    typ_dokumentu = rozpoznaj_typ_dokumentu(
        nazwa_pliku
    )


    tab_dane, tab_ocr, tab_json = st.tabs(
        [
            "🔑 Kluczowe dane",
            "📄 OCR",
            "📋 JSON"
        ]
    )

    with tab_dane:

        with st.container(
            height=900,
            border=True
        ):

            pokaz_wynik_dokumentu(
                typ_dokumentu,
                wynik
            )
    with tab_ocr:

        widok_ocr()

    with tab_json:

        widok_json(wynik)

def sekcja_podsumowanie_i_ryzyka(nazwa_pliku):
    if st.session_state.get("nazwa_pliku_analizowany") is None:
        return

    wynik = st.session_state["wyniki_ekstrakcji"][nazwa_pliku]
    st.divider()
    widok_podsumowania(wynik.get("podsumowanie", ""))
    st.markdown("<div style='height:22px;'></div>", unsafe_allow_html=True)
    widok_ryzyk(wynik.get("potencjalne_ryzyka", []))

def widok_weryfikacji_uniflow(wynik):
    """Panel ustaleń: wyłącznie rzeczy wymagające decyzji analityka.

    Zastępuje listę wszystkich wyników weryfikacji UniFlow. Zgodności nie są
    pokazywane — panel, który potwierdza oczywistości, przestaje być czytany
    po kilku analizach. Do weryfikacji z modelu dochodzą twarde kontrole
    liczone w Pythonie (PESEL, NRB, suma transz) i rozbieżności w dokumencie.
    """

    ustalenia = zbierz_problemy(
        wynik,
        wynik.get("weryfikacja_uniflow", []),
        potwierdzone_rozbieznosci(wynik)
    )

    panel_ustalen(ustalenia)


# =====================================================================
# MAIN
# =====================================================================
# def wnioskodawcy_z_ocr(wynik):
#     wnioskodawcy = []

#     for nr in range (1,6):
#         nazwa = wynik.get(f"nabywca_{nr}")
#         pesel = wynik.get(f"pesel_{nr}")

#         if nazwa:
#             wnioskodawcy.append({
#                 "imie_nazwisko": nazwa.strip(),
#                 "pesel": str(pesel).strip() if pesel else "",
#             })

#     return wnioskodawcy

# def pokaz_porownanie(osoby_uniflow, wynik):

#     osoby_ocr = wnioskodawcy_z_ocr(wynik)

#     porownanie = []

#     max_osob = max(len(osoby_uniflow), len(osoby_ocr))

#     for i in range(max_osob):

#         osoba_h = osoby_uniflow[i] if i < len(osoby_uniflow) else {}
#         osoba_o = osoby_ocr[i] if i < len(osoby_ocr) else {}

#         porownanie.append({
#             "Wnioskodawca": i + 1,

#             "OCR Imię i nazwisko": osoba_o.get("imie_nazwisko", ""),
#             "Uniflow Imię i nazwisko": osoba_h.get("imie_nazwisko", ""),
#             "Zgodność imienia i nazwiska ": (
#                 "✅"
#                 if osoba_o.get("imie_nazwisko", "").lower()
#                 == osoba_h.get("imie_nazwisko", "").lower()
#                 else "❌"
#             ),

#             "OCR PESEL": osoba_o.get("pesel", ""),
#             "Uniflow PESEL": osoba_h.get("pesel", ""),
#             "Zgodność PESEL": (
#                 "✅"
#                 if osoba_o.get("pesel", "")
#                 == osoba_h.get("pesel", "")
#                 else "❌"
#             ),
#         })

#     st.markdown(
#         '<p class="naglowek-sekcji">✅ Porównanie OCR vs Uniflow</p>',
#         unsafe_allow_html=True,
#     )

#     st.dataframe(
#         pd.DataFrame(porownanie),
#         use_container_width=True,
#         hide_index=True,
#     )
   
    
def menu_boczne():

    wybor = st.sidebar.radio(
        "Nawigacja",
        [
            "📄 Umowa deweloperska",
            "📄 Umowa przedwstępna",
            "📄 Umowa rezerwacyjna",
            "📄 Wzór prospektu informacyjnego",
            "📄 Oświadczenie zbywcy",
            "📋 Podsumowanie"
        ]
    )

    return wybor


def zakladka_umowa_deweloperska(
    nr_wniosku,
    token
):

    plik = sekcja_upload_widget()
    
    if plik:
        st.session_state["umowa_deweloperska_plik"] = {
            "nazwa": plik.name,
            "bajty": plik.getvalue()
        }

    plik_dane = st.session_state.get(
        "umowa_deweloperska_plik"
    )

    if not plik_dane:
        return
    

    bajty_pdf = plik_dane["bajty"]

    nazwa_pliku = plik_dane["nazwa"]
    
    
    # Panel ustaleń na pełnej szerokości — przed podziałem na kolumny.
    wynik_do_panelu = st.session_state.get(
        "wyniki_ekstrakcji", {}
    ).get(nazwa_pliku)

    if wynik_do_panelu:
        potwierdzone_panel = potwierdzone_rozbieznosci(wynik_do_panelu)
        ustalenia_panel = zbierz_problemy(
            wynik_do_panelu,
            wynik_do_panelu.get("weryfikacja_uniflow", []),
            potwierdzone_panel
        )
        panel_ustalen(ustalenia_panel)

    col_podglad, col_dane = st.columns(
        [1, 1.05],
        gap="large"
    )

    with col_podglad:

        # Szukajka nad dokumentem — analityk wpisuje frazę zanim otworzy
        # pełny podgląd i od razu widzi, na której stronie szukać.
        wynik_pliku = st.session_state.get(
            "wyniki_ekstrakcji",
            {}
        ).get(nazwa_pliku)

        if wynik_pliku:
            panel_szukajki(
                potwierdzone_rozbieznosci(wynik_pliku)
            )

        else:
            panel_szukajki()

        sekcja_podglad_dokumentu(
            bajty_pdf,
            nazwa_pliku
        )

    with col_dane:
        sekcja_akcja_i_kluczowe_dane(
            bajty_pdf,
            nazwa_pliku,
            nr_wniosku,
            token
        )

    sekcja_podsumowanie_i_ryzyka(
        nazwa_pliku
    )
    
    
def zakladka_podsumowanie():

    # st.markdown(
    #     '<p class="naglowek-sekcji">📋 Podsumowanie wniosku</p>',
    #     unsafe_allow_html=True,
    # )

    wynik = st.session_state.get(
        "wyniki_ekstrakcji",
        {}
    )

    if not wynik:
        st.info(
            "Przeanalizuj dokument, aby zobaczyć podsumowanie."
        )
        return

    pierwszy_wynik = next(
        iter(wynik.values())
    )
    
    widok_weryfikacji_uniflow(
        pierwszy_wynik
    )
        

def main():
    token = panel_konfiguracji()

    banner_naglowek()

    # dane_wniosku = pobierz_dane_wniosku()
    # sekcja_dane_wniosku(dane_wniosku)
    # st.divider()
    
    nr_wniosku = sekcja_numer_wniosku()
    
    sekcja_dane_uniflow(nr_wniosku)
  
    zakladka = menu_boczne()
    
    if zakladka == "📋 Podsumowanie":

        zakladka_podsumowanie()

    elif zakladka == "📄 Umowa deweloperska":

        zakladka_umowa_deweloperska(
            nr_wniosku,
            token
        )

    elif zakladka == "📄 Umowa przedwstępna":

        st.info("W przygotowaniu")

    elif zakladka == "📄 Umowa rezerwacyjna":

        st.info("W przygotowaniu")

    elif zakladka == "📄 Wzór prospektu informacyjnego":

        st.info("W przygotowaniu")

    elif zakladka == "📄 Oświadczenie zbywcy":

        st.info("W przygotowaniu")


if __name__ == "__main__":
    main()
