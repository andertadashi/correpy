"""Nota de negociação exportada pela consulta de notas do site da XP/Rico.

O conteúdo é o da nota SINACOR, num layout diferente:

- o cabeçalho traz "Data pregão" e "Nº Nota" (não "Nr. nota"), com os valores
  na linha de baixo;
- a seção de negócios se chama "Negociações";
- cada papel ganha uma linha-resumo "Quantidade Total: N Preço Médio: X", sem
  coluna C/V, que não é negócio nem pedaço de nome;
- as páginas seguintes da mesma nota podem vir sem o cabeçalho.
"""
import re
from datetime import date, datetime
from typing import List, Optional

from fitz import TextPage

from correpy.domain.entities.brokerage_note import BrokerageNote
from correpy.domain.entities.transaction import Transaction
from correpy.parsers.brokerage_notes.b3_parser.b3_parser import B3Parser
from correpy.parsers.exceptions import ProblemParsingBrokerageNoteException
from correpy.utils import extract_value_from_line

_DATA_E_NUMERO = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d+)")
#: A coluna "Q Negociação" de uma linha de negócio: "1-BOVESPA".
_COLUNA_NEGOCIACAO = re.compile(r"^\d+-\S+$")


class XpConsultaParser(B3Parser):
    REFERENCE_NOTE_ID = "Nº Nota"
    TRANSACTIONS_SECTION_TITLE = "Negociações"
    #: Texto que só a consulta imprime; a nota SINACOR não o tem.
    CONSULTA_MARKER = "Data da Consulta"

    def __init__(self, *args, **kwargs) -> None:  # type:ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._nota_corrente: Optional[BrokerageNote] = None

    def _cabecalho(self, page: TextPage, page_number: int) -> Optional[tuple]:
        try:
            titulo_data = self.fitz_parser.search_and_extract_rectangle_from_text(
                page=page, text=self.REFERENCE_DATE_TITLE
            )
            titulo_nota = self.fitz_parser.search_and_extract_rectangle_from_text(
                page=page, text=self.REFERENCE_NOTE_ID
            )
        except ProblemParsingBrokerageNoteException:
            return None
        altura = titulo_nota.y1 - titulo_nota.y0
        palavras = [
            w
            for w in self.fitz_parser.words[page_number]
            if w.x0 >= titulo_data.x0 - 1 and titulo_nota.y1 <= w.y0 <= titulo_nota.y1 + 1.5 * altura
        ]
        linha = " ".join(w.value for w in sorted(palavras, key=lambda w: w.x0))
        achado = _DATA_E_NUMERO.search(linha)
        if achado is None:
            return None
        pregao: date = datetime.strptime(achado.group(1), "%d/%m/%Y").date()
        return int(achado.group(2)), pregao

    def _get_or_create_brokerage_note_by_page(self, page: TextPage, page_number: int) -> BrokerageNote:
        cabecalho = self._cabecalho(page, page_number)
        if cabecalho is None:
            # Página de continuação: a nota é a da página anterior.
            if self._nota_corrente is None:
                raise ProblemParsingBrokerageNoteException
            return self._nota_corrente
        numero, pregao = cabecalho
        if (nota := self.brokerage_notes.get((numero, pregao))) is None:
            nota = BrokerageNote(reference_id=numero, reference_date=pregao)
            self.brokerage_notes[(numero, pregao)] = nota
        self._nota_corrente = nota
        return nota

    def _linhas_de_negocio(self, page_number: int) -> List[str]:
        """Uma linha por negócio, montada pela FAIXA vertical da coluna
        "Q Negociação" ("1-BOVESPA"): na consulta o nome do papel sai numa
        altura um pouco diferente do resto da linha, e agrupar pela altura
        exata o separaria."""
        palavras = self.fitz_parser.words[page_number]
        fora = []
        for ancora in palavras:
            if not _COLUNA_NEGOCIACAO.match(ancora.value):
                continue
            na_faixa = [w for w in palavras if ancora.y0 <= (w.y0 + w.y1) / 2 <= ancora.y1]
            texto = " ".join(w.value for w in sorted(na_faixa, key=lambda w: w.x0))
            if self._has_transaction_type_column(line_array=texto.split(" ")):
                fora.append(texto)
        return fora

    def set_brokerage_note_transactions(self) -> None:
        for page_document in self.fitz_parser.document:  # type:ignore[union-attr]
            page = page_document.get_textpage()
            page_number = page_document.number
            try:
                nota = self._get_or_create_brokerage_note_by_page(page=page, page_number=page_number)
            except ProblemParsingBrokerageNoteException:
                continue
            for linha in self._linhas_de_negocio(page_number):
                transacao: Transaction = self._create_transaction(line=linha)
                nota.add_transaction(transaction=transacao)
        # As taxas releem as páginas desde o início.
        self._nota_corrente = None

    def set_brokerage_note_fees(self) -> None:
        """Mesmo mapa de taxas da nota SINACOR, lido pela FAIXA vertical de cada
        rótulo: o valor sai numa altura um pouco diferente do rótulo, e o
        agrupamento por altura exata os separaria."""
        for page_document in self.fitz_parser.document:  # type:ignore[union-attr]
            page = page_document.get_textpage()
            page_number = page_document.number
            try:
                nota = self._get_or_create_brokerage_note_by_page(page=page, page_number=page_number)
                self.fitz_parser.search_and_extract_rectangle_from_text(page=page, text=self.FINANCIAL_SUMMARY_TITLE)
            except ProblemParsingBrokerageNoteException:
                continue
            palavras = self.fitz_parser.words[page_number]
            for rotulo, tipo in self.financial_summary_header_mapper.items():
                for achado in page.search(rotulo):
                    faixa = achado.rect
                    valor = [
                        w
                        for w in palavras
                        if w.x0 > faixa.x1 and faixa.y0 <= (w.y0 + w.y1) / 2 <= faixa.y1
                    ]
                    texto = " ".join(w.value for w in sorted(valor, key=lambda w: w.x0))
                    nota.update_fee_from_fee_type(fee_type=tipo, fee_value=extract_value_from_line(line=texto))
                    break
