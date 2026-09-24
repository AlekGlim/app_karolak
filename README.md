# Hipoteka AI — analiza umowy deweloperskiej

Aplikacja Streamlit dla analityków hipotecznych: OCR dokumentu, ekstrakcja
danych przez LLM, porównanie z danymi wniosku z UniFlow i szukajka w dokumencie.

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

Numer wniosku: `KHB1553044`, dokument: `dev/umowa_demo.pdf`.

## Struktura

| Katalog / plik   | Zawartość                                                          |
|------------------|--------------------------------------------------------------------|
| `app.py`         | widoki Streamlit                                                   |
| `stan.py`        | stan sesji — analiza przypisana do pary (dokument, numer wniosku)  |
| `ustawienia.py`  | adresy, ścieżki, limity czasu (nadpisywalne zmiennymi środowiska)  |
| `core/`          | czysta logika bez Streamlita: szukanie, daty, kwoty, walidacje     |
| `services/`      | hurtownia, API, przebieg analizy, tryb offline                     |
| `schemy/`        | schematy ekstrakcji                                                |
| `dev/`           | dane do trybu offline                                              |
| `tests/`         | testy pytest                                                       |

## Testy

```
pip install -r requirements-dev.txt
pytest
```
