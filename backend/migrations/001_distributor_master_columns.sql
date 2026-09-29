-- Only for a database created before the master data release. The API does
-- this itself on startup (services/migrate.py); this is the by-hand version.
-- Run it, then schema_masters.sql.
ALTER TABLE distributor
  ADD COLUMN Code VARCHAR(20) NULL,
  ADD COLUMN CountryId INT NULL,
  ADD COLUMN ContactPerson VARCHAR(120) NULL,
  ADD COLUMN Phone VARCHAR(30) NULL,
  ADD COLUMN Email VARCHAR(120) NULL;
