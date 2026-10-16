"""XP/Rico "consulta de notas" layout — synthetic PDF built in the test.

The real layout differs from the SINACOR note in ways that broke the B3 parser:
"Nº Nota" header with values on the line below, a "Negociações" section, a
"Quantidade Total ... Preço Médio" summary row after each security, the
security name and the fee values printed on a slightly different baseline than
the rest of their row, and continuation pages without the note header.
"""
import io
from datetime import date
from decimal import Decimal

import fitz

from correpy.domain.enums import TransactionType
from correpy.parsers.brokerage_notes.parser_factory import ParserFactory
from correpy.parsers.brokerage_notes.xp_consulta_parser.xp_consulta import XpConsultaParser

BASELINE_SHIFT = 1.5


def _cabecalho(page: fitz.Page) -> None:
    page.insert_text((440, 40), "Nota de Negociação", fontsize=8)
    page.insert_text((463, 55), "Data da Consulta: 01/02/2026 10:00", fontsize=6)
    page.insert_text((440, 167), "Data pregão", fontsize=7)
    page.insert_text((510, 167), "Nº Nota", fontsize=7)
    page.insert_text((440, 181), "05/01/2026", fontsize=7)
    page.insert_text((501, 181), "123456", fontsize=7)


def _negocio(page: fitz.Page, y: float, cv: str, mercado: str, nome: str, qtd: str, preco: str, valor: str) -> None:
    page.insert_text((20, y), "1-BOVESPA", fontsize=7)
    page.insert_text((75, y), cv, fontsize=7)
    page.insert_text((85, y), mercado, fontsize=7)
    page.insert_text((160, y + BASELINE_SHIFT), f"{nome} @", fontsize=7)
    page.insert_text((360, y), qtd, fontsize=7)
    page.insert_text((410, y), preco, fontsize=7)
    page.insert_text((500, y), valor, fontsize=7)
    page.insert_text((549, y), "D" if cv == "C" else "C", fontsize=7)


def _taxa(page: fitz.Page, y: float, rotulo: str, valor: str) -> None:
    page.insert_text((303, y), rotulo, fontsize=7)
    page.insert_text((514, y + BASELINE_SHIFT), valor, fontsize=7)


def _consulta_pdf() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page(width=596, height=842)
    _cabecalho(p1)
    p1.insert_text((273, 277), "Negociações", fontsize=7)
    p1.insert_text((20, 300), "Q Negociação C/V Tipo mercado Especificação do título Quantidade", fontsize=6)
    _negocio(p1, 320, "C", "VISTA", "PAPEL TESTE PAPE3 ON NM", "10", "20,00", "200,00")
    _negocio(p1, 334, "C", "VISTA", "PAPEL TESTE PAPE3 ON NM", "5", "21,00", "105,00")
    p1.insert_text((150, 348), "PAPEL TESTE PAPE3 ON NM Quantidade Total: 15 Preço Médio: 20,3333", fontsize=7)
    _negocio(p1, 362, "V", "FRACIONARIO", "OUTRO TESTE OUTR4F PN", "3", "9,50", "28,50")

    p2 = doc.new_page(width=596, height=842)  # continuation: no note header
    p2.insert_text((440, 40), "Nota de Negociação", fontsize=8)
    _negocio(p2, 220, "C", "VISTA", "FUNDO TESTE FUND11 CI", "2", "100,00", "200,00")
    p2.insert_text((300, 400), "Resumo Financeiro", fontsize=7)
    _taxa(p2, 420, "Taxa de liquidação", "0,13")
    _taxa(p2, 434, "Emolumentos", "0,03")
    _taxa(p2, 448, "I.R.R.F. s/ operações, base R$28,50", "0,00")
    p2.insert_text((303, 470), "Líquido para 07/01/2026", fontsize=7)
    return doc.tobytes()


def test_factory_picks_the_consulta_parser():
    parser = ParserFactory(brokerage_note=io.BytesIO(_consulta_pdf())).get_parser()

    assert isinstance(parser, XpConsultaParser)


def test_reads_header_transactions_across_pages_and_fees():
    [note] = ParserFactory(brokerage_note=io.BytesIO(_consulta_pdf())).parse()

    assert (note.reference_id, note.reference_date) == (123456, date(2026, 1, 5))
    assert [
        (t.transaction_type, t.amount, t.unit_price, t.security.raw_name, t.market_type, t.debit_credit)
        for t in note.transactions
    ] == [
        (TransactionType.BUY, Decimal("10"), Decimal("20.00"), "PAPEL TESTE PAPE3 ON NM @", "VISTA", "D"),
        (TransactionType.BUY, Decimal("5"), Decimal("21.00"), "PAPEL TESTE PAPE3 ON NM @", "VISTA", "D"),
        (TransactionType.SELL, Decimal("3"), Decimal("9.50"), "OUTRO TESTE OUTR4F PN @", "FRACIONARIO", "C"),
        # Page 2 has no header: it continues the note of page 1.
        (TransactionType.BUY, Decimal("2"), Decimal("100.00"), "FUNDO TESTE FUND11 CI @", "VISTA", "D"),
    ]
    assert (note.settlement_fee, note.emoluments, note.irrf) == (Decimal("0.13"), Decimal("0.03"), Decimal("0"))


def test_summary_row_is_never_a_transaction_nor_part_of_a_name():
    [note] = ParserFactory(brokerage_note=io.BytesIO(_consulta_pdf())).parse()

    assert all("Quantidade Total" not in t.security.raw_name for t in note.transactions)
    assert len(note.transactions) == 4
