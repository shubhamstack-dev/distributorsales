-- Master data. Apply after schema.sql. The API creates these on startup too;
-- this file is here so the schema can be read, reviewed and applied by hand.
--
-- Structure (permanent):  Zone > Headquarter > Territory
--                         Product Group > Brand > SKU
-- Alignment (per year):   every table with a YearId. Copy a year forward on the
--                         screen, then change only what moved.
--
-- Generated from app/models_master.py with the MySQL dialect, so it matches.

CREATE TABLE IF NOT EXISTS md_company (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_company_code UNIQUE (`Code`)
);

CREATE TABLE IF NOT EXISTS md_country (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(80) NOT NULL,
  `CurrencyCode` VARCHAR(3) NOT NULL,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_country_code UNIQUE (`Code`)
);

CREATE TABLE IF NOT EXISTS md_currency_rate (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `FromCurrency` VARCHAR(3) NOT NULL,
  `ToCurrency` VARCHAR(3) NOT NULL,
  `Rate` NUMERIC(18, 6) NOT NULL,
  `EffectiveFrom` DATE NOT NULL,
  `Note` VARCHAR(200),
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_rate_pair_date UNIQUE (`FromCurrency`, `ToCurrency`, `EffectiveFrom`)
);

CREATE TABLE IF NOT EXISTS md_designation (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(80) NOT NULL,
  `Level` INTEGER NOT NULL DEFAULT 1,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_designation_code UNIQUE (`Code`)
);

CREATE TABLE IF NOT EXISTS md_role (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(80) NOT NULL,
  `Description` VARCHAR(300),
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_role_code UNIQUE (`Code`)
);

CREATE TABLE IF NOT EXISTS md_year (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `YearValue` INTEGER NOT NULL,
  `Label` VARCHAR(40) NOT NULL,
  `StartDate` DATE NOT NULL,
  `EndDate` DATE NOT NULL,
  `IsCurrent` INTEGER NOT NULL DEFAULT 0,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  UNIQUE (`YearValue`)
);

CREATE TABLE IF NOT EXISTS md_company_country (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `CompanyId` INTEGER NOT NULL,
  `CountryId` INTEGER NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_company_country UNIQUE (`CompanyId`, `CountryId`),
  FOREIGN KEY(`CompanyId`) REFERENCES md_company (`Id`),
  FOREIGN KEY(`CountryId`) REFERENCES md_country (`Id`)
);

CREATE TABLE IF NOT EXISTS md_product_group (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `CompanyId` INTEGER,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_pg_code UNIQUE (`Code`),
  FOREIGN KEY(`CompanyId`) REFERENCES md_company (`Id`)
);

CREATE TABLE IF NOT EXISTS md_product_reporting (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `YearId` INTEGER NOT NULL,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `Flag` VARCHAR(2) NOT NULL,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_pr_year_code UNIQUE (`YearId`, `Code`),
  FOREIGN KEY(`YearId`) REFERENCES md_year (`Id`)
);

CREATE TABLE IF NOT EXISTS md_team (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(80) NOT NULL,
  `CompanyId` INTEGER,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_team_code UNIQUE (`Code`),
  FOREIGN KEY(`CompanyId`) REFERENCES md_company (`Id`)
);

CREATE TABLE IF NOT EXISTS md_zone (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `CountryId` INTEGER NOT NULL,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_zone_code UNIQUE (`Code`),
  FOREIGN KEY(`CountryId`) REFERENCES md_country (`Id`)
);

CREATE TABLE IF NOT EXISTS md_brand (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `ProductGroupId` INTEGER NOT NULL,
  `Nrv` VARCHAR(20),
  `StartDate` DATE,
  `EndDate` DATE,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_brand_code UNIQUE (`Code`),
  FOREIGN KEY(`ProductGroupId`) REFERENCES md_product_group (`Id`)
);

CREATE TABLE IF NOT EXISTS md_headquarter (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `ZoneId` INTEGER NOT NULL,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_hq_code UNIQUE (`Code`),
  FOREIGN KEY(`ZoneId`) REFERENCES md_zone (`Id`)
);

