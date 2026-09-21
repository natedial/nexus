# Research relay sanitization requirements

Date: 2026-09-20

Privacy boundary for the Gmail → Proton relay. Downstream packages must never
see the original private message or unsanitized attachment metadata.

## Requirements

1. **No original RFC822 forward** — rebuild a new message; never attach `.eml`.
2. **Transport header stripping** — drop `Received`, `Delivered-To`, Gmail
   transport headers, threading headers, and `X-Google-*` / `X-Gmail-*`.
3. **Private address redaction** — redact the configured private Gmail address
   from subject, body, sender attribution, and filenames.
4. **Quoted-history removal** — strip reply/forward quote blocks from the body.
5. **Subject cleanup** — normalize `Re:` / `Fwd:` prefixes after redaction.
6. **Filename sanitization** — basename only, path traversal removed, unsafe
   characters replaced, private address redacted from names.
7. **Attachment type and size policy** — allow/block lists and byte limits;
   prohibited types are skipped or quarantined per config.
8. **Attachment document-metadata scrubbing (fail-closed)** — before an allowed
   attachment is copied into the reconstructed message or archived to Drive,
   strip embedded document metadata. If scrubbing is required and fails, the
   attachment is not forwarded (skipped or quarantined per `on_prohibited`).
   Scrub targets:
   - PDF: document info dictionary (author, title, subject, creator, producer,
     keywords, comments)
   - Raster images: EXIF and other metadata segments (JPEG, PNG, WebP, GIF, TIFF)
   - Office Open XML (`.docx`, `.xlsx`, `.pptx`): remove `docProps/*` entries
9. **Downstream handoff artifact (R2/R3)** — relay ledger key, content hash,
   sanitized body, attachment manifest (PDF or HTML-only archive). Parser intake
   adapter consumes handoff bundles from a shared directory.

## Implementation map

| Item | Module | Status |
| --- | --- | --- |
| 1–2 | `reconstruct.py` | done |
| 3 | `redact.py` | done |
| 4 | `quotes.py` | done |
| 5 | `subject.py` | done |
| 6 | `attachments.py` | done |
| 7 | `attachments.py` | done |
| 8 | `metadata_scrub.py` | **R1** |
| 9 | parser intake adapter | **R2/R3** (`intake_contract.py`, `intake_handoff.py`, parser `src/intake/`) |

## Fail-closed rule (item 8)

If an attachment type can carry embedded metadata and scrubbing is not
supported or raises an error, the attachment must not be included in the
outgoing message. The relay run records a skip/quarantine note; it does not
fall back to the original bytes.

Plain-text formats without embedded file metadata (`.txt`, `.csv`, `.md`) pass
through unchanged.
