from datetime import UTC, datetime, timedelta

from research_gleaner.models import CapturedExcerpt, SourceDocumentRef, SourceLocator
from research_gleaner.pipeline import run_remarkable_capture
from research_gleaner.remarkable.client import RemarkableDocument
from research_gleaner.store import CaptureStore


class FakeLibrary:
    def __init__(self, documents):
        self.documents = documents
        self.downloaded = []

    def list_documents(self):
        return self.documents

    def file_type(self, document):
        return "pdf"

    def download(self, document):
        self.downloaded.append(document.document_id)
        return b"archive"


def document(document_id, revision, modified_at):
    return RemarkableDocument(
        document_id=document_id,
        revision=revision,
        title=f"Document {document_id}",
        path=f"/Research/Document {document_id}",
        modified_at=modified_at,
        raw=object(),
    )


def test_pipeline_downloads_only_recent_unprocessed_revisions(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    recent = document("recent", "rev-1", now)
    old = document("old", "rev-1", now - timedelta(days=3))
    library = FakeLibrary([recent, old])
    store = CaptureStore(tmp_path / "gleaner.db")

    def fake_extract(source, archive, *, routes=None):
        return [
            CapturedExcerpt.create(
                document=SourceDocumentRef(
                    source_kind="remarkable",
                    document_id=source.document_id,
                    uri="remarkable:///Research/Document",
                    title=source.title,
                ),
                locator=SourceLocator(page_number=1, annotation_id="annotation-1"),
                text="Useful evidence",
                context_text="Useful evidence",
                source_style="pink",
            )
        ]

    monkeypatch.setattr("research_gleaner.pipeline.extract_document", fake_extract)
    output = tmp_path / "captures.json"

    first = run_remarkable_capture(
        library,
        store,
        output,
        modified_since=now - timedelta(hours=24),
    )
    second = run_remarkable_capture(
        library,
        store,
        output,
        modified_since=now - timedelta(hours=24),
    )

    assert library.downloaded == ["recent"]
    assert len(first.captures) == 1
    assert second.captures == ()
    assert store.processed_revision("remarkable", "recent") == "rev-1:extractor-v3"
    assert store.processed_revision("remarkable", "old") is None
