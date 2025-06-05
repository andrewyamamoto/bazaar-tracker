BEGIN;

CREATE TABLE IF NOT EXISTS public.game (
	id bigint DEFAULT nextval('game_seq'::regclass) NOT NULL,
	player character varying,
	season integer,
	ranked boolean,
	hero character varying,
	wins integer,
	finished integer,
	media character varying,
	notes text,
	played timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY(id)
);

COMMIT;
