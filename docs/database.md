# Relia Database Integration

This document explains the database integration in Relia OSS.

## Database Architecture

Relia uses SQLite for local storage of:

1. **Feedback** - User ratings and comments on generated playbooks
2. **Telemetry** - Usage data and events
3. **Playbooks** - Metadata about generated playbooks
4. **LLM Usage** - Metrics on LLM API usage

## Database Schema

The database schema consists of four main tables:

### Feedback Table

Stores user feedback on generated playbooks:

```sql
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playbook_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous'
);
```

### Telemetry Table

Stores usage data and events:

```sql
CREATE TABLE telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL,  -- JSON string
    created_at TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous',
    session_id TEXT
);
```

### Playbooks Table

Stores metadata about generated playbooks:

```sql
CREATE TABLE playbooks (
    playbook_id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    prompt TEXT NOT NULL,
    yaml_content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous',
    status TEXT DEFAULT 'created'
);
```

### LLM Usage Table

Stores metrics on LLM API usage:

```sql
CREATE TABLE llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    duration_ms INTEGER,
    created_at TEXT NOT NULL,
    request_id TEXT,
    user_id TEXT DEFAULT 'anonymous'
);
```

## Configuration

Database functionality can be controlled with these environment variables:

- `RELIA_DB_ENABLED` - Enable/disable database (default: `True`)
- `RELIA_COLLECT_TELEMETRY` - Enable/disable telemetry collection (default: `True`)
- `RELIA_COLLECT_FEEDBACK` - Enable/disable feedback storage (default: `True`)
- `RELIA_COLLECT_LLM_USAGE` - Enable/disable LLM usage tracking (default: `True`)
- `RELIA_DATA_DIR` - Directory for database and other data (default: `.relia-data`)

## Data Flow

### Feedback Flow

1. User submits feedback via the `/feedback` endpoint
2. The playbook is validated to ensure it exists
3. Feedback is recorded in the database
4. A telemetry event is recorded for analytics

### Telemetry Flow

Telemetry is recorded at key points in the application:

1. When a playbook is generated
2. When a cache hit occurs
3. When a playbook is linted
4. When a playbook is tested
5. When errors occur
6. When feedback is submitted

Each telemetry event includes:
- Event type
- Event data (JSON)
- Timestamp
- User ID
- Session ID (if available)

### LLM Usage Tracking

LLM usage is tracked automatically when interacting with LLM providers:

1. Provider and model used
2. Tokens used (prompt, completion, total)
3. Request duration
4. User ID
5. Request ID

## API Endpoints

The database integration adds these admin endpoints:

- `GET /admin/stats/feedback` - Get feedback statistics
- `GET /admin/stats/telemetry` - Get telemetry statistics
- `GET /admin/stats/llm` - Get LLM usage statistics

All endpoints require the `admin` role.

## User Identification

Users are identified by:

1. JWT token subject if authentication is enabled
2. `X-User-ID` header if provided
3. Default "anonymous" otherwise

## Database Security

The SQLite database is stored in the `RELIA_DATA_DIR` directory, which is local to the machine running Relia. Database files are created with proper permissions to prevent unauthorized access.

Note that SQLite databases are not encrypted by default. If encryption is required, consider:

1. Using filesystem-level encryption
2. Using an encrypted database extension
3. Using a different database backend with encryption support

## Performance Considerations

SQLite is designed for local use and may not be suitable for high-concurrency environments. If you expect heavy usage:

1. Consider using connection pooling
2. Use batch operations for bulk inserts
3. Create appropriate indexes
4. Consider using a client/server database for multi-user deployments

## Data Privacy

The database collects:

1. User feedback (if enabled)
2. Usage telemetry (if enabled)
3. Generated playbooks and their metadata
4. LLM usage data

Consider legal requirements such as GDPR, CCPA, etc. when enabling data collection. Users should be informed about what data is collected and how it's used.