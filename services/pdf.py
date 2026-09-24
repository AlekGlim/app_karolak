"""Odczyt PDF: liczba stron, słowa z pozycjami (warstwa tekstowa), obraz strony.

pdfplumber jest opcjonalny: bez niego (albo dla skanu bez warstwy tekstowej)
szukajka działa na tekście OCR i wskazuje stronę, ale nie podświetla frazy.
"""

import io

import pypdfium2 as pdfium

try:
    import pdfplumber
    MA_WARSTWE_TEKSTOWA = True
except ImportError:
    pdfplumber = None
    MA_WARSTWE_TEKSTOWA = False


def liczba_stron(plik_bajty):
    dokument = pdfium.PdfDocument(plik_bajty)
    try:
        return len(dokument)
    finally:
        dokument.close()


def slowa_stron(plik_bajty):
    """Lista stron, każda jako lista słów {"text", "x0", "x1", "top", "bottom"}.

    Współrzędne w punktach PDF, początek w lewym górnym rogu. Strona skanu
    daje pustą listę.
    """
    if not MA_WARSTWE_TEKSTOWA:
        return []

    strony = []
    with pdfplumber.open(io.BytesIO(plik_bajty)) as pdf:
        for strona in pdf.pages:
            strony.append([
                {k: s[k] for k in ("text", "x0", "x1", "top", "bottom")}
                for s in strona.extract_words(use_text_flow=True)
            ])
    return strony


def renderuj_strone(plik_bajty, numer_strony, skala):
    """Obraz strony (PIL, RGBA); numer_strony od 1."""
    dokument = pdfium.PdfDocument(plik_bajty)
    try:
        return dokument[numer_strony - 1].render(scale=skala).to_pil().convert("RGBA")
    finally:
        dokument.close()