CREATE TABLE IF NOT EXISTS md_team_product_group (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `YearId` INTEGER NOT NULL,
  `TeamId` INTEGER NOT NULL,
  `ProductGroupId` INTEGER NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_tpg UNIQUE (`YearId`, `TeamId`, `ProductGroupId`),
  FOREIGN KEY(`YearId`) REFERENCES md_year (`Id`),
  FOREIGN KEY(`TeamId`) REFERENCES md_team (`Id`),
  FOREIGN KEY(`ProductGroupId`) REFERENCES md_product_group (`Id`)
);

CREATE TABLE IF NOT EXISTS md_employee (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `DesignationId` INTEGER NOT NULL,
  `RoleId` INTEGER,
  `TeamId` INTEGER,
  `HeadquarterId` INTEGER,
  `ReportsToId` INTEGER,
  `Email` VARCHAR(120),
  `Phone` VARCHAR(30),
  `JoiningDate` DATE,
  `EndDate` DATE,
  `TerritoryCode` VARCHAR(20),
  `RdCsEditable` INTEGER NOT NULL DEFAULT 0,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_employee_code UNIQUE (`Code`),
  FOREIGN KEY(`DesignationId`) REFERENCES md_designation (`Id`),
  FOREIGN KEY(`RoleId`) REFERENCES md_role (`Id`),
  FOREIGN KEY(`TeamId`) REFERENCES md_team (`Id`),
  FOREIGN KEY(`HeadquarterId`) REFERENCES md_headquarter (`Id`),
  FOREIGN KEY(`ReportsToId`) REFERENCES md_employee (`Id`)
);

CREATE TABLE IF NOT EXISTS md_sku (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(250) NOT NULL,
  `BrandId` INTEGER NOT NULL,
  `PackSize` VARCHAR(40),
  `SapProductId` VARCHAR(25),
  `MaterialCode` VARCHAR(50),
  `Nrv` VARCHAR(20),
  `StartDate` DATE,
  `EndDate` DATE,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_sku_code UNIQUE (`Code`),
  FOREIGN KEY(`BrandId`) REFERENCES md_brand (`Id`)
);

CREATE TABLE IF NOT EXISTS md_team_headquarter (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `YearId` INTEGER NOT NULL,
  `TeamId` INTEGER NOT NULL,
  `HeadquarterId` INTEGER NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_thq UNIQUE (`YearId`, `TeamId`, `HeadquarterId`),
  FOREIGN KEY(`YearId`) REFERENCES md_year (`Id`),
  FOREIGN KEY(`TeamId`) REFERENCES md_team (`Id`),
  FOREIGN KEY(`HeadquarterId`) REFERENCES md_headquarter (`Id`)
);

CREATE TABLE IF NOT EXISTS md_territory (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `Code` VARCHAR(20) NOT NULL,
  `Name` VARCHAR(120) NOT NULL,
  `HeadquarterId` INTEGER NOT NULL,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_territory_code UNIQUE (`Code`),
  FOREIGN KEY(`HeadquarterId`) REFERENCES md_headquarter (`Id`)
);

CREATE TABLE IF NOT EXISTS md_customer (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `CustomerCode` VARCHAR(30) NOT NULL,
  `Name` VARCHAR(200) NOT NULL,
  `Classification` VARCHAR(40) NOT NULL,
  `City` VARCHAR(80),
  `CountryId` INTEGER,
  `SapId` VARCHAR(50),
  `BillingName` VARCHAR(200),
  `ZoneId` INTEGER,
  `HeadquarterId` INTEGER,
  `TerritoryId` INTEGER,
  `SubTerritory` VARCHAR(120),
  `State` VARCHAR(80),
  `Remark` VARCHAR(200),
  `StartDate` DATE,
  `EndDate` DATE,
  `LegacyId` INTEGER,
  `Active` INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_customer_code UNIQUE (`CustomerCode`),
  FOREIGN KEY(`CountryId`) REFERENCES md_country (`Id`),
  FOREIGN KEY(`ZoneId`) REFERENCES md_zone (`Id`),
  FOREIGN KEY(`HeadquarterId`) REFERENCES md_headquarter (`Id`),
  FOREIGN KEY(`TerritoryId`) REFERENCES md_territory (`Id`)
);

