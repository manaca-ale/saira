-- Pull ALL esp32_001 (Imbiribeira) detections labeled by the operator.
-- Ground truth = detections.status: CONFIRMADO=TP, REJEITADO=FP, INDETERMINADO=ambiguous.
-- Run inside the prod `db` container (read-only), e.g.:
--   cat pull_esp32_001.sql | ssh saira-prod \
--     'docker exec -i saira-db-prod psql -U postgres -d saira_db -q -f -' > corpus_esp32_001.csv
-- DISTINCT ON (d.id) collapses the cascade_decisions LEFT JOIN to ONE row per detection
-- (prefer the confirming decision / highest agent1_confidence).
COPY (
  SELECT id, status, created_at, validity_comment, waste_bbox, image_url,
         confidence_score, agent1_confidence, offender_present, agent2_disposal,
         waste_type, volume_m3, logradouro
  FROM (
    SELECT DISTINCT ON (d.id)
      d.id::text                         AS id,
      d.status::text                     AS status,
      d.timestamp::text                  AS created_at,
      COALESCE(d.validity_comment, '')   AS validity_comment,
      COALESCE(d.waste_bbox::text, '')   AS waste_bbox,
      COALESCE(d.image_url, '')          AS image_url,
      d.confidence_score                 AS confidence_score,
      cd.agent1_confidence               AS agent1_confidence,
      cd.offender_present                AS offender_present,
      cd.agent2_disposal                 AS agent2_disposal,
      d.waste_type                       AS waste_type,
      d.volume_m3                        AS volume_m3,
      d.logradouro                       AS logradouro,
      d.timestamp                        AS ts
    FROM detections d
    JOIN cameras c ON c.id = d.camera_id
    LEFT JOIN cascade_decisions cd ON cd.detection_id = d.id
    WHERE c.device_id = 'esp32_001'
      AND d.status IN ('CONFIRMADO', 'REJEITADO', 'INDETERMINADO')
    ORDER BY d.id,
             (cd.detection_id IS NOT NULL) DESC,
             cd.agent1_confidence DESC NULLS LAST
  ) q
  ORDER BY ts ASC
) TO STDOUT WITH CSV HEADER;
