-- Distributor sales. The API creates these on startup; this file is here so the
-- schema can be read, reviewed and applied by hand if you would rather.
CREATE TABLE IF NOT EXISTS distributor (
	`Id` INTEGER NOT NULL AUTO_INCREMENT, 
	`Name` VARCHAR(60) NOT NULL, 
	`CutoffDay` INTEGER NOT NULL, 
	`InvoiceMode` VARCHAR(10) NOT NULL, 
	`NegateReturns` INTEGER NOT NULL, 
	`PickPattern` VARCHAR(200), 
	`RateMode` VARCHAR(10) NOT NULL, 
	`MidCutoffDay` INTEGER, 
	`SalesSheet` INTEGER, 
	`ReturnSheet` INTEGER, 
	`ProductKeepDot` INTEGER NOT NULL, 
	`Note` VARCHAR(700), 
	`Active` INTEGER NOT NULL, 
	`Code` VARCHAR(20), 
	`CountryId` INTEGER, 
	`ContactPerson` VARCHAR(120), 
	`Phone` VARCHAR(30), 
	`Email` VARCHAR(120), 
	PRIMARY KEY (`Id`), 
	UNIQUE (`Name`), 
	FOREIGN KEY(`CountryId`) REFERENCES md_country (`Id`)
);

CREATE TABLE IF NOT EXISTS batch (
	`Id` INTEGER NOT NULL AUTO_INCREMENT, 
	`DistributorId` INTEGER NOT NULL, 
	`SourceName` VARCHAR(255) NOT NULL, 
	`AsOf` DATE NOT NULL, 
	`MonthName` VARCHAR(12) NOT NULL, 
	`Year` INTEGER NOT NULL, 
	`MidMonth` VARCHAR(1) NOT NULL, 
	`CutoffDay` INTEGER NOT NULL, 
	`MidCutoffDay` INTEGER, 
	`InvoiceMode` VARCHAR(10) NOT NULL, 
	`RowCount` INTEGER NOT NULL, 
	`OmittedCount` INTEGER NOT NULL, 
	`TotalQty` NUMERIC(18, 3) NOT NULL, 
	`TotalAmount` NUMERIC(18, 2) NOT NULL, 
	`CreatedBy` VARCHAR(120) NOT NULL, 
	`CreatedAtUtc` DATETIME NOT NULL, 
	`Notes` TEXT, 
	PRIMARY KEY (`Id`), 
	FOREIGN KEY(`DistributorId`) REFERENCES distributor (`Id`)
);

-- Every workbook that was offered, used or not: when a total looks wrong the
-- first question is which files went in, and the second is which did not.
CREATE TABLE IF NOT EXISTS batch_file (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  BatchId INT NOT NULL,
  FileName VARCHAR(255) NOT NULL,
  Used TINYINT NOT NULL DEFAULT 0,
  Layout VARCHAR(30) NULL,
  `Rows` INT NOT NULL DEFAULT 0,                    -- reserved word in MySQL 8, so quoted
  Omitted INT NOT NULL DEFAULT 0,
  Detail VARCHAR(500) NULL,
  CONSTRAINT fk_bf_batch FOREIGN KEY (BatchId) REFERENCES batch(Id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sales_row (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  BatchId INT NOT NULL,
  Seq INT NOT NULL,
  DistributorName VARCHAR(60) NOT NULL,
  InvoiceNo VARCHAR(40) NOT NULL,
  MonthName VARCHAR(12) NOT NULL,
  Year INT NOT NULL,
  MidMonth CHAR(1) NOT NULL,
  CustomerName VARCHAR(200) NOT NULL,
  ProductName VARCHAR(200) NOT NULL,
  Quantity DECIMAL(18,3) NOT NULL DEFAULT 0,
  FreeQuantity DECIMAL(18,3) NOT NULL DEFAULT 0,
  Rate DECIMAL(18,6) NOT NULL DEFAULT 0,
  BAmount DECIMAL(18,2) NOT NULL DEFAULT 0,
  Amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  SourceFile VARCHAR(255) NULL,
  IsReturn TINYINT NOT NULL DEFAULT 0,
  CONSTRAINT uq_row_seq UNIQUE (BatchId, Seq),
  INDEX ix_row_batch (BatchId),
  CONSTRAINT fk_row_batch FOREIGN KEY (BatchId) REFERENCES batch(Id) ON DELETE CASCADE
);

-- A distributor's reference names. Extracted customer and product names are
-- matched against NormName (letters and digits only, upper case) and replaced
-- with Name where they match.
CREATE TABLE IF NOT EXISTS name_ref (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  DistributorId INT NOT NULL,
  Kind VARCHAR(10) NOT NULL,                        -- customer | product
  Name VARCHAR(200) NOT NULL,
  NormName VARCHAR(200) NOT NULL,
  SourceFile VARCHAR(255) NULL,
  UploadedAtUtc DATETIME NOT NULL,
  CONSTRAINT uq_name_ref UNIQUE (DistributorId, Kind, NormName),
  CONSTRAINT fk_nr_dist FOREIGN KEY (DistributorId) REFERENCES distributor(Id) ON DELETE CASCADE
);
