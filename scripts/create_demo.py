"""Create nonconfidential, selectable-text demo documents with known answers."""
from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import Workbook


def _simple_pdf(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -22 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
         b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
               f"startxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(pdf)


def create_demo(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "Contract.pdf").write_bytes(_simple_pdf([
        "Scope of Work",
        "Contractor shall install two transformers and commission the plant.",
        "Deliverable: Submit design drawings by 15 November 2026.",
        "Exclusion: Civil excavation is excluded from this contract.",
    ]))
    boq = Workbook()
    sheet = boq.active
    sheet.title = "Electrical BOQ"
    sheet.append(["Item", "Description", "Total Amount (SAR)", "Unit Price"])
    sheet.append(["EL-01", "Transformers", 1_500_000, 50_000])
    sheet.append(["EL-02", "Cable", 1_000_000, 100])
    sheet.append(["EL-03", "Switchgear", 2_250_000, 75_000])
    boq.save(folder / "BOQ.xlsx")
    milestones = Workbook()
    sheet = milestones.active
    sheet.title = "Milestones"
    sheet.append(["Deliverable", "Due date"])
    sheet.append(["Commission plant", "2026-12-01"])
    sheet.append(["Review optional test", "03/04/26"])
    milestones.save(folder / "Milestones.xlsx")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", default=".local/demo_documents")
    options = parser.parse_args()
    create_demo(Path(options.folder))
    print(f"Created synthetic documents in {options.folder}")
