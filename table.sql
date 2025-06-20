BEGIN;

CREATE TABLE IF NOT EXISTS public.game (
	id bigint DEFAULT nextval('game_seq'::regclass) NOT NULL,
	player_id character varying,
	patch_id character varying,
	season integer,
	ranked boolean,
	hero character varying,
	wins integer,
	finished integer,
	media character varying,
	upload character varying,
	notes text,
	played timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY(id)
);
-- Create a separate sequence for users table IDs
CREATE SEQUENCE IF NOT EXISTS users_seq;
CREATE SEQUENCE IF NOT EXISTS patch_seq;

CREATE TABLE IF NOT EXISTS public.users (
	id bigint DEFAULT nextval('users_seq'::regclass) NOT NULL,
	u_name character varying,
	u_password character varying,
	PRIMARY KEY(id)
);

CREATE TABLE IF NOT EXISTS public.patches (
	id bigint DEFAULT nextval('patch_seq'::regclass) NOT NULL,
	patch_version character varying,
	PRIMARY KEY(id)
);

COMMIT;
