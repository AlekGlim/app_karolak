"""Panel dokumentu: szukajka, nawigacja po trafieniach i podgląd strony.

Układ jak w app_lite: jedno pole szukania, jeden pasek nawigacji, pod nim
strona dokumentu. Klik w wartość pola po prawej wkleja ją do szukajki
i przełącza na pierwsze wystąpienie.

Większość dokumentów to skany, a endpoint OCR (prebuilt-layout) zwraca sam
tekst w markdownie, podzielony na strony — bez pozycji słów. Dla takiej
strony szukajka przełącza podgląd na właściwą stronę i pokazuje nad nim
fragment tekstu z trafieniem. Tylko PDF z warstwą tekstową (rzadkość) daje
pozycje słów — wtedy trafienie jest dodatkowo zaznaczone na obrazie strony.
"""

import html
import io

import streamlit as st
from PIL import Image, ImageDraw

from core.indeks import (
    pierwsze_do_pokazania,
    strona_ze_slow,
    strony_z_ocr,
    zloz_strony,
    znajdz_w_stronach,
)
from core.szukanie import warianty_do_szukania
from core.tekst import tekst_do_wyswietlenia
from services import pdf

KLUCZ_FRAZY = "fraza_ocr"
KLUCZ_TRAFIENIA = "szukajka_nr"
KLUCZ_STRONY = "wybrana_strona_pdf"
KLUCZ_OSTATNIEJ_FRAZY = "szukajka_ostatnia_fraza"
KLUCZ_DOKUMENTU = "szukajka_dokument"

SKALA_RENDERU = 2.0
MARGINES_RAMKI = 2
WYSOKOSC_PODGLADU = 800

# Kolor zależy od rodzaju trafienia (patrz warianty_do_szukania): przy polu
# z rozbieżnością widać naraz wartość przyjętą, jej inne zapisy i wartości
# niezgodne. "kolor" dla legendy w HTML, "rgb" do rysowania na stronie.
RODZAJE_TRAFIEN = {
    "szukana": {"etykieta": "szukana fraza", "kolor": "#D4A900", "rgb": (255, 214, 0)},
    "glowna": {"etykieta": "wartość przyjęta", "kolor": "#D4A900", "rgb": (255, 214, 0)},
    "ok": {"etykieta": "inny zapis tej samej wartości", "kolor": "#1E7C34", "rgb": (40, 170, 80)},
    "zla": {"etykieta": "wartość niezgodna", "kolor": "#C0392B", "rgb": (225, 45, 45)},
}
ALFA_AKTYWNEGO = 110
ALFA_POZOSTALYCH = 45
OBRYS_AKTYWNEGO = (196, 30, 58)


def ustaw_fraze_szukania(wartosc):
    """Callback kliknięcia w wartość pola — wkleja ją do szukajki.

    Musi to być callback: widget text_input ma własny klucz w session_state
    i po pierwszym renderze ignoruje parametr `value`. Callbacki wykonują się
    PRZED ponownym uruchomieniem skryptu, więc ustawiona tu wartość zdąży
    trafić do widgetu.
    """
    st.session_state[KLUCZ_FRAZY] = str(wartosc)


# --- dane dokumentu (cache per dokument) ---

@st.cache_data(show_spinner="Wczytywanie dokumentu...", max_entries=16)
def _strony_pdf(_plik_bajty, pdf_hash):
    """Strony z warstwy tekstowej i liczba stron. Klucz cache: pdf_hash."""
    liczba = pdf.liczba_stron(_plik_bajty)

    try:
        slowa = pdf.slowa_stron(_plik_bajty)
    except Exception:
        # uszkodzona albo nietypowa warstwa tekstowa nie może zablokować
        # podglądu — zostaje szukanie w tekście OCR
        slowa = []

    return [strona_ze_slow(n, s) for n, s in enumerate(slowa, start=1)], liczba


@st.cache_data(show_spinner=False, max_entries=64)
def _obraz_strony(_plik_bajty, pdf_hash, numer_strony, skala):
    return pdf.renderuj_strone(_plik_bajty, numer_strony, skala)


def _zaznacz(obraz, trafienia_na_stronie, skala):
    """PNG strony z zaznaczonymi trafieniami: [(trafienie, czy_aktywne)].

    Aktywne mocno i z obrysem, pozostałe na tej samej stronie blado —
    widać, że wystąpień jest więcej, ale wzrok idzie do bieżącego.
    """
    warstwa = Image.new("RGBA", obraz.size, (0, 0, 0, 0))
    rysownik = ImageDraw.Draw(warstwa)

    # aktywne na końcu, żeby leżało na wierzchu
    for trafienie, aktywne in sorted(trafienia_na_stronie, key=lambda para: para[1]):
        rgb = RODZAJE_TRAFIEN[trafienie["rodzaj"]]["rgb"]
        alfa = ALFA_AKTYWNEGO if aktywne else ALFA_POZOSTALYCH

        for p in trafienie["prostokaty"]:
            ramka = [
                (p["x0"] - MARGINES_RAMKI) * skala,
                (p["top"] - MARGINES_RAMKI) * skala,
                (p["x1"] + MARGINES_RAMKI) * skala,
                (p["bottom"] + MARGINES_RAMKI) * skala,
            ]
            rysownik.rectangle(ramka, fill=rgb + (alfa,))
            if aktywne:
                rysownik.rectangle(ramka, outline=OBRYS_AKTYWNEGO, width=3)

    bufor = io.BytesIO()
    Image.alpha_composite(obraz, warstwa).convert("RGB").save(bufor, format="PNG")
    return bufor.getvalue()


