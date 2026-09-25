import io
from decimal import Decimal
from unittest.mock import MagicMock, patch

import fitz

from correpy.domain.enums import TransactionType
from correpy.parsers.brokerage_notes.b3_parser.b3_parser import B3Parser


class TestB3ParserTransactionsFromLines:
    """Some brokerage notes wrap the "Especificação do título" column onto
    its OWN physical line instead of printing the whole transaction row on
    one line — observed on a real note where FRACIONARIO (odd-lot) trades
    render that column at a slightly different baseline than the rest of
    the row, so `_group_words_by_line` splits it off. The fragment line has
    no C/V column: `__parse_transaction_amount` then indexes into a
    3-or-4-token list expecting position -4 and raises IndexError.

    All values below are FABRICATED — same shape as the real note, not its
    content.
    """

    def setup_method(self):
        self.document_mock = MagicMock()
        self.document_mock.__iter__ = lambda _: iter([])
        self.patcher = patch("correpy.parsers.fitz_parser.fitz.open")
        fitz_open_mock = self.patcher.start()
        fitz_open_mock.return_value = self.document_mock
        self.parser = B3Parser(brokerage_note=io.BytesIO(b"fake-pdf"), password=None)

    def teardown_method(self):
        self.patcher.stop()

    def test_WHEN_every_line_has_the_full_row_THEN_parses_one_transaction_per_line(self):
        # The common case (VISTA and most FRACIONARIO rows on other notes):
        # security name + numeric columns all on the SAME physical line.
        lines = [
            "1-BOVESPA C VISTA FAKECORP ON NM 100 10,00 1.000,00 D",
            "1-BOVESPA V VISTA OTHERCORP PN N1 50 20,00 1.000,00 C",
        ]

        transactions = self.parser._build_transactions_from_lines(lines=lines)

        assert len(transactions) == 2
        assert transactions[0].transaction_type == TransactionType.BUY
        assert transactions[0].amount == Decimal("100")
        assert transactions[0].unit_price == Decimal("10.00")
        assert transactions[0].security.name == "FAKECORP ON NM"
        assert transactions[1].transaction_type == TransactionType.SELL
        assert transactions[1].security.name == "OTHERCORP PN N1"

    def test_WHEN_security_name_is_wrapped_onto_its_own_line_THEN_merges_it_into_the_next_transaction(self):
        # The broken format: the name-only fragment line (no C/V column)
        # comes first, then the data line carries an extra "Obs.(*)" token
        # ("@" below, fabricated) where the name would otherwise sit.
        lines = [
            "FAKECORP ON NM",
            "1-BOVESPA C FRACIONARIO @ 2 38,80 77,60 D",
        ]

        transactions = self.parser._build_transactions_from_lines(lines=lines)

        assert len(transactions) == 1
        transaction = transactions[0]
        assert transaction.transaction_type == TransactionType.BUY
        assert transaction.amount == Decimal("2")
        assert transaction.unit_price == Decimal("38.80")
        assert transaction.security.name == "FAKECORP ON NM"
        assert transaction.market_type == "FRACIONARIO"
        assert transaction.debit_credit == "D"

    def test_WHEN_several_wrapped_transactions_in_a_row_THEN_each_merges_with_its_own_data_line(self):
        lines = [
            "FAKECORP ON NM",
            "1-BOVESPA C FRACIONARIO @ 2 38,80 77,60 D",
            "OTHERCORP PN N1",
            "1-BOVESPA C FRACIONARIO @ 4 10,93 43,72 D",
        ]

        transactions = self.parser._build_transactions_from_lines(lines=lines)

        assert [t.security.name for t in transactions] == ["FAKECORP ON NM", "OTHERCORP PN N1"]
        assert [t.amount for t in transactions] == [Decimal("2"), Decimal("4")]
        assert [t.unit_price for t in transactions] == [Decimal("38.80"), Decimal("10.93")]
