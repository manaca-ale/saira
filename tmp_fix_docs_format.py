import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CRED_PATH = Path(r"C:\Users\aleco\.google_workspace_mcp\credentials\contato@manaca.tech.json")
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def get_text_from_paragraph(paragraph: Dict[str, Any]) -> str:
    parts: List[str] = []
    for el in paragraph.get("elements", []):
        tr = el.get("textRun")
        if tr:
            parts.append(tr.get("content", ""))
    return "".join(parts)


def get_paragraphs(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for el in doc.get("body", {}).get("content", []):
        if "paragraph" not in el:
            continue
        out.append(
            {
                "start": el.get("startIndex"),
                "end": el.get("endIndex"),
                "text": get_text_from_paragraph(el["paragraph"]),
            }
        )
    return out


def parse_table_rows(lines: List[str]) -> List[List[str]]:
    rows: List[List[str]] = []
    for raw in lines:
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Markdown separator row, e.g. |---|---| or |:---|---:|
        if cells and all(re.fullmatch(r"[:\- ]*", c or "") and "-" in c for c in cells):
            continue
        cleaned = [c.replace("`", "") for c in cells]
        rows.append(cleaned)

    if not rows:
        return []

    cols = max(len(r) for r in rows)
    if cols == 0:
        return []

    normalized = [r + [""] * (cols - len(r)) for r in rows]
    return normalized


def find_markdown_table_blocks(paragraphs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    i = 0
    n = len(paragraphs)
    in_code_fence = False
    while i < n:
        text = (paragraphs[i]["text"] or "").strip()

        if text.startswith("```"):
            in_code_fence = not in_code_fence
            i += 1
            continue

        if in_code_fence or not text.startswith("|"):
            i += 1
            continue

        start_i = i
        while i < n:
            row_text = (paragraphs[i]["text"] or "").strip()
            if row_text.startswith("```"):
                # Defensive stop if malformed markdown interleaves blocks.
                break
            if not row_text.startswith("|"):
                break
            i += 1
        end_i = i - 1

        lines = [(paragraphs[j]["text"] or "").strip() for j in range(start_i, end_i + 1)]
        rows = parse_table_rows(lines)
        if len(rows) >= 2 and len(rows[0]) >= 2:
            blocks.append(
                {
                    "start": paragraphs[start_i]["start"],
                    "end": paragraphs[end_i]["end"],
                    "rows": rows,
                    "raw_lines": lines,
                }
            )
    return blocks


def get_tables(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    tables = []
    for el in doc.get("body", {}).get("content", []):
        if "table" in el:
            tables.append(el)
    return tables


def find_best_table_for_index(doc: Dict[str, Any], index: int) -> Dict[str, Any]:
    tables = get_tables(doc)
    if not tables:
        raise RuntimeError("No table found after insertion")

    # Prefer tables at/after index, closest first.
    after = [t for t in tables if t.get("startIndex", -1) >= index]
    if after:
        return min(after, key=lambda t: t.get("startIndex", 0) - index)

    # Fallback to absolute nearest (should rarely happen)
    return min(tables, key=lambda t: abs(t.get("startIndex", 0) - index))


def get_cell_insert_index(cell: Dict[str, Any]) -> int:
    # New table cells contain one paragraph with one newline. Inserting at the
    # first paragraph element start index writes before that newline.
    for c in cell.get("content", []):
        p = c.get("paragraph")
        if not p:
            continue
        elems = p.get("elements", [])
        if not elems:
            continue
        return elems[0].get("startIndex")
    raise RuntimeError("Could not determine cell insertion index")


def batch_update(service, document_id: str, requests: List[Dict[str, Any]]) -> None:
    if not requests:
        return
    service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()


def convert_tables(service, document_id: str) -> int:
    doc = service.documents().get(documentId=document_id).execute()
    paragraphs = get_paragraphs(doc)
    blocks = find_markdown_table_blocks(paragraphs)

    if not blocks:
        print(f"[{document_id}] no markdown table blocks found")
        return 0

    print(f"[{document_id}] markdown table blocks found: {len(blocks)}")

    converted = 0
    # Process from bottom to top so earlier indices stay stable.
    for pos, block in enumerate(reversed(blocks), start=1):
        start = block["start"]
        end = block["end"]
        rows = block["rows"]
        rcount = len(rows)
        ccount = len(rows[0])

        # 1) Delete markdown table text block
        batch_update(
            service,
            document_id,
            [{"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}}],
        )

        # 2) Insert empty table at same location
        batch_update(
            service,
            document_id,
            [
                {
                    "insertTable": {
                        "rows": rcount,
                        "columns": ccount,
                        "location": {"index": start},
                    }
                }
            ],
        )

        # 3) Re-fetch and fill cells
        cur = service.documents().get(documentId=document_id).execute()
        table = find_best_table_for_index(cur, start)

        inserts: List[Tuple[int, str]] = []
        for r in range(rcount):
            for c in range(ccount):
                value = rows[r][c]
                if not value:
                    continue
                cell = table["table"]["tableRows"][r]["tableCells"][c]
                idx = get_cell_insert_index(cell)
                inserts.append((idx, value))

        # Insert in descending order of index to keep ranges stable.
        insert_reqs = [
            {"insertText": {"location": {"index": idx}, "text": txt}}
            for idx, txt in sorted(inserts, key=lambda x: x[0], reverse=True)
        ]
        for chunk in chunked(insert_reqs, 80):
            batch_update(service, document_id, chunk)

        # 4) Bold header row
        cur = service.documents().get(documentId=document_id).execute()
        table = find_best_table_for_index(cur, start)
        header_reqs: List[Dict[str, Any]] = []
        for c in range(ccount):
            header = rows[0][c]
            if not header:
                continue
            cell = table["table"]["tableRows"][0]["tableCells"][c]
            sidx = get_cell_insert_index(cell)
            eidx = sidx + len(header)
            header_reqs.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": sidx, "endIndex": eidx},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                }
            )
        if header_reqs:
            batch_update(service, document_id, header_reqs)

        converted += 1
        print(f"[{document_id}] converted table {pos}/{len(blocks)} ({rcount}x{ccount}) at {start}")

    return converted


def cleanup_markers_and_headings(service, document_id: str) -> Dict[str, int]:
    # Remove literal markdown bold markers.
    batch_update(
        service,
        document_id,
        [
            {
                "replaceAllText": {
                    "containsText": {"text": "**", "matchCase": True},
                    "replaceText": "",
                }
            }
        ],
    )

    doc = service.documents().get(documentId=document_id).execute()
    paragraphs = get_paragraphs(doc)

    h2_reqs: List[Dict[str, Any]] = []
    h3_reqs: List[Dict[str, Any]] = []
    etapa_bold_reqs: List[Dict[str, Any]] = []

    for p in paragraphs:
        text = (p["text"] or "").strip()
        if not text:
            continue

        # Main numbered sections -> Heading 2
        if re.match(r"^\d+\.\s+", text):
            h2_reqs.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": p["start"], "endIndex": p["end"]},
                        "paragraphStyle": {"namedStyleType": "HEADING_2"},
                        "fields": "namedStyleType",
                    }
                }
            )
            continue

        # Subsections like 2.1, 4.2, 7.1 -> Heading 3
        if re.match(r"^\d+\.\d+\s+", text):
            h3_reqs.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": p["start"], "endIndex": p["end"]},
                        "paragraphStyle": {"namedStyleType": "HEADING_3"},
                        "fields": "namedStyleType",
                    }
                }
            )
            continue

        # "Etapa X — ..." lines should be bold labels, not literal **
        if re.match(r"^Etapa\s+\d+\s+[—-]", text):
            end_no_newline = max(p["start"], p["end"] - 1)
            etapa_bold_reqs.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": p["start"], "endIndex": end_no_newline},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                }
            )

    for reqs in (h2_reqs, h3_reqs, etapa_bold_reqs):
        for chunk in chunked(reqs, 120):
            batch_update(service, document_id, chunk)

    return {
        "h2": len(h2_reqs),
        "h3": len(h3_reqs),
        "etapa_bold": len(etapa_bold_reqs),
    }


def process_doc(service, document_id: str) -> None:
    converted = convert_tables(service, document_id)
    stats = cleanup_markers_and_headings(service, document_id)
    print(
        f"[{document_id}] done | tables_converted={converted} | "
        f"h2={stats['h2']} h3={stats['h3']} etapa_bold={stats['etapa_bold']}"
    )


def main(argv: List[str]) -> int:
    if not CRED_PATH.exists():
        print(f"Credentials file not found: {CRED_PATH}", file=sys.stderr)
        return 1

    doc_ids = argv[1:]
    if not doc_ids:
        print("Usage: python fix_docs_format.py <DOC_ID> [<DOC_ID> ...]", file=sys.stderr)
        return 1

    creds = Credentials.from_authorized_user_file(str(CRED_PATH), SCOPES)
    service = build("docs", "v1", credentials=creds, cache_discovery=False)

    for doc_id in doc_ids:
        process_doc(service, doc_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
