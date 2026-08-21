CREATE TABLE IF NOT EXISTS route_step_ie_item (
    id INTEGER PRIMARY KEY,
    route_step_id INTEGER NOT NULL REFERENCES route_step(id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL CHECK(sequence_no BETWEEN 1 AND 6),
    action TEXT NOT NULL,
    machine_type TEXT NOT NULL DEFAULT '',
    equipment_speed TEXT NOT NULL DEFAULT '',
    unit_price TEXT NOT NULL DEFAULT '',
    headcount TEXT NOT NULL DEFAULT '',
    standard_time TEXT NOT NULL DEFAULT '',
    allowance_rate TEXT NOT NULL DEFAULT '',
    standard_capacity TEXT NOT NULL DEFAULT '',
    time_source TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    review_state TEXT NOT NULL DEFAULT 'needs_revision'
        CHECK(review_state IN ('unreviewed','confirmed','rejected','needs_revision')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(route_step_id, sequence_no)
);

CREATE INDEX IF NOT EXISTS idx_route_step_ie_item_step
ON route_step_ie_item(route_step_id, sequence_no);
