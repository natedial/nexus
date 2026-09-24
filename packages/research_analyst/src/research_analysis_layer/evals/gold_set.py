"""Gold argument maps written from a co-reading session.

One record per document in `evals/golden/arguments.jsonl`, with the source text
in `evals/golden/documents/`. Records carry claim roles and author-stated links
between claims, which the older `annotations.jsonl` output eval does not.

    python -m research_analysis_layer.evals.gold_set register --document-id ... --text-file ...
    python -m research_analysis_layer.evals.gold_set put --file draft.json
    python -m research_analysis_layer.evals.gold_set show --document-id ...
    python -m research_analysis_layer.evals.gold_set list
    python -m research_analysis_layer.evals.gold_set validate
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ARGUMENTS_FILENAME = "arguments.jsonl"
DOCUMENTS_DIRNAME = "documents"
DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parents[3] / "evals" / "golden"

DOC_KINDS = (
    "note",
    "chart_pack",
    "speech",
    "paper",
    "statement",
    "minutes",
    "testimony",
    "other",
)
STATUSES = ("draft", "final")
ROLES = ("conclusion", "premise", "condition", "counterpoint")
CLAIM_TYPES = (
    "observation",
    "forecast",
    "causal",
    "market_impact",
    "policy",
    "risk",
    "recommendation",
)
SUPPORT_STRENGTHS = ("evidenced", "reasoned", "asserted")
EVIDENCE_KINDS = ("data", "quote", "citation", "chart", "prior_view")
PROPOSED_BY = ("annotator", "agent")
# Directed links read "from <type> to". contrasts_with has no direction.
DIRECTED_LINK_TYPES = ("supports", "depends_on", "qualifies", "leads_to", "answers")
SYMMETRIC_LINK_TYPES = ("contrasts_with",)
LINK_TYPES = DIRECTED_LINK_TYPES + SYMMETRIC_LINK_TYPES

_DOCUMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,80}$")
_CLAIM_ID_RE = re.compile(r"^c[0-9]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MIN_QUOTE_CHARS = 12


class GoldSetError(ValueError):
    """A record that cannot be stored."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _match_text(value: str) -> str:
    """Letters and digits only, so PDF line breaks and hyphenation do not block a quote."""
    return re.sub(r"[^0-9a-z]+", "", value.casefold())


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_choice(errors: list[str], where: str, value: Any, choices: tuple[str, ...]) -> None:
    if value not in choices:
        errors.append(f"{where}: {value!r} is not one of {', '.join(choices)}")


