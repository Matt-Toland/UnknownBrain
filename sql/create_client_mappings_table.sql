-- Create client_mappings table for production-ready name normalization
-- This table persists across Cloud Run deployments

CREATE TABLE IF NOT EXISTS `angular-stacker-471711-k4.unknown_brain.client_mappings` (
  variant_name STRING NOT NULL,
  canonical_name STRING NOT NULL,
  notes STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- Create unique index to prevent duplicate variants
CREATE UNIQUE INDEX IF NOT EXISTS idx_variant_name
ON `angular-stacker-471711-k4.unknown_brain.client_mappings` (variant_name);

-- Insert initial mappings from client_mappings.json
INSERT INTO `angular-stacker-471711-k4.unknown_brain.client_mappings`
  (variant_name, canonical_name, notes)
VALUES
  -- Corrupted hex entries
  ('25615A3D E4C9', 'Unknown', 'Corrupted UUID fragment from filename extraction'),
  ('Bcb88E78 88E8', 'Unknown', 'Corrupted UUID fragment from filename extraction'),
  ('D185Be63 81B0', 'Unknown', 'Corrupted UUID fragment from filename extraction'),

  -- Client name variants
  ('Legas Delaney', 'Leagas Delaney', 'Typo variant'),
  ('Omnicom / DDB', 'Omnicom', 'Normalize to parent company'),
  ('Sophia (creative agency within Atoms & Space group)', 'Sophia', 'Remove descriptive text'),
  ('Media Arts Lab (Apple\'s advertising agency)', 'Media Arts Lab', 'Remove descriptive text'),
  ('Your Studio (unnamed; referred to as "your studio" / founder\'s studio)', 'Your Studio', 'Remove descriptive text'),

  -- Keep these as-is (no change needed, but listed for completeness)
  ('adam&eveDDB', 'adam&eveDDB', 'Canonical name - keep formatting'),
  ('Adam and Eve Recruitment', 'Adam and Eve Recruitment', 'Separate entity from adam&eveDDB');

-- View current mappings
SELECT
  variant_name,
  canonical_name,
  notes,
  created_at
FROM `angular-stacker-471711-k4.unknown_brain.client_mappings`
ORDER BY variant_name;
