-- ============================================================================
-- Alien Time Listing Studio - Complete Supabase PostgreSQL Schema
-- Project: alientime-studio (ffeethtdohrwkatahopy)
-- Generated for Supabase SQL / Query Editor
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table: ai_usage
CREATE TABLE IF NOT EXISTS ai_usage (
	id SERIAL NOT NULL, 
	at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	provider VARCHAR(40) NOT NULL, 
	model VARCHAR(80) NOT NULL, 
	operation VARCHAR(60) NOT NULL, 
	input_tokens INTEGER NOT NULL, 
	output_tokens INTEGER NOT NULL, 
	image_input_count INTEGER NOT NULL, 
	image_output_count INTEGER NOT NULL, 
	cost_usd FLOAT NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	latency_ms INTEGER NOT NULL, 
	watch_id VARCHAR(32), 
	job_id VARCHAR(32), 
	error TEXT, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_ai_usage_at ON ai_usage (at);

-- Table: api_tokens
CREATE TABLE IF NOT EXISTS api_tokens (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	token_prefix VARCHAR(16) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	scopes JSON NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_by VARCHAR(80), 
	last_used_at TIMESTAMP WITHOUT TIME ZONE, 
	revoked_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (token_hash)
);


-- Table: app_settings
CREATE TABLE IF NOT EXISTS app_settings (
	key VARCHAR(80) NOT NULL, 
	value JSON NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_by VARCHAR(120), 
	PRIMARY KEY (key)
);


-- Table: audit_events
CREATE TABLE IF NOT EXISTS audit_events (
	id SERIAL NOT NULL, 
	at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	actor VARCHAR(160) NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	entity_type VARCHAR(40), 
	entity_id VARCHAR(64), 
	watch_id VARCHAR(32), 
	summary TEXT NOT NULL, 
	detail JSON NOT NULL, 
	ip VARCHAR(64), 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_audit_events_at ON audit_events (at);
CREATE INDEX IF NOT EXISTS ix_audit_events_watch_id ON audit_events (watch_id);

-- Table: integration_status
CREATE TABLE IF NOT EXISTS integration_status (
	name VARCHAR(40) NOT NULL, 
	state VARCHAR(30) NOT NULL, 
	checked_at TIMESTAMP WITHOUT TIME ZONE, 
	message TEXT, 
	details JSON NOT NULL, 
	live_enabled BOOLEAN NOT NULL, 
	PRIMARY KEY (name)
);


-- Table: jobs
CREATE TABLE IF NOT EXISTS jobs (
	id VARCHAR(32) NOT NULL, 
	type VARCHAR(60) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	watch_id VARCHAR(32), 
	asset_id VARCHAR(32), 
	channel VARCHAR(40), 
	payload JSON NOT NULL, 
	result JSON NOT NULL, 
	error TEXT, 
	progress FLOAT NOT NULL, 
	progress_message VARCHAR(300), 
	attempts INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	idempotency_key VARCHAR(200), 
	run_after TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	locked_by VARCHAR(80), 
	heartbeat_at TIMESTAMP WITHOUT TIME ZONE, 
	cancel_requested BOOLEAN NOT NULL, 
	created_by VARCHAR(160), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITHOUT TIME ZONE, 
	finished_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_jobs_status_run_after ON jobs (status, run_after);
CREATE INDEX IF NOT EXISTS ix_jobs_watch_id ON jobs (watch_id);

-- Table: spec_records
CREATE TABLE IF NOT EXISTS spec_records (
	id VARCHAR(32) NOT NULL, 
	brand VARCHAR(120) NOT NULL, 
	model VARCHAR(200) NOT NULL, 
	reference VARCHAR(120), 
	calibre VARCHAR(120), 
	movement_type VARCHAR(80), 
	case_size_mm VARCHAR(40), 
	case_thickness_mm VARCHAR(40), 
	case_material VARCHAR(120), 
	dial VARCHAR(200), 
	bezel VARCHAR(200), 
	crystal VARCHAR(120), 
	water_resistance VARCHAR(80), 
	power_reserve VARCHAR(80), 
	bracelet_strap VARCHAR(200), 
	functions VARCHAR(300), 
	extra JSON NOT NULL, 
	source_note TEXT, 
	status VARCHAR(20) NOT NULL, 
	approved_by VARCHAR(80), 
	approved_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_spec_records_reference ON spec_records (reference);

-- Table: users
CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	display_name VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	last_login_at TIMESTAMP WITHOUT TIME ZONE, 
	password_changed_at TIMESTAMP WITHOUT TIME ZONE, 
	failed_login_count INTEGER NOT NULL, 
	locked_until TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);


-- Table: user_sessions
CREATE TABLE IF NOT EXISTS user_sessions (
	id VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	csrf_token VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	last_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	ip VARCHAR(64), 
	user_agent VARCHAR(255), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions (user_id);

-- Table: watches
CREATE TABLE IF NOT EXISTS watches (
	id VARCHAR(32) NOT NULL, 
	sku VARCHAR(60) NOT NULL, 
	brand VARCHAR(120) NOT NULL, 
	model VARCHAR(200) NOT NULL, 
	reference VARCHAR(120), 
	year VARCHAR(20), 
	condition VARCHAR(40), 
	condition_notes TEXT, 
	price_sgd NUMERIC(14, 2), 
	price_usd NUMERIC(14, 2), 
	fx_rate_sgd_usd NUMERIC(12, 6), 
	fx_source VARCHAR(40), 
	fx_updated_at TIMESTAMP WITHOUT TIME ZONE, 
	box_papers VARCHAR(30) NOT NULL, 
	box_papers_notes TEXT, 
	custody VARCHAR(30) NOT NULL, 
	is_consignment BOOLEAN NOT NULL, 
	consignor_name VARCHAR(200), 
	consignor_contact VARCHAR(200), 
	consignment_ref VARCHAR(120), 
	consignment_terms TEXT, 
	consignment_payout_sgd NUMERIC(14, 2), 
	consignment_start DATE, 
	consignment_end DATE, 
	consignor_signoff VARCHAR(20) NOT NULL, 
	description TEXT, 
	internal_notes TEXT, 
	extra_facts JSON NOT NULL, 
	spec_id VARCHAR(32), 
	status VARCHAR(30) NOT NULL, 
	status_changed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	gallery JSON NOT NULL, 
	channels JSON, 
	hero_asset_id VARCHAR(32), 
	content_version INTEGER NOT NULL, 
	studio_defaults JSON NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	archived_at TIMESTAMP WITHOUT TIME ZONE, 
	created_by VARCHAR(120), 
	PRIMARY KEY (id), 
	UNIQUE (sku), 
	FOREIGN KEY(spec_id) REFERENCES spec_records (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_watches_status ON watches (status);

-- Table: ai_observations
CREATE TABLE IF NOT EXISTS ai_observations (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	provider VARCHAR(40) NOT NULL, 
	model VARCHAR(80) NOT NULL, 
	asset_ids JSON NOT NULL, 
	payload JSON NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_ai_observations_watch_id ON ai_observations (watch_id);

-- Table: approvals
CREATE TABLE IF NOT EXISTS approvals (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	target VARCHAR(60) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	content_ref VARCHAR(120), 
	snapshot JSON NOT NULL, 
	approved_by VARCHAR(160) NOT NULL, 
	approved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	note TEXT, 
	status VARCHAR(20) NOT NULL, 
	invalidated_at TIMESTAMP WITHOUT TIME ZONE, 
	invalidated_reason TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_approval_target ON approvals (watch_id, scope, target);

-- Table: assets
CREATE TABLE IF NOT EXISTS assets (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	source VARCHAR(30) NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	original_path VARCHAR(500) NOT NULL, 
	original_sha256 VARCHAR(64) NOT NULL, 
	original_bytes INTEGER NOT NULL, 
	original_format VARCHAR(20) NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	exif_summary JSON NOT NULL, 
	phash VARCHAR(32), 
	duplicate_of VARCHAR(32), 
	working_path VARCHAR(500), 
	working_width INTEGER NOT NULL, 
	working_height INTEGER NOT NULL, 
	sort_order INTEGER NOT NULL, 
	uploaded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	uploaded_by VARCHAR(120), 
	removed_at TIMESTAMP WITHOUT TIME ZONE, 
	pipeline_status VARCHAR(30) NOT NULL, 
	pipeline_error TEXT, 
	source_profile VARCHAR(20), 
	source_profile_reasons JSON NOT NULL, 
	inspection JSON NOT NULL, 
	quality_score FLOAT, 
	selected BOOLEAN, 
	selection_reasons JSON NOT NULL, 
	selection_override BOOLEAN, 
	photo_type VARCHAR(30), 
	photo_type_source VARCHAR(20), 
	photo_type_confidence FLOAT, 
	ai_tags JSON NOT NULL, 
	safety_status VARCHAR(30) NOT NULL, 
	safety_engine VARCHAR(60), 
	safety_findings JSON NOT NULL, 
	safety_recheck JSON NOT NULL, 
	safety_reviewed_at TIMESTAMP WITHOUT TIME ZONE, 
	safety_reviewed_by VARCHAR(120), 
	redacted_path VARCHAR(500), 
	redaction_version INTEGER NOT NULL, 
	mask_path VARCHAR(500), 
	mask_version INTEGER NOT NULL, 
	mask_source VARCHAR(60), 
	segmentation JSON NOT NULL, 
	studio_settings JSON NOT NULL, 
	current_render_id VARCHAR(32), 
	render_stale BOOLEAN NOT NULL, 
	review_status VARCHAR(30) NOT NULL, 
	review_note TEXT, 
	warnings JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_assets_watch_id ON assets (watch_id);
CREATE INDEX IF NOT EXISTS ix_assets_original_sha256 ON assets (original_sha256);

-- Table: channel_copies
CREATE TABLE IF NOT EXISTS channel_copies (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	channel VARCHAR(40) NOT NULL, 
	sections JSON NOT NULL, 
	rendered_text TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	generator VARCHAR(80) NOT NULL, 
	style VARCHAR(40) NOT NULL, 
	validation JSON NOT NULL, 
	fixed_blocks_hash VARCHAR(64), 
	facts_hash VARCHAR(64), 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_by VARCHAR(120), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_channel_copy UNIQUE (watch_id, channel), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_channel_copies_watch_id ON channel_copies (watch_id);

-- Table: channel_listings
CREATE TABLE IF NOT EXISTS channel_listings (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	channel VARCHAR(40) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	mode VARCHAR(20) NOT NULL, 
	external_id VARCHAR(200), 
	external_url VARCHAR(500), 
	published_hash VARCHAR(64), 
	published_at TIMESTAMP WITHOUT TIME ZONE, 
	last_action VARCHAR(40), 
	last_synced_at TIMESTAMP WITHOUT TIME ZONE, 
	last_error TEXT, 
	details JSON NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_channel_listing UNIQUE (watch_id, channel), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_channel_listings_watch_id ON channel_listings (watch_id);

-- Table: copy_revisions
CREATE TABLE IF NOT EXISTS copy_revisions (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	channel VARCHAR(40) NOT NULL, 
	version INTEGER NOT NULL, 
	sections JSON NOT NULL, 
	rendered_text TEXT NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	generator VARCHAR(80) NOT NULL, 
	reason VARCHAR(120) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_by VARCHAR(120), 
	PRIMARY KEY (id), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_copy_revisions_watch_id ON copy_revisions (watch_id);

-- Table: fact_suggestions
CREATE TABLE IF NOT EXISTS fact_suggestions (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	field VARCHAR(60) NOT NULL, 
	value TEXT NOT NULL, 
	source VARCHAR(40) NOT NULL, 
	evidence TEXT, 
	confidence FLOAT, 
	status VARCHAR(20) NOT NULL, 
	observation_id VARCHAR(32), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	resolved_at TIMESTAMP WITHOUT TIME ZONE, 
	resolved_by VARCHAR(120), 
	PRIMARY KEY (id), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_fact_suggestions_watch_id ON fact_suggestions (watch_id);

-- Table: manual_tasks
CREATE TABLE IF NOT EXISTS manual_tasks (
	id VARCHAR(32) NOT NULL, 
	watch_id VARCHAR(32) NOT NULL, 
	channel VARCHAR(40) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	instructions TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	live_url VARCHAR(500), 
	content_hash VARCHAR(64), 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITHOUT TIME ZONE, 
	completed_by VARCHAR(120), 
	PRIMARY KEY (id), 
	FOREIGN KEY(watch_id) REFERENCES watches (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_manual_tasks_watch_id ON manual_tasks (watch_id);

-- Table: asset_renders
CREATE TABLE IF NOT EXISTS asset_renders (
	id VARCHAR(32) NOT NULL, 
	asset_id VARCHAR(32) NOT NULL, 
	version INTEGER NOT NULL, 
	settings JSON NOT NULL, 
	background_source VARCHAR(80), 
	master_path VARCHAR(500), 
	master_sha256 VARCHAR(64), 
	variants JSON NOT NULL, 
	fidelity JSON NOT NULL, 
	fidelity_passed BOOLEAN NOT NULL, 
	warnings JSON NOT NULL, 
	inputs JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_asset_renders_asset_id ON asset_renders (asset_id);

-- Table: redaction_regions
CREATE TABLE IF NOT EXISTS redaction_regions (
	id VARCHAR(32) NOT NULL, 
	asset_id VARCHAR(32) NOT NULL, 
	x FLOAT NOT NULL, 
	y FLOAT NOT NULL, 
	w FLOAT NOT NULL, 
	h FLOAT NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	category VARCHAR(60), 
	confidence FLOAT, 
	enabled BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	created_by VARCHAR(120), 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_redaction_regions_asset_id ON redaction_regions (asset_id);