def validate_record(
    record: dict[str, Any],
    *,
    document_text: str | None,
) -> tuple[list[str], list[str]]:
    """Return (errors, completeness issues).

    Errors always block a write. Completeness issues are warnings on a draft and
    block a record marked final.
    """
    errors: list[str] = []
    incomplete: list[str] = []

    document_id = record.get("document_id")
    if not isinstance(document_id, str) or not _DOCUMENT_ID_RE.match(document_id):
        errors.append(
            "document_id must be lowercase letters, digits, '.', '_' or '-' (3-81 chars)"
        )
    if record.get("document_path") != f"{DOCUMENTS_DIRNAME}/{document_id}.md":
        errors.append(f"document_path must be {DOCUMENTS_DIRNAME}/{document_id}.md")
    _check_choice(errors, "status", record.get("status"), STATUSES)

    document = record.get("document")
    if not isinstance(document, dict):
        errors.append("document must be an object")
        document = {}
    if not (_is_text(document.get("publisher")) or _is_text(document.get("speaker"))):
        errors.append("document needs a publisher or a speaker")
    source_date = document.get("source_date")
    if source_date is not None and not (
        isinstance(source_date, str) and _DATE_RE.match(source_date)
    ):
        errors.append("document.source_date must be YYYY-MM-DD")
    if source_date is None:
        incomplete.append("document.source_date is missing")
    _check_choice(errors, "document.doc_kind", document.get("doc_kind"), DOC_KINDS)

    if document_text is None:
        errors.append(f"document text not found at {record.get('document_path')}")
    haystack = _match_text(document_text or "")

    claims = record.get("claims")
    if not isinstance(claims, list):
        errors.append("claims must be a list")
        claims = []
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims):
        where = f"claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{where} must be an object")
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not _CLAIM_ID_RE.match(claim_id):
            errors.append(f"{where}.id must look like c1, c2, ...")
        elif claim_id in claim_ids:
            errors.append(f"{where}.id {claim_id} is used twice")
        else:
            claim_ids.add(claim_id)
            where = claim_id
        if not _is_text(claim.get("claim")):
            errors.append(f"{where}.claim is empty")
        _check_choice(errors, f"{where}.role", claim.get("role"), ROLES)
        if claim.get("claim_type") is not None:
            _check_choice(errors, f"{where}.claim_type", claim.get("claim_type"), CLAIM_TYPES)
        _check_choice(
            errors,
            f"{where}.support_strength",
            claim.get("support_strength"),
            SUPPORT_STRENGTHS,
        )
        _check_choice(
            errors, f"{where}.proposed_by", claim.get("proposed_by", "annotator"), PROPOSED_BY
        )
        if not _is_text(claim.get("rationale")):
            incomplete.append(f"{where}.rationale is empty")
        conditions = claim.get("conditions", [])
        if not isinstance(conditions, list) or not all(_is_text(c) for c in conditions):
            errors.append(f"{where}.conditions must be a list of strings")

        evidence = claim.get("evidence", [])
        if not isinstance(evidence, list):
            errors.append(f"{where}.evidence must be a list")
            evidence = []
        for ev_index, item in enumerate(evidence):
            ev_where = f"{where}.evidence[{ev_index}]"
            if not isinstance(item, dict):
                errors.append(f"{ev_where} must be an object")
                continue
            _check_choice(errors, f"{ev_where}.kind", item.get("kind", "quote"), EVIDENCE_KINDS)
            page = item.get("page")
            if page is not None and not (isinstance(page, int) and page > 0):
                errors.append(f"{ev_where}.page must be a positive integer")
            figure_key = item.get("figure_key")
            if figure_key is not None and not (
                isinstance(figure_key, str) and figure_key.startswith("figure:")
            ):
                errors.append(f"{ev_where}.figure_key must look like figure:<hash>")
            text = item.get("text")
            if not _is_text(text):
                errors.append(f"{ev_where}.text is empty")
                continue
            if figure_key:
                continue
            needle = _match_text(text)
            if len(needle) < _MIN_QUOTE_CHARS:
                errors.append(
                    f"{ev_where}.text is too short to locate; quote more of the passage"
                )
            elif document_text is not None and needle not in haystack:
                errors.append(f"{ev_where}.text is not a verbatim quote from the document")
        if claim.get("support_strength") == "evidenced" and not evidence:
            incomplete.append(f"{where} is marked evidenced but cites no evidence")

    links = record.get("links", [])
    if not isinstance(links, list):
        errors.append("links must be a list")
        links = []
    seen_links: set[tuple[str, str, str]] = set()
    for index, link in enumerate(links):
        where = f"links[{index}]"
        if not isinstance(link, dict):
            errors.append(f"{where} must be an object")
            continue
        source, target, link_type = link.get("from"), link.get("to"), link.get("type")
        _check_choice(errors, f"{where}.type", link_type, LINK_TYPES)
        for end, value in (("from", source), ("to", target)):
            if value not in claim_ids:
                errors.append(f"{where}.{end} {value!r} is not a claim id")
        if source == target:
            errors.append(f"{where} links a claim to itself")
        key = (str(source), str(target), str(link_type))
        if link_type in SYMMETRIC_LINK_TYPES:
            key = (min(key[0], key[1]), max(key[0], key[1]), key[2])
        if key in seen_links:
            errors.append(f"{where} repeats an existing link")
        seen_links.add(key)

    if record.get("status") == "final":
        if not claims:
            incomplete.append("a final record needs at least one claim")
        elif not any(
            isinstance(c, dict) and c.get("role") == "conclusion" for c in claims
        ):
            incomplete.append("a final record needs at least one conclusion")
    return errors, incomplete


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and store each contrasts_with link once, in claim-id order."""
    normalized = dict(record)
    normalized["schema_version"] = SCHEMA_VERSION
    normalized.setdefault("notes", "")
    claims = []
    for claim in normalized.get("claims") or []:
        if not isinstance(claim, dict):
            claims.append(claim)
            continue
        item = dict(claim)
        item.setdefault("claim_type", None)
        item.setdefault("stance", None)
        item.setdefault("horizon", None)
        item.setdefault("conditions", [])
        item.setdefault("evidence", [])
        item.setdefault("proposed_by", "annotator")
        item.setdefault("uncertain", False)
        item["evidence"] = [
            {"kind": "quote", "page": None, "figure_key": None, **ev}
            if isinstance(ev, dict)
            else ev
            for ev in item["evidence"]
        ]
        claims.append(item)
    normalized["claims"] = claims
    links = []
    for link in normalized.get("links") or []:
        if not isinstance(link, dict):
            links.append(link)
            continue
        item = {"rationale": "", "uncertain": False, **link}
        if item.get("type") in SYMMETRIC_LINK_TYPES:
            ends = sorted([str(item.get("from")), str(item.get("to"))], key=_claim_sort_key)
            item["from"], item["to"] = ends
        links.append(item)
    normalized["links"] = links
    return normalized


def _claim_sort_key(claim_id: str) -> tuple[int, str]:
    digits = claim_id[1:] if claim_id.startswith("c") else ""
    return (int(digits), claim_id) if digits.isdigit() else (sys.maxsize, claim_id)


def load_records(golden_path: Path = DEFAULT_GOLDEN_PATH) -> dict[str, dict[str, Any]]:
    path = golden_path / ARGUMENTS_FILENAME
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["document_id"]] = record
    return records


def _write_records(golden_path: Path, records: dict[str, dict[str, Any]]) -> None:
    path = golden_path / ARGUMENTS_FILENAME
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records.values()]
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    tmp.replace(path)


def _document_text(golden_path: Path, record: dict[str, Any]) -> str | None:
    rel = record.get("document_path")
    if not isinstance(rel, str):
        return None
    path = golden_path / rel
    return path.read_text(encoding="utf-8") if path.is_file() else None


def put_record(
    record: dict[str, Any],
    *,
    golden_path: Path = DEFAULT_GOLDEN_PATH,
    now: datetime | None = None,
) -> list[str]:
    """Validate and upsert one record by document_id. Returns completeness warnings."""
    normalized = normalize_record(record)
    errors, incomplete = validate_record(
        normalized, document_text=_document_text(golden_path, normalized)
    )
    if normalized.get("status") == "final":
        errors.extend(incomplete)
        incomplete = []
    if errors:
        raise GoldSetError(errors)
    normalized["annotated_at"] = (now or datetime.now(timezone.utc)).isoformat()
    records = load_records(golden_path)
    records[normalized["document_id"]] = normalized
    _write_records(golden_path, records)
    return incomplete


def register_document(
    *,
    document_id: str,
    text_file: Path,
    document: dict[str, Any],
    annotator: str = "",
    golden_path: Path = DEFAULT_GOLDEN_PATH,
    replace_text: bool = False,
) -> dict[str, Any]:
    """Copy the source text into the gold set and start a draft record."""
    if not _DOCUMENT_ID_RE.match(document_id):
        raise GoldSetError(["document_id must be lowercase letters, digits, '.', '_' or '-'"])
    if not text_file.is_file():
        raise GoldSetError([f"text file not found: {text_file}"])
    documents_dir = golden_path / DOCUMENTS_DIRNAME
    documents_dir.mkdir(parents=True, exist_ok=True)
    target = documents_dir / f"{document_id}.md"
    records = load_records(golden_path)
    if target.exists() and not replace_text:
        if document_id in records:
            return records[document_id]
        raise GoldSetError([f"{target} already exists; pass --replace-text to overwrite"])
    if document_id in records and not replace_text:
        raise GoldSetError([f"{document_id} is already registered"])
    shutil.copyfile(text_file, target)
    existing = records.get(document_id, {})
    record = {
        "document_id": document_id,
        "document_path": f"{DOCUMENTS_DIRNAME}/{document_id}.md",
        "document": {**existing.get("document", {}), **document},
        "status": existing.get("status", "draft"),
        "annotator": annotator or existing.get("annotator", ""),
        "notes": existing.get("notes", ""),
        "claims": existing.get("claims", []),
        "links": existing.get("links", []),
    }
    put_record(record, golden_path=golden_path)
    return load_records(golden_path)[document_id]


def summarize_record(record: dict[str, Any]) -> str:
    """Plain-language readback for the annotator to confirm."""
    document = record.get("document") or {}
    author = " / ".join(
        part for part in (document.get("speaker"), document.get("publisher")) if part
    )
    lines = [
        f"{record['document_id']} ({record.get('status')}): "
        f"{document.get('title') or 'untitled'}, {author}, {document.get('source_date') or 'no date'}"
    ]
    for claim in record.get("claims") or []:
        flags = []
        if claim.get("proposed_by") == "agent":
            flags.append("suggested by agent")
        if claim.get("uncertain"):
            flags.append("uncertain")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        horizon = f", horizon {claim['horizon']}" if claim.get("horizon") else ""
        lines.append(
            f"  {claim['id']} {claim.get('role')}, {claim.get('support_strength')}{horizon}: "
            f"{claim.get('claim')}{suffix}"
        )
        if claim.get("rationale"):
            lines.append(f"      because {claim['rationale']}")
        for item in claim.get("evidence") or []:
            where = f" (p.{item['page']})" if item.get("page") else ""
            lines.append(f"      evidence{where}: \"{item.get('text')}\"")
    for link in record.get("links") or []:
        arrow = "<->" if link.get("type") in SYMMETRIC_LINK_TYPES else "->"
        lines.append(f"  {link['from']} {arrow} {link['to']}: {link['type']}")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gold_set", description=__doc__.splitlines()[0])
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="Copy source text in and start a draft")
    register.add_argument("--document-id", required=True)
    register.add_argument("--text-file", type=Path, required=True)
    register.add_argument("--title", default="")
    register.add_argument("--publisher", default="")
    register.add_argument("--speaker", default="")
    register.add_argument("--date", dest="source_date", default=None)
    register.add_argument("--kind", dest="doc_kind", choices=DOC_KINDS, required=True)
    register.add_argument("--link", dest="source_link", default="")
    register.add_argument("--annotator", default="")
    register.add_argument("--replace-text", action="store_true")

    put = sub.add_parser("put", help="Validate and store a full record from JSON")
    put.add_argument("--file", type=Path, help="JSON file; reads stdin when omitted")

    show = sub.add_parser("show", help="Print a record and its plain-language readback")
    show.add_argument("--document-id", required=True)
    show.add_argument("--json", action="store_true")

    sub.add_parser("list", help="List gold documents and their status")
    sub.add_parser("validate", help="Validate every stored record")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    golden: Path = args.golden
    try:
        if args.command == "register":
            document = {
                key: value
                for key, value in {
                    "title": args.title,
                    "publisher": args.publisher,
                    "speaker": args.speaker,
                    "source_date": args.source_date,
                    "doc_kind": args.doc_kind,
                    "source_link": args.source_link,
                }.items()
                if value not in ("", None)
            }
            record = register_document(
                document_id=args.document_id,
                text_file=args.text_file,
                document=document,
                annotator=args.annotator,
                golden_path=golden,
                replace_text=args.replace_text,
            )
            print(summarize_record(record))
        elif args.command == "put":
            raw = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
            payload = json.loads(raw)
            warnings = put_record(payload, golden_path=golden)
            record = load_records(golden)[payload["document_id"]]
            print(summarize_record(record))
            for warning in warnings:
                print(f"still to do: {warning}")
        elif args.command == "show":
            record = load_records(golden).get(args.document_id)
            if record is None:
                print(f"{args.document_id} is not in the gold set", file=sys.stderr)
                return 1
            print(json.dumps(record, indent=2, ensure_ascii=False) if args.json else summarize_record(record))
        elif args.command == "list":
            for record in load_records(golden).values():
                document = record.get("document") or {}
                print(
                    f"{record['document_id']}\t{record.get('status')}\t"
                    f"{len(record.get('claims') or [])} claims\t{document.get('title', '')}"
                )
        elif args.command == "validate":
            failed = False
            for document_id, record in load_records(golden).items():
                errors, incomplete = validate_record(
                    record, document_text=_document_text(golden, record)
                )
                if record.get("status") == "final":
                    errors = errors + incomplete
                    incomplete = []
                for message in errors:
                    failed = True
                    print(f"{document_id}: {message}")
                for message in incomplete:
                    print(f"{document_id}: still to do: {message}")
            return 1 if failed else 0
    except GoldSetError as exc:
        for message in exc.errors:
            print(f"error: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
