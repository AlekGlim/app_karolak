"""Generuje dane dokumentu do trybu offline, zgodne z dev/wynik_umowa_deweloperska.json:

  umowa_demo.pdf           PDF z warstwą tekstową (fraza zaznaczana na stronie)
  umowa_demo_skan.pdf      ten sam dokument jako skan — same obrazy, bez tekstu
  ocr_umowa_demo_skan.txt  odpowiedź endpointu OCR dla skanu: markdown
                           prebuilt-layout z tabelą, komentarzami stron i łamaniem
                           linii, z < i > zamienionymi na encje (jak zwraca endpoint)

Celowo zawiera rozbieżności, żeby w trybie offline było co oglądać:
  - druga data zawarcia umowy (15 marca 2026 obok 14 marca 2026)
  - numer księgi wieczystej z literą O zamiast zera (typowa pomyłka OCR)
  - nabywca 2 jako "Maria Nowak", a we wniosku "Maria Kowalska"

Uruchomienie (wymaga reportlab): python dev/generuj_umowe_demo.py
"""

import html
import textwrap
from pathlib import Path

import pypdfium2 as pdfium
from reportlab.lib import colors

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CZCIONKA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CZCIONKA_POGRUBIONA = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

STRONY = [
    [
        ("tytul", "Repertorium A Nr 1123/2026"),
        ("tytul", "AKT NOTARIALNY"),
        ("tekst", "Dnia czternastego marca dwa tysiące dwudziestego szóstego roku "
                  "(14 marca 2026 r.) przed notariuszem Janem Przykładowym w Kancelarii "
                  "Notarialnej w Warszawie stawili się:"),
        ("tekst", "1. Piotr Zarządca, działający w imieniu spółki XYZ Development spółka "
                  "z ograniczoną odpowiedzialnością z siedzibą w Warszawie, NIP 5252525252, "
                  "zwanej dalej „Deweloperem”,"),
        ("tekst", "2. Adam Nowak, PESEL 89052112345,"),
        ("tekst", "3. Maria Nowak, PESEL 92081534567, zwani dalej łącznie „Nabywcami”."),
        ("tytul", "UMOWA DEWELOPERSKA"),
        ("tekst", "§ 1. Deweloper oświadcza, że jest właścicielem nieruchomości gruntowej "
                  "położonej w Warszawie przy ulicy Puławskiej, stanowiącej działkę "
                  "ewidencyjną nr 12/5, dla której Sąd Rejonowy dla Warszawy-Mokotowa "
                  "prowadzi księgę wieczystą nr WA1M/00123456/7."),
        ("tekst", "Na nieruchomości Deweloper realizuje przedsięwzięcie deweloperskie "
                  "polegające na budowie budynku mieszkalnego wielorodzinnego z garażem "
                  "podziemnym."),
    ],
    [
        ("tekst", "§ 2. Przedmiotem umowy jest lokal mieszkalny nr 42 w budynku przy "
                  "ul. Puławskiej 17B w Warszawie, o powierzchni użytkowej 58,40 m², "
                  "składający się z trzech pokoi, kuchni, łazienki i przedpokoju."),
        ("tekst", "Wraz z lokalem Nabywcy nabędą udział w lokalu niemieszkalnym — garażu "
                  "wielostanowiskowym, z prawem do wyłącznego korzystania z miejsca "
                  "postojowego oznaczonego MLAC/G26, dla którego zostanie założona księga "
                  "wieczysta nr WA1M/00654321/3."),
        ("tekst", "§ 3. Cena lokalu mieszkalnego wynosi 685 000,00 zł. Cena udziału "
                  "w garażu wielostanowiskowym wynosi 35 000,00 zł. Łączna wartość "
                  "transakcji wynosi 720 000,00 zł."),
        ("tekst", "§ 4. Nabywcy zapłacą cenę w transzach, zgodnie z harmonogramem:"),
        ("tabela", [
            ["Transza", "Kwota", "Termin płatności"],
            ["1", "144 000,00 zł", "21-03-2026"],
            ["2", "216 000,00 zł", "15.08.2026"],
            ["3", "216 000,00 zł", "10.02.2027"],
            ["4", "144 000,00 zł", "30-06-2027"],
        ]),
        ("tekst", "Wpłaty nastąpią na otwarty mieszkaniowy rachunek powierniczy "
                  "prowadzony przez Bank Powierniczy S.A. o numerze "
                  "03 1090 1234 0000 0001 2345 1234, na indywidualny numer rachunku "
                  "19 1090 1234 0000 0001 9876 5432."),
    ],
    [
        ("tekst", "§ 5. Deweloper zobowiązuje się do ustanowienia odrębnej własności "
                  "lokalu do dnia 31-03-2027 oraz przeniesienia jej na Nabywców do dnia "
                  "30 czerwca 2027 r."),
        ("tekst", "§ 6. Nieruchomość objęta księgą wieczystą WA1M/0O123456/7 jest "
                  "obciążona hipoteką na rzecz banku finansującego przedsięwzięcie; "
                  "bank wyraził zgodę na bezobciążeniowe wyodrębnienie lokalu."),
        ("tekst", "§ 7. Nabywcy, Adam Nowak oraz Maria Nowak, oświadczają, że zapoznali "
                  "się z prospektem informacyjnym."),
        ("tekst", "Umowę sporządzono i podpisano w Warszawie dnia 15 marca 2026 r."),
    ],
]


