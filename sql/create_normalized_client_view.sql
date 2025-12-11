-- Create a view with normalized client names for querying
-- This view applies client_mappings.json transformations at query time

CREATE OR REPLACE VIEW `angular-stacker-471711-k4.unknown_brain.meeting_intel_normalized` AS
SELECT
  meeting_id,
  date,
  participants,
  desk,
  source,

  -- Normalize client name using CASE statement
  CASE JSON_VALUE(client_info, '$.client')
    -- Corrupted hex entries
    WHEN '25615A3D E4C9' THEN 'Unknown'
    WHEN 'Bcb88E78 88E8' THEN 'Unknown'
    WHEN 'D185Be63 81B0' THEN 'Unknown'

    -- Leagas Delaney variants
    WHEN 'Legas Delaney' THEN 'Leagas Delaney'

    -- Omnicom variants
    WHEN 'Omnicom / DDB' THEN 'Omnicom'

    -- Sophia variant
    WHEN 'Sophia (creative agency within Atoms & Space group)' THEN 'Sophia'

    -- Media Arts Lab variant
    WHEN 'Media Arts Lab (Apple\'s advertising agency)' THEN 'Media Arts Lab'

    -- Your Studio variant
    WHEN 'Your Studio (unnamed; referred to as "your studio" / founder\'s studio)' THEN 'Your Studio'

    -- Default: use original value
    ELSE JSON_VALUE(client_info, '$.client')
  END AS client_normalized,

  -- Keep original client_info for reference
  client_info,

  -- Other fields
  granola_note_id,
  title,
  creator_name,
  creator_email,
  calendar_event_title,
  calendar_event_id,
  calendar_event_time,
  granola_link,
  file_created_timestamp,
  zapier_step_id,
  enhanced_notes,
  my_notes,
  full_transcript,
  total_qualified_sections,
  qualified,
  now,
  next,
  measure,
  blocker,
  fit,
  challenges,
  results,
  offering,
  scored_at,
  llm_model

FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`;

-- Example queries using the normalized view:

-- 1. Get all meetings for a client (handles variants automatically)
-- SELECT * FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel_normalized`
-- WHERE client_normalized = 'Omnicom'
-- ORDER BY date DESC;

-- 2. Count meetings per normalized client
-- SELECT
--   client_normalized,
--   COUNT(*) as meeting_count,
--   AVG(total_qualified_sections) as avg_score
-- FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel_normalized`
-- GROUP BY client_normalized
-- ORDER BY meeting_count DESC;

-- 3. Find qualified opportunities by client
-- SELECT
--   client_normalized,
--   meeting_id,
--   date,
--   total_qualified_sections,
--   JSON_VALUE(fit, '$.services') as services
-- FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel_normalized`
-- WHERE qualified = TRUE
-- ORDER BY client_normalized, date DESC;
