# Hipoteka AI — analiza umowy deweloperskiej

Aplikacja Streamlit dla analityków hipotecznych: OCR dokumentu, ekstrakcja
danych przez LLM, porównanie z danymi wniosku z UniFlow i szukajka w dokumencie.

**Pełna instrukcja — uruchomienie, praca analityka, co jest w plikach i jak
wprowadzać zmiany: [docs/INSTRUKCJA.md](docs/INSTRUKCJA.md).**

Opis funkcjonalności i pomysły na rozwój: [docs/OPIS_FUNKCJONALNOSCI.md](docs/OPIS_FUNKCJONALNOSCI.md).

## Uruchomienie

Na serwerze (hurtownia i API dostępne):

```
streamlit run app.py
```

Lokalnie, bez hurtowni — tryb offline. Dane wniosku i wynik ekstrakcji
pochodzą z katalogu `dev/`, OCR czyta warstwę tekstową wgranego PDF-a:

```
HIPOTEKA_OFFLINE=1 streamlit run app.py        # PowerShell: $env:HIPOTEKA_OFFLINE="1"; streamlit run app.py
```

Numer wniosku: `KHB1553044`, dokument: `dev/umowa_demo_skan.pdf` (skan, jak
większość prawdziwych umów) albo `dev/umowa_demo.pdf` (PDF z warstwą tekstową).

Przeniesienie na inny komputer mailem (same pliki `.txt`):
`python kopiuj_do_wysylki.py` kopiuje potrzebne pliki do `paczka_wysylka/`
z końcówką `.txt`; na miejscu usuwa się tę końcówkę — szczegóły
w [docs/INSTRUKCJA.md](docs/INSTRUKCJA.md).

## Struktura

| Plik / katalog      | Zawartość                                                             |
|---------------------|-----------------------------------------------------------------------|
| `app.py`            | cała aplikacja, podzielona na sekcje z nagłówkami (spis na górze pliku) |
| `data_loader.py`    | hurtownia: dane wniosku z UniFlow i cache wyników (tylko serwer)     |
| `schemy/`           | schematy ekstrakcji                                                   |
| `.streamlit/`       | kolor akcentu kontrolek Streamlita (fioletowy)                        |
| `dev/`              | dane do trybu offline                                                 |
| `tests/`            | testy pytest                                                          |
| `kopiuj_do_wysylki.py` | kopia plików z końcówką `.txt` do wysłania mailem                  |

## Szukajka

Większość dokumentów to skany, a endpoint OCR (prebuilt-layout) zwraca sam
tekst w markdownie, podzielony na strony, bez pozycji słów. Szukajka działa
więc na tekście OCR: fraza (wpisana albo z kliknięcia w wartość pola)
przełącza podgląd na stronę, na której występuje, a nad podglądem pokazuje
fragment tekstu z zaznaczonym trafieniem. Znaczniki markdown i tabele
z odpowiedzi OCR są w tym fragmencie zamieniane na czytelny tekst.

Daty, kwoty i identyfikatory (PESEL, NIP, KW, rachunek) są szukane po znaczeniu,
nie po napisie: `2026-03-14` znajdzie `14 marca 2026`, a `WA1M/00123456/7`
znajdzie `WA1M 00123456 7`. Kolory trafień: niebieski — szukana wartość,
morski zielony — ta sama wartość w innym zapisie, czerwony — wartość niezgodna.

Obsługujemy wyłącznie wskazanie strony — na obrazie strony niczego nie
zaznaczamy, także dla PDF-a z warstwą tekstową. Szukanie działa po analizie.

## Testy

```
pip install -r requirements-dev.txt
pytest
```
