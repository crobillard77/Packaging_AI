/*
  Packaging AI — SQL Server schema (optional manual run).
  The API also runs equivalent DDL via SqlServerJobRepository.ensure_schema().

  Database: PackagingAI (create first)
  Auth: SQL Authentication for the API service account
*/

IF DB_ID(N'PackagingAI') IS NULL
BEGIN
    CREATE DATABASE PackagingAI;
END
GO

USE PackagingAI;
GO

IF OBJECT_ID(N'dbo.jobs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.jobs (
        id UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
        status NVARCHAR(32) NOT NULL,
        folder_path NVARCHAR(1024) NOT NULL,
        output_dir NVARCHAR(1024) NULL,
        auto_confirm BIT NOT NULL CONSTRAINT DF_jobs_auto_confirm DEFAULT (0),
        confidence_score FLOAT NULL,
        state_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_jobs_state_json DEFAULT (N'{}'),
        clarification_json NVARCHAR(MAX) NULL,
        error NVARCHAR(MAX) NULL,
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        started_at DATETIME2 NULL,
        finished_at DATETIME2 NULL
    );
    CREATE INDEX IX_jobs_status_created ON dbo.jobs (status, created_at);
END
GO

IF OBJECT_ID(N'dbo.job_events', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.job_events (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        job_id UNIQUEIDENTIFIER NOT NULL,
        event_type NVARCHAR(64) NOT NULL,
        message NVARCHAR(MAX) NULL,
        created_at DATETIME2 NOT NULL,
        CONSTRAINT FK_job_events_jobs FOREIGN KEY (job_id) REFERENCES dbo.jobs(id)
    );
    CREATE INDEX IX_job_events_job_created ON dbo.job_events (job_id, created_at);
END
GO
