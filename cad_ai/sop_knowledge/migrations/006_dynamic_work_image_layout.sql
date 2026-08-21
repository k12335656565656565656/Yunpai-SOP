ALTER TABLE route_step
ADD COLUMN work_image_slots INTEGER NOT NULL DEFAULT 3
    CHECK(work_image_slots BETWEEN 1 AND 6);

-- Existing routes keep enough slots for every already-bound image. Empty and
-- small-image routes move to the new three-slot default.
UPDATE route_step
SET work_image_slots = MIN(
    6,
    MAX(3, (SELECT COUNT(*) FROM step_media WHERE route_step_id = route_step.id))
);
