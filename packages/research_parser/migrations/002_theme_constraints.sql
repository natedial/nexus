-- Phase 3B: Schema constraints finalization
-- Add CHECK constraints after Phase 2 is locked

-- =============================================================================
-- Add CHECK constraint for relationship values
-- =============================================================================

ALTER TABLE research_theme_links
    DROP CONSTRAINT IF EXISTS chk_relationship_values;

ALTER TABLE research_theme_links
    ADD CONSTRAINT chk_relationship_values 
    CHECK (relationship IN ('drives', 'amplifies', 'contradicts', 'hedges', 'enables'));

-- =============================================================================
-- Add scope enum constraint (optional - uncomment if needed)
-- =============================================================================

-- ALTER TABLE research_themes
--     ADD CONSTRAINT chk_scope_values 
--     CHECK (scope IN ('Macro', 'Sector', 'Asset', 'Company', 'Policy', 'Positioning', 'Flows', 'Technical', 'Risk', 'Other'));

-- =============================================================================
-- Add classification enum constraint (optional - uncomment if needed)
-- =============================================================================

-- ALTER TABLE research_themes
--     ADD CONSTRAINT chk_classification_values 
--     CHECK (classification IN ('Opinion', 'Forecast', 'Description'));

-- =============================================================================
-- Add strength enum constraint (optional - uncomment if needed)
-- =============================================================================

-- ALTER TABLE research_themes
--     ADD CONSTRAINT chk_strength_values 
--     CHECK (strength IN ('Primary', 'Secondary', 'Peripheral'));

-- =============================================================================
-- Add confidence enum constraint (optional - uncomment if needed)
-- =============================================================================

-- ALTER TABLE research_themes
--     ADD CONSTRAINT chk_confidence_values 
--     CHECK (confidence IN ('High', 'Medium', 'Low'));
