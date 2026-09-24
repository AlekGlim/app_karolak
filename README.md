# Hipoteka AI — analiza umowy deweloperskiej

Aplikacja Streamlit dla analityków hipotecznych: OCR dokumentu, ekstrakcja
danych przez LLM, porównanie z danymi wniosku z UniFlow i szukajka w dokumencie.

**Pełna instrukcja — uruchomienie, praca analityka, co jest w plikach i jak
wprowadzać zmiany: [docs/INSTRUKCJA.md](docs/INSTRUKCJA.md).**

## Uruchomienie

Na serwerze (hurtownia i API dostępne):

```
streamlit run app.py
```

Lokalnie, bez hurtowni — tryb offline. Dane wniosku i wynik ekstrakcji
pochodzą z katalogu `dev/`, OCR czyta warstwę tekstową wgranego PDF-a:

```
HIPOTEKA_OFFLINE=1 streamlit run app.py        # Windows: set HIPOTEKA_OFFLINE=1
```

Numer wniosku: `KHB1553044`, dokument: `dev/umowa_demo_skan.pdf` (skan, jak
większość prawdziwych umów) albo `dev/umowa_demo.pdf` (PDF z warstwą tekstową).

Przeniesienie na inny komputer mailem (same pliki `.txt`):
`python narzedzia/pakuj_do_txt.py`, a na miejscu `python ROZPAKUJ.py.txt` —
szczegóły w [docs/INSTRUKCJA.md](docs/INSTRUKCJA.md).

## Struktura

| Katalog / plik   | Zawartość                                                          |
|------------------|--------------------------------------------------------------------|
| `app.py`         | widoki Streamlit                                                   |
| `stan.py`        | stan sesji — analiza przypisana do pary (dokument, numer wniosku)  |
| `ustawienia.py`  | adresy, ścieżki, limity czasu (nadpisywalne zmiennymi środowiska)  |
| `core/`          | czysta logika bez Streamlita: szukanie, daty, kwoty, walidacje     |
| `services/`      | hurtownia, API, odczyt PDF, przebieg analizy, tryb offline         |
| `ui/`            | widoki wydzielone z app.py (panel dokumentu z szukajką)            |
| `schemy/`        | schematy ekstrakcji                                                |
| `dev/`           | dane do trybu offline                                              |
| `narzedzia/`     | paczka `.txt` do wysłania mailem i jej rozpakowanie                |
| `tests/`         | testy pytest                                                       |

## Szukajka

Większość dokumentów to skany, a endpoint OCR (prebuilt-layout) zwraca sam
tekst w markdownie, podzielony na strony, bez pozycji słów. Szukajka działa
więc na tekście OCR: fraza (wpisana albo z kliknięcia w wartość pola)
przełącza podgląd na stronę, na której występuje, a nad podglądem pokazuje
fragment tekstu z zaznaczonym trafieniem. Znaczniki markdown i tabele
z odpowiedzi OCR są w tym fragmencie zamieniane na czytelny tekst.

Dla PDF-a z warstwą tekstową (wygenerowanego cyfrowo) trafienie jest
dodatkowo zaznaczone na obrazie strony — pozycje słów czyta `pdfplumber`.
Szukanie działa wtedy także przed analizą.

W trybie offline typowy przypadek to `dev/umowa_demo_skan.pdf`,
a `dev/umowa_demo.pdf` pokazuje wariant z warstwą tekstową.

## Testy

```
pip install -r requirements-dev.txt
pytest
```
