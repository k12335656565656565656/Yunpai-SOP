ALTER TABLE product_route
    ADD COLUMN font_profile TEXT NOT NULL DEFAULT 'standard'
    CHECK(font_profile IN ('standard', 'clear_large', 'large'));