CREATE TABLE IF NOT EXISTS md_employee_assignment (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `YearId` INTEGER NOT NULL,
  `EmployeeId` INTEGER NOT NULL,
  `TerritoryId` INTEGER NOT NULL,
  `ProductGroupId` INTEGER NOT NULL,
  `SkuId` INTEGER NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_ea_year_emp_terr_sku UNIQUE (`YearId`, `EmployeeId`, `TerritoryId`, `SkuId`),
  FOREIGN KEY(`YearId`) REFERENCES md_year (`Id`),
  FOREIGN KEY(`EmployeeId`) REFERENCES md_employee (`Id`),
  FOREIGN KEY(`TerritoryId`) REFERENCES md_territory (`Id`),
  FOREIGN KEY(`ProductGroupId`) REFERENCES md_product_group (`Id`),
  FOREIGN KEY(`SkuId`) REFERENCES md_sku (`Id`),
  INDEX ix_ea_territory (`YearId`, `TerritoryId`)
);

CREATE TABLE IF NOT EXISTS md_product_reporting_sku (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `ProductReportingId` INTEGER NOT NULL,
  `SkuId` INTEGER NOT NULL,
  `YearId` INTEGER NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_prs_year_sku UNIQUE (`YearId`, `SkuId`),
  FOREIGN KEY(`ProductReportingId`) REFERENCES md_product_reporting (`Id`),
  FOREIGN KEY(`SkuId`) REFERENCES md_sku (`Id`),
  FOREIGN KEY(`YearId`) REFERENCES md_year (`Id`)
);

CREATE TABLE IF NOT EXISTS md_sku_alias (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `SkuId` INTEGER NOT NULL,
  `Alias` VARCHAR(250) NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_sku_alias UNIQUE (`SkuId`, `Alias`),
  FOREIGN KEY(`SkuId`) REFERENCES md_sku (`Id`),
  INDEX ix_sku_alias (`Alias`)
);

CREATE TABLE IF NOT EXISTS md_customer_alias (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `CustomerId` INTEGER NOT NULL,
  `Alias` VARCHAR(200) NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_customer_alias UNIQUE (`CustomerId`, `Alias`),
  FOREIGN KEY(`CustomerId`) REFERENCES md_customer (`Id`),
  INDEX ix_customer_alias (`Alias`)
);

CREATE TABLE IF NOT EXISTS md_customer_assignment (
  `Id` INTEGER NOT NULL AUTO_INCREMENT,
  `YearId` INTEGER NOT NULL,
  `CustomerId` INTEGER NOT NULL,
  `TerritoryId` INTEGER NOT NULL,
  `TeamId` INTEGER NOT NULL,
  `ProductGroupId` INTEGER NOT NULL,
  `SkuId` INTEGER NOT NULL,
  PRIMARY KEY (`Id`),
  CONSTRAINT uq_ca_year_cust_sku UNIQUE (`YearId`, `CustomerId`, `SkuId`),
  FOREIGN KEY(`YearId`) REFERENCES md_year (`Id`),
  FOREIGN KEY(`CustomerId`) REFERENCES md_customer (`Id`),
  FOREIGN KEY(`TerritoryId`) REFERENCES md_territory (`Id`),
  FOREIGN KEY(`TeamId`) REFERENCES md_team (`Id`),
  FOREIGN KEY(`ProductGroupId`) REFERENCES md_product_group (`Id`),
  FOREIGN KEY(`SkuId`) REFERENCES md_sku (`Id`),
  INDEX ix_ca_territory (`YearId`, `TerritoryId`)
);
