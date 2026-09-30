-- Only for a database from the master data release (before the legacy import).
-- The API does this itself on startup (services/migrate.py); this is the
-- by-hand version. Run it, then schema_masters.sql for the two alias tables.
ALTER TABLE md_zone          ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_headquarter   ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_territory     ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_product_group ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_designation   ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_role          ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_team          ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_brand
  ADD COLUMN Nrv VARCHAR(20) NULL, ADD COLUMN StartDate DATE NULL,
  ADD COLUMN EndDate DATE NULL, ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_sku
  MODIFY Name VARCHAR(250) NOT NULL,
  ADD COLUMN SapProductId VARCHAR(25) NULL, ADD COLUMN MaterialCode VARCHAR(50) NULL,
  ADD COLUMN Nrv VARCHAR(20) NULL, ADD COLUMN StartDate DATE NULL,
  ADD COLUMN EndDate DATE NULL, ADD COLUMN LegacyId INT NULL;
ALTER TABLE md_customer
  ADD COLUMN SapId VARCHAR(50) NULL, ADD COLUMN BillingName VARCHAR(200) NULL,
  ADD COLUMN ZoneId INT NULL, ADD COLUMN HeadquarterId INT NULL, ADD COLUMN TerritoryId INT NULL,
  ADD COLUMN SubTerritory VARCHAR(120) NULL, ADD COLUMN State VARCHAR(80) NULL,
  ADD COLUMN Remark VARCHAR(200) NULL, ADD COLUMN StartDate DATE NULL,
  ADD COLUMN EndDate DATE NULL, ADD COLUMN LegacyId INT NULL,
  ADD CONSTRAINT fk_cust_zone FOREIGN KEY (ZoneId) REFERENCES md_zone(Id),
  ADD CONSTRAINT fk_cust_hq FOREIGN KEY (HeadquarterId) REFERENCES md_headquarter(Id),
  ADD CONSTRAINT fk_cust_territory FOREIGN KEY (TerritoryId) REFERENCES md_territory(Id);
ALTER TABLE md_employee
  ADD COLUMN EndDate DATE NULL, ADD COLUMN TerritoryCode VARCHAR(20) NULL,
  ADD COLUMN RdCsEditable INT NOT NULL DEFAULT 0, ADD COLUMN LegacyId INT NULL;
