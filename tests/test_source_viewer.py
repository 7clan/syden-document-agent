"""Source controls show exact indexed locations without trusting generated paths."""
import json

from syden_agent.db import connect
from syden_agent.source_viewer import local_pdf_page, source_detail


def test_source_detail_resolves_pdf_word_and_excel_locations():
    conn = connect(":memory:")
    for name, kind in (("Report.pdf", "pdf"), ("Minutes.docx", "docx"),
                       ("Schedule.xlsx", "xlsx")):
        conn.execute("INSERT INTO documents(path,kind,status) VALUES(?,?,'ready')",
                     (name, kind))
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,2,0,'Inspection passed.')")
    conn.execute("INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
                 "VALUES(2,3,'paragraph','paragraph 3','Acceptance','Sign by Friday.')")
    cells = {"A": {"value": "M-01"}, "B": {"value": "2027-03-31"},
             "C": {"value": "Approved"}}
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES(3,'Milestones',4,?)", (json.dumps(cells),))
    pdf = source_detail(conn, "Report.pdf | page 2 | chunk 0")
    word = source_detail(conn, "Minutes.docx | paragraph 3")
    excel = source_detail(conn, "Schedule.xlsx | Milestones | row 4")
    assert pdf["evidence"]["text"] == "Inspection passed."
    assert word["evidence"]["section"] == "Acceptance"
    assert excel["evidence"]["row"] == {"A": "M-01", "B": "2027-03-31",
                                           "C": "Approved"}
    assert "error" in source_detail(conn, "Report.pdf | page 9 | chunk 0")
    assert "error" in source_detail(conn, "Schedule.xlsx | document")


def test_local_pdf_page_stays_inside_indexed_folder(tmp_path):
    conn = connect(":memory:")
    conn.execute("INSERT INTO metadata(key,value) VALUES('active_folder',?)",
                 (str(tmp_path),))
    (tmp_path / "Report.pdf").write_bytes(b"%PDF test")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Report.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(1,2,0,'Page two')")
    assert local_pdf_page(conn, "Report.pdf | page 2 | chunk 0") == (
        (tmp_path / "Report.pdf").resolve(), 2)
    assert local_pdf_page(conn, "../other.pdf | page 2 | chunk 0") is None
