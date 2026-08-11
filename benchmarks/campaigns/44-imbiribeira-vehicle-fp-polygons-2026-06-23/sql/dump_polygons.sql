-- Dump the LIVE pile_zone_polygon for esp32_001 (baseline for Phase C).
-- Do NOT assume the camp-41 proposal; this is what prod actually runs today.
--   docker compose -p saira-prod -f services/docker-compose.prod.yml exec -T db \
--     psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -f - < dump_polygons.sql \
--     > ../data/current_polygons_live.json
SELECT COALESCE(pile_zone_polygon::text, 'null')
FROM cameras
WHERE device_id = 'esp32_001';