# --- nawigacja ---

def _przewin_trafienie(o_ile, ostatni):
    numer = st.session_state.get(KLUCZ_TRAFIENIA, 0) + o_ile
    st.session_state[KLUCZ_TRAFIENIA] = max(0, min(numer, ostatni))


def _zmien_strone(o_ile, liczba_stron):
    numer = st.session_state.get(KLUCZ_STRONY, 1) + o_ile
    st.session_state[KLUCZ_STRONY] = max(1, min(numer, liczba_stron))


def _pasek_nawigacji(trafienia, aktywne, strona, liczba_stron):
    """Jeden pasek: po trafieniach, gdy są, a w przeciwnym razie po stronach."""
    kol_wstecz, kol_opis, kol_dalej = st.columns([1.35, 2, 1.35])

    if trafienia:
        rodzaj = RODZAJE_TRAFIEN[trafienia[aktywne]["rodzaj"]]
        opis = (
            f'<span class="legenda-kropka" style="background:{rodzaj["kolor"]}"></span>'
            f'Trafienie <b>{aktywne + 1}</b> z <b>{len(trafienia)}</b> · strona <b>{strona}</b>'
        )
        wstecz = ("← Poprzednie", aktywne == 0, _przewin_trafienie, (-1, len(trafienia) - 1))
        dalej = ("Następne →", aktywne >= len(trafienia) - 1, _przewin_trafienie, (1, len(trafienia) - 1))
    else:
        opis = f"Strona <b>{strona}</b> z <b>{liczba_stron}</b>"
        wstecz = ("← Strona", strona <= 1, _zmien_strone, (-1, liczba_stron))
        dalej = ("Strona →", strona >= liczba_stron, _zmien_strone, (1, liczba_stron))

    for kolumna, (etykieta, wylaczony, akcja, argumenty), klucz in (
        (kol_wstecz, wstecz, "dokument_wstecz"),
        (kol_dalej, dalej, "dokument_dalej"),
    ):
        with kolumna:
            st.button(
                etykieta,
                key=klucz,
                disabled=wylaczony,
                use_container_width=True,
                on_click=akcja,
                args=argumenty,
            )

    with kol_opis:
        st.markdown(f'<div class="pasek-nawigacji">{opis}</div>', unsafe_allow_html=True)


def _legenda(trafienia):
    """Legenda kolorów — tylko gdy w wynikach jest więcej niż jeden rodzaj."""
    obecne = []
    for trafienie in trafienia:
        etykieta = RODZAJE_TRAFIEN[trafienie["rodzaj"]]["etykieta"]
        if (trafienie["rodzaj"], etykieta) not in obecne:
            obecne.append((trafienie["rodzaj"], etykieta))

    if len(obecne) < 2:
        return

    wpisy = "".join(
        f'<span class="legenda-wpis">'
        f'<span class="legenda-kropka" style="background:{RODZAJE_TRAFIEN[rodzaj]["kolor"]}"></span>'
        f'{etykieta}</span>'
        for rodzaj, etykieta in obecne
    )
    st.markdown(f'<div class="legenda-trafien">{wpisy}</div>', unsafe_allow_html=True)


def _przytnij(tekst, dlugosc, od_konca):
    """Najwyżej `dlugosc` znaków, cięte na granicy słowa."""
    if len(tekst) <= dlugosc:
        return tekst
    if od_konca:
        wycinek = tekst[-dlugosc:]
        return wycinek[wycinek.find(" ") + 1:] if " " in wycinek else wycinek
    wycinek = tekst[:dlugosc]
    return wycinek[:wycinek.rfind(" ")] if " " in wycinek else wycinek


def _fragment(trafienie):
    """Karta z trafieniem w tekście OCR — na skanie jedyny wskaźnik, gdzie stoi fraza.

    Tekst przechodzi przez tekst_do_wyswietlenia: bez znaczników markdown
    i tabel z odpowiedzi OCR, komórki tabeli rozdzielone " · ".
    """
    rodzaj = RODZAJE_TRAFIEN[trafienie["rodzaj"]]
    przed = _przytnij(tekst_do_wyswietlenia(trafienie["przed"]).lstrip(), 150, od_konca=True)
    po = _przytnij(tekst_do_wyswietlenia(trafienie["po"]).rstrip(), 150, od_konca=False)
    fraza = tekst_do_wyswietlenia(trafienie["trafienie"]).strip()

    meta = f'Strona {trafienie["strona"]} · tekst z OCR'
    if not trafienie.get("dokladne", True):
        meta += " · forma odmieniona"

    st.markdown(
        f'<div class="kontekst-trafienia" style="border-left-color:{rodzaj["kolor"]}">'
        f'<div class="fragment-meta">{html.escape(meta)}</div>'
        f'…{html.escape(przed)}'
        f'<mark style="background:{rodzaj["kolor"]}33;box-shadow:inset 0 -2px 0 {rodzaj["kolor"]}">'
        f'{html.escape(fraza)}</mark>'
        f'{html.escape(po)}…'
        f'</div>',
        unsafe_allow_html=True,
    )


