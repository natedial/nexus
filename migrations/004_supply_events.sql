-- Supply calendar events for dispatcher reports (optional external data)

CREATE TABLE IF NOT EXISTS supply_events (
    id BIGSERIAL PRIMARY KEY,
    event_date DATE,
    time_ny TEXT,
    description TEXT,
    size_bn NUMERIC,
    maturity TEXT,
    country TEXT
);

CREATE INDEX IF NOT EXISTS idx_supply_events_event_date ON supply_events(event_date);
CREATE INDEX IF NOT EXISTS idx_supply_events_country ON supply_events(country);
