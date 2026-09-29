-- Distributor sales. The API creates these on startup; this file is here so the
-- schema can be read, reviewed and applied by hand if you would rather.
CREATE TABLE IF NOT EXISTS distributor (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  Name VARCHAR(60) NOT NULL UNIQUE,
  CutoffDay INT NOT NULL DEFAULT 15,
  InvoiceMode VARCHAR(10) NOT NULL DEFAULT 'seq',   -- seq | file
  NegateReturns TINYINT NOT NULL DEFAULT 1,
  PickPattern VARCHAR(200) NULL,                    -- names the files this rule wants
  Note VARCHAR(500) NULL,
  Active TINYINT NOT NULL DEFAULT 1,
  -- master details; the CountryId foreign key is added in schema_masters.sql
  Code VARCHAR(20) NULL,
  CountryId INT NULL,
  ContactPerson VARCHAR(120) NULL,
  Phone VARCHAR(30) NULL,
  Email VARCHAR(120) NULL
);

CREATE TABLE IF NOT EXISTS batch (
  Id INT AUTO_INCREMENT PRIMARY KEY,
  DistributorId INT NOT NULL,
  SourceName VARCHAR(255) NOT NULL DEFAULT '',
  AsOf DATE NOT NULL,
  MonthName VARCHAR(12) NOT NULL,
  Year INT NOT NULL,
  MidMonth CHAR(1) NOT NULL,
  CutoffDay INT NOT NULL,
  InvoiceMode VARCHAR(10) NOT NULL,
  RowCount INT NOT NULL DEFAULT 0,
  OmittedCount INT NOT NULL DEFAULT 0,
  TotalQty DECIMAL(18,3) NOT NULL DEFAULT 0,
  TotalAmount DECIMAL(18,2) NOT NULL DEFAULT 0,
  CreatedBy VARCHAR(120) NOT NULL DEFAULT '',
  CreatedAtUtc DATETIME NOT NULL,
  Notes TEXT NULL,
  INDEX ix_batch_dist (DistributorId, CreatedAtUtc),
  CONSTRAINT fk_batch_dist FOREIGN KEY (DistributorId) REFERENCES distributor(Id)
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
