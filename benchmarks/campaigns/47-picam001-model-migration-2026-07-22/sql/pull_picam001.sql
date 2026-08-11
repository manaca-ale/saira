-- Pull ALL pi-cam-001 (Residencial Via Mangue III-2, Imbiribeira) labeled detections.
-- Ground truth = detections.status: CONFIRMADO=TP, REJEITADO=FP, INDETERMINADO=ambiguous.
-- pi-cam-001 is EVENT-DRIVEN: each detection carries event_ref (first coalesced event);
-- the full event_refs[] list lives in the worker detection_frames/<id>.json.
-- Run inside the prod db container (read-only), e.g.:
--   cat pull_picam001.sql | ssh saira-prod \
--     'docker exec -i saira-db-prod psql -U postgres -d saira_db -q -f -' > corpus_picam001.csv
COPY (
  SELECT id, status, created_at, validity_comment, waste_bbox, image_url,
         confidence_score, agent1_confidence, offender_present, agent2_disposal,
         waste_type, volume_m3, logradouro, bairro, rpa, event_ref
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
      d.bairro                           AS bairro,
      d.rpa                              AS rpa,
      COALESCE(d.event_ref, '')          AS event_ref,
      d.timestamp                        AS ts
    FROM detections d
    JOIN cameras c ON c.id = d.camera_id
    LEFT JOIN cascade_decisions cd ON cd.detection_id = d.id
    WHERE c.device_id = 'pi-cam-001'
      AND d.status IN ('CONFIRMADO', 'REJEITADO', 'INDETERMINADO')
    ORDER BY d.id,
             (cd.detection_id IS NOT NULL) DESC,
             cd.agent1_confidence DESC NULLS LAST
  ) q
  ORDER BY ts ASC
) TO STDOUT WITH CSV HEADER;
