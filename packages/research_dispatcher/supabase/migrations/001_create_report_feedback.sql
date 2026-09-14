-- Create report_feedback table for storing user feedback on through-lines
CREATE TABLE IF NOT EXISTS report_feedback (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    doc_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('useful', 'flag')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for querying feedback by report
CREATE INDEX IF NOT EXISTS idx_feedback_doc ON report_feedback(doc_id);

-- Index for querying feedback by item (through-line)
CREATE INDEX IF NOT EXISTS idx_feedback_item ON report_feedback(item_id);

-- Comment on table
COMMENT ON TABLE report_feedback IS 'Stores user feedback on through-lines from PDF reports';
COMMENT ON COLUMN report_feedback.doc_id IS 'Report generation timestamp identifier';
COMMENT ON COLUMN report_feedback.item_id IS 'Hash of through-line lead text (first 8 chars of MD5)';
COMMENT ON COLUMN report_feedback.action IS 'Feedback action: useful or flag';
