-- seed.sql — minimal local fixtures for the walking skeleton.
-- Fictional/curated taxonomy rows only. No vendor data.

INSERT INTO services (slug, display_name, keyword_seeds, anzsic_code) VALUES
  ('plumbing',   'Plumbing',   '["{service} {city}","emergency {service} {city}","{service} near me"]', '3231'),
  ('electrical', 'Electrical', '["{service} {city}","emergency {service} {city}"]', '3232')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO locations (slug, country_code, admin1, locality, granularity, display_name, population) VALUES
  ('au-qld-brisbane', 'AU', 'QLD', 'Brisbane', 'city',   'Brisbane, QLD', 2568900),
  ('au-vic-richmond', 'AU', 'VIC', 'Richmond', 'suburb', 'Richmond, VIC', 28000),
  ('au-nsw-richmond', 'AU', 'NSW', 'Richmond', 'suburb', 'Richmond, NSW', 5000)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO markets (service_id, location_id, market_key)
SELECT s.id, l.id, s.slug || '@' || l.slug
FROM services s CROSS JOIN locations l
WHERE (s.slug, l.slug) IN (
  ('plumbing','au-qld-brisbane'),
  ('electrical','au-qld-brisbane'),
  ('plumbing','au-vic-richmond'),
  ('plumbing','au-nsw-richmond')
)
ON CONFLICT (service_id, location_id) DO NOTHING;