# --- panel ---

def panel_dokumentu(plik_bajty, pdf_hash, nazwa_pliku, ocr_text="", potwierdzone=None):
    """Szukajka + podgląd dokumentu.

    `ocr_text` (z markerami stron) uzupełnia strony bez warstwy tekstowej;
    `potwierdzone` (rozbieżności) sprawia, że fraza będąca jednym z zapisów
    pola szuka od razu wszystkich jego zapisów, w kolorach rodzaju.
    """
    st.markdown('<p class="naglowek-sekcji">📄 Dokument</p>', unsafe_allow_html=True)

    # nowy dokument: od pierwszej strony i pierwszego trafienia
    if st.session_state.get(KLUCZ_DOKUMENTU) != pdf_hash:
        st.session_state[KLUCZ_DOKUMENTU] = pdf_hash
        st.session_state[KLUCZ_STRONY] = 1
        st.session_state[KLUCZ_TRAFIENIA] = 0
        st.session_state[KLUCZ_OSTATNIEJ_FRAZY] = None

    strony_pdf, liczba_stron = _strony_pdf(plik_bajty, pdf_hash)
    strony = zloz_strony(strony_pdf, strony_z_ocr(ocr_text), liczba_stron)

    # Skan przed analizą nie ma żadnego tekstu — szukajka czeka na OCR.
    ma_tekst = any(strona["tekst"].strip() for strona in strony)

    st.session_state.setdefault(KLUCZ_FRAZY, "")

    fraza = st.text_input(
        "Szukaj w dokumencie",
        key=KLUCZ_FRAZY,
        placeholder=(
            "Wpisz frazę albo kliknij wartość pola po prawej"
            if ma_tekst
            else "Szukanie w dokumencie będzie dostępne po analizie (OCR)"
        ),
        disabled=not ma_tekst,
        label_visibility="collapsed",
    )
    if not ma_tekst:
        fraza = ""

    trafienia = []
    if fraza.strip():
        trafienia = znajdz_w_stronach(strony, warianty_do_szukania(fraza, potwierdzone))

    # nowa fraza (wpisana albo z kliknięcia w pole) zaczyna od pierwszego
    # trafienia wartości przyjętej, nie od wartości niezgodnej
    if fraza != st.session_state.get(KLUCZ_OSTATNIEJ_FRAZY):
        st.session_state[KLUCZ_OSTATNIEJ_FRAZY] = fraza
        st.session_state[KLUCZ_TRAFIENIA] = pierwsze_do_pokazania(trafienia)

    aktywne = max(0, min(st.session_state.get(KLUCZ_TRAFIENIA, 0), len(trafienia) - 1))

    if trafienia:
        strona = trafienia[aktywne]["strona"]
        st.session_state[KLUCZ_STRONY] = strona
    else:
        strona = max(1, min(st.session_state.get(KLUCZ_STRONY, 1), liczba_stron))

    if fraza.strip() and not trafienia:
        st.warning(
            f"Nie znaleziono „{fraza}” w dokumencie. "
            "Wartość może być zapisana inaczej albo pochodzić z błędnego odczytu."
        )

    _pasek_nawigacji(trafienia, aktywne, strona, liczba_stron)

    if trafienia:
        _legenda(trafienia)
        if not trafienia[aktywne]["prostokaty"]:
            _fragment(trafienia[aktywne])

    obraz = _obraz_strony(plik_bajty, pdf_hash, strona, SKALA_RENDERU)
    na_stronie = [
        (trafienie, indeks == aktywne)
        for indeks, trafienie in enumerate(trafienia)
        if trafienie["strona"] == strona
    ]

    with st.container(height=WYSOKOSC_PODGLADU, border=True):
        st.image(_zaznacz(obraz, na_stronie, SKALA_RENDERU), use_container_width=True)

    kol_info, kol_pobierz = st.columns([3, 1])
    with kol_info:
        st.markdown(
            f'<div class="info-pliku">{html.escape(nazwa_pliku)} · '
            f'{len(plik_bajty) / 1024:.0f} KB · {liczba_stron} str.</div>',
            unsafe_allow_html=True,
        )
    with kol_pobierz:
        st.download_button(
            "⬇ Pobierz",
            data=plik_bajty,
            file_name=nazwa_pliku,
            mime="application/pdf",
            use_container_width=True,
        )
