import io
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from correpy.domain.entities.brokerage_note import BrokerageNote
from correpy.parsers.brokerage_notes.b3_parser.b3_parser import B3Parser
from correpy.parsers.brokerage_notes.xp_consulta_parser.xp_consulta import XpConsultaParser


class TestB3ParserFeesFromLines:
    """Since 2025-08-01 the "Bovespa" block of the note may print a
    "Taxa de Transf. de Ativos" line (B3's asset transfer fee). Values below
    are FABRICATED."""

    def setup_method(self):
        self.document_mock = MagicMock()
        self.document_mock.__iter__ = lambda _: iter([])
        self.patcher = patch("correpy.parsers.fitz_parser.fitz.open")
        fitz_open_mock = self.patcher.start()
        fitz_open_mock.return_value = self.document_mock
        self.parser = B3Parser(brokerage_note=io.BytesIO(b"fake-pdf"), password=None)
        self.note = BrokerageNote(reference_id=1, reference_date=date(2026, 1, 2))

    def teardown_method(self):
        self.patcher.stop()

    def _parse(self, line: str) -> None:
        with patch.object(B3Parser, "_get_or_create_brokerage_note_by_page", return_value=self.note):
            self.parser._B3Parser__parse_brokerage_note_fee_from_summary_line(  # type: ignore[attr-defined]
                financial_summary_line=line, page=MagicMock(), page_number=0
            )

    def test_WHEN_line_is_asset_transfer_fee_THEN_sets_asset_transfer_fee(self):
        self._parse("Taxa de Transf. de Ativos 0,23 D")

        assert self.note.asset_transfer_fee == Decimal("0.23")
        assert self.note.emoluments == Decimal("0")
        assert self.note.others == Decimal("0")

    def test_WHEN_xp_consulta_parser_THEN_reads_the_same_label(self):
        assert XpConsultaParser.financial_summary_header_mapper["Taxa de Transf. de Ativos"] == (
            B3Parser.financial_summary_header_mapper["Taxa de Transf. de Ativos"]
        )
