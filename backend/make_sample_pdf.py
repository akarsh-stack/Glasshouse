"""Generate samples/meridian-release-notes.pdf.

A committed binary PDF would be opaque; this script makes the fixture
reproducible and reviewable. It writes a minimal but fully valid PDF with a
real text stream, so the pypdf extraction path in loaders/pdf.py is exercised
by genuine PDF parsing rather than a doctored file.
"""

from pathlib import Path

LINES = [
    "Meridian Compiler Toolchain - Release Notes 4.2",
    "",
    "Build reproducibility",
    "",
    "Identical inputs now produce byte-identical artifacts. The build ID is",
    "derived from a hash of the source tree rather than from the wall clock,",
    "so two machines building the same commit agree bit for bit.",
    "",
    "Incremental linking",
    "",
    "Link times on the reference workload dropped from 41 seconds to 6",
    "seconds by caching relocation tables between builds. The cache is keyed",
    "on object file content hashes and lives under .meridian/linkcache.",
    "",
    "Diagnostics",
    "",
    "Error messages now include the inferred type of every subexpression in a",
    "failing template instantiation, instead of only the outermost type.",
    "",
    "Known limitations",
    "",
    "The new linker cannot yet emit split debug information on 32-bit",
    "targets. Use the legacy linker with the --split-debug flag there.",
]


def build_pdf() -> bytes:
    content = "BT /F1 11 Tf 54 742 Td 15 TL\n"
    for line in LINES:
        # Parentheses and backslashes are PDF string delimiters; the fixture
        # text avoids them, but strip defensively so an edit above can't
        # silently produce a corrupt file.
        safe = line.replace("\\", "").replace("(", "").replace(")", "")
        content += "({}) Tj T*\n".format(safe)
    content += "ET"
    stream = content.encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"

    xref = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref).encode() + b"\n%%EOF\n"
    )
    return out


if __name__ == "__main__":
    path = Path(__file__).parent.parent / "samples" / "meridian-release-notes.pdf"
    data = build_pdf()
    path.write_bytes(data)
    print(f"wrote {path} ({len(data)} bytes)")

    from pypdf import PdfReader

    text = PdfReader(str(path)).pages[0].extract_text()
    print(f"pypdf extracted {len(text)} chars from {len(PdfReader(str(path)).pages)} page(s)")
    print(text[:200])