def zbuduj_pdf(sciezka):
    pdfmetrics.registerFont(TTFont("DejaVu", CZCIONKA))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", CZCIONKA_POGRUBIONA))

    style = {
        "tytul": ParagraphStyle("tytul", fontName="DejaVu-Bold", fontSize=13,
                                leading=18, alignment=1, spaceAfter=10),
        "tekst": ParagraphStyle("tekst", fontName="DejaVu", fontSize=11,
                                leading=16, spaceAfter=10),
    }

    elementy = []
    for numer, strona in enumerate(STRONY):
        if numer:
            elementy.append(PageBreak())
        for rodzaj, tresc in strona:
            if rodzaj == "tabela":
                tabela = Table(tresc, colWidths=[2.5 * cm, 4.5 * cm, 4.5 * cm])
                tabela.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
                    ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                elementy.append(tabela)
                elementy.append(Spacer(1, 0.4 * cm))
            else:
                elementy.append(Paragraph(tresc, style[rodzaj]))
        elementy.append(Spacer(1, 0.5 * cm))

    SimpleDocTemplate(
        str(sciezka), pagesize=A4, title="Umowa deweloperska — demo",
        leftMargin=2.5 * cm, rightMargin=2.5 * cm, topMargin=2.5 * cm, bottomMargin=2.5 * cm,
    ).build(elementy)


def zbuduj_skan(sciezka_pdf, sciezka_skanu):
    """Każda strona jako obraz w skali szarości — PDF bez warstwy tekstowej."""
    dokument = pdfium.PdfDocument(str(sciezka_pdf))
    strony = [
        dokument[i].render(scale=1.6).to_pil().convert("L")
        for i in range(len(dokument))
    ]
    dokument.close()

    strony[0].save(
        sciezka_skanu, format="PDF", save_all=True, append_images=strony[1:],
        resolution=115, quality=70,
    )


def tekst_ocr():
    """Tekst w formacie endpointu OCR (prebuilt-layout, markdown).

    Akapity łamane jak linie na stronie, tabela jako HTML, nagłówek i numer
    strony jako komentarze — a na końcu < i > zamienione na encje, bo tak
    tekst przychodzi z endpointu (core.tekst dzieli strony po &lt;!-- PageBreak --&gt;).
    """
    strony = []
    for numer, strona in enumerate(STRONY, start=1):
        czesci = ['<!-- PageHeader="Kancelaria Notarialna — Repertorium A Nr 1123/2026" -->']
        for rodzaj, tresc in strona:
            if rodzaj == "tytul":
                czesci.append(f"# {tresc}")
            elif rodzaj == "tekst":
                czesci.append("\n".join(textwrap.wrap(tresc, 78)))
            else:
                naglowek, *wiersze = tresc
                czesci.append(
                    "<table>\n<tr>" + "".join(f"<th>{k}</th>" for k in naglowek) + "</tr>\n"
                    + "\n".join("<tr>" + "".join(f"<td>{k}</td>" for k in w) + "</tr>" for w in wiersze)
                    + "\n</table>"
                )
        czesci.append(f'<!-- PageNumber="{numer}" -->')
        strony.append("\n\n".join(czesci))

    return html.escape("\n<!-- PageBreak -->\n".join(strony), quote=False)


def main():
    katalog = Path(__file__).parent
    zbuduj_pdf(katalog / "umowa_demo.pdf")
    zbuduj_skan(katalog / "umowa_demo.pdf", katalog / "umowa_demo_skan.pdf")
    (katalog / "ocr_umowa_demo_skan.txt").write_text(tekst_ocr(), encoding="utf-8")
    print("Zapisano umowa_demo.pdf, umowa_demo_skan.pdf, ocr_umowa_demo_skan.txt")


if __name__ == "__main__":
    main()
