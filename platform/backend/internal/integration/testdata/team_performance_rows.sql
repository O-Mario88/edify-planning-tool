-- Synthetic records for the Team Performance golden comparison
-- (docs/migration/37-team-performance.md, 37.3). Every row's id starts
-- "tpg"; team_performance_rows_cleanup.sql removes them. They are written
-- into the Go integration database only, never the development one, and
-- reach every rule the seed cannot: officers in four regions and none, a
-- Programme Lead holding schools, closed and reopened schools, every kind
-- of work and status, cluster registers and legacy attended lists, work at
-- no school, the Core package, SSAs in every state, evidence, enrolment,
-- stories, and the Uganda Master Priority Plan targets with their phasing
-- and the country targets IA set.
--
-- Accounts (the seed's): cceo1 (Moses K., Programme Lead 2's team),
-- cceo6 (Esther N., Programme Lead 3's team), pl2 (holds schools of their
-- own). Dates are fixed in FY 2027 (October 2026 to September 2027).

BEGIN;

-- The seed's own records, found by what stays the same from one seeding to
-- the next (an account's email, a district's name, a catalogue item's
-- stable code, a school's code) rather than by their ids, which every
-- seeding draws afresh: CI seeds its own database. A template row (an
-- activity, an SSA record) only lends its columns, every one that matters
-- written over below.
CREATE TEMP TABLE tpg_seed (token text PRIMARY KEY, id text) ON COMMIT DROP;
INSERT INTO tpg_seed VALUES
 ('cmw9p53r100v09heihgm7', (SELECT id FROM district WHERE name = 'Buikwe' ORDER BY id LIMIT 1)),
 ('cmw9p53sh00eaheeihgjo', (SELECT id FROM district WHERE name = 'Bukomansimbi' ORDER BY id LIMIT 1)),
 ('cmw9p54dy0004o4eihgg2', (SELECT id FROM district WHERE name = 'Amuria' ORDER BY id LIMIT 1)),
 ('cmw9p54es00owi5eihgiy', (SELECT id FROM district WHERE name = 'Budaka' ORDER BY id LIMIT 1)),
 ('cmw9p55ge00e766eihg9v', (SELECT id FROM district WHERE name = 'Abim' ORDER BY id LIMIT 1)),
 ('cmw9p55h300a2o1eihgzn', (SELECT id FROM district WHERE name = 'Adjumani' ORDER BY id LIMIT 1)),
 ('cmw9p566x001kjbeihg6q', (SELECT id FROM district WHERE name = 'Buhweju' ORDER BY id LIMIT 1)),
 ('cmw9p567j00vplqeihgoy', (SELECT id FROM district WHERE name = 'Buliisa' ORDER BY id LIMIT 1)),
 ('cmw9p6zeg00klpueihg7a', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'EDTECH_FOUNDATIONS')),
 ('cmw9p6zg600734ueihg0f', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'SCHOOL_LEADERSHIP')),
 ('cmw9p6zhh00nfwoeihg2u', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'GOVERNMENT_STATUTORY_REQUIREMENTS')),
 ('cmw9p6zle0025h0eihgln', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'TAM_I')),
 ('cmw9p6zqd0082gueihgtv', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'EARLY_CHILDHOOD_EDUCATION_PROJECT')),
 ('cmw9p6zs60036xueihght', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'PARTNER_MEETINGS_ADMIN')),
 ('cmw9p6ztj0007xxeihg3z', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'STUDENT_CONFERENCE_CAMPS')),
 ('cmw9p6ztu007g68eihg3z', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'TEACHER_PEDAGOGY_PROFESSIONALISM')),
 ('cmw9p6zui00zapceihg6m', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'CC_SEL')),
 ('cmw9p6zvd00u8dgeihgqm', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'CORE_SCHOOL_ORIENTATION')),
 ('cmw9p705z00slcbeihg2k', (SELECT id FROM activity_catalogue_item WHERE stable_code = 'FIELD_DISTRICT_MEETING')),
 ('cmw9p70ap00h2fieihgfk', (SELECT id FROM hr_strategic_priority_cycle WHERE financial_year = '2027' AND scope_type = 'regional' ORDER BY created_at, id LIMIT 1)),
 ('cmw9p7b6a00e4s8ekhefr', (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'pl2@edify.org' ORDER BY sp.deleted_at NULLS FIRST LIMIT 1)),
 ('cmw9p7bf200eymgekhexn', (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'pl3@edify.org' ORDER BY sp.deleted_at NULLS FIRST LIMIT 1)),
 ('cmw9p7bws00c2f9ekherh', (SELECT id FROM "user" WHERE email = 'cceo1@edify.org')),
 ('cmw9p7c6000iqchekhe36', (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'cceo1@edify.org' ORDER BY sp.deleted_at NULLS FIRST LIMIT 1)),
 ('cmw9p7d6600vvj2ekheu3', (SELECT id FROM "user" WHERE email = 'cceo6@edify.org')),
 ('cmw9p7dez0031o9ekhee5', (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'cceo6@edify.org' ORDER BY sp.deleted_at NULLS FIRST LIMIT 1)),
 ('cmw9p7gp700mkgcekhefg', (SELECT id FROM school WHERE school_id = '1000' ORDER BY id LIMIT 1)),
 ('cmw9p8gmw004ge6ekhe0g', (SELECT id FROM activity WHERE activity_type = 'school_visit' AND status = 'completed' ORDER BY created_at, id LIMIT 1)),
 ('cmw9p7xaj00derkekhe6q', (SELECT id FROM ssa_record ORDER BY created_at, id LIMIT 1));
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM tpg_seed WHERE id IS NULL) THEN
    RAISE EXCEPTION 'the seed lacks: %', (SELECT string_agg(token, ', ') FROM tpg_seed WHERE id IS NULL);
  END IF;
END $$;


-- ── Schools ────────────────────────────────────────────────────────────────
CREATE TEMP TABLE tpg_school ON COMMIT DROP AS SELECT * FROM school WHERE id = (SELECT id FROM tpg_seed WHERE token = 'cmw9p7gp700mkgcekhefg');
CREATE TEMP TABLE tpg_school_spec (id text, code text, name text, owner text, kind text, status text, created timestamptz,
  closes date, closed_at timestamptz, cluster text, region text, district text, enrollment int, enrolled date) ON COMMIT DROP;
INSERT INTO tpg_school_spec VALUES
 ('tpgs01', 'TPG-001', 'Tpg Alpha Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 'client', 'active', '2026-10-05 09:00+03', NULL, NULL, 'x', (SELECT id FROM tpg_seed WHERE token = 'cmw9p54dy0004o4eihgg2'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p54dy0004o4eihgg2'), 410, '2026-10-20'),
 ('tpgs02', 'TPG-002', 'Tpg Beta Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 'core', 'active', '2025-03-01 09:00+03', NULL, NULL, NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p54dy0004o4eihgg2'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p54es00owi5eihgiy'), NULL, NULL),
 ('tpgs03', 'TPG-003', 'Tpg Gamma Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7bws00c2f9ekherh'), 'champion', 'reopened', '2024-01-10 09:00+03', NULL, NULL, 'x', (SELECT id FROM tpg_seed WHERE token = 'cmw9p55ge00e766eihg9v'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p55ge00e766eihg9v'), 220, '2026-09-15'),
 ('tpgs04', 'TPG-004', 'Tpg Delta Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 'client', 'closed', '2024-06-01 09:00+03', '2026-11-01', '2026-10-31 20:00+03', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p55ge00e766eihg9v'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p55h300a2o1eihgzn'), NULL, NULL),
 ('tpgs05', 'TPG-005', 'Tpg Epsilon Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), 'client', 'active', '2026-11-02 09:00+03', NULL, NULL, 'x', (SELECT id FROM tpg_seed WHERE token = 'cmw9p566x001kjbeihg6q'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p566x001kjbeihg6q'), NULL, NULL),
 ('tpgs06', 'TPG-006', 'Tpg Zeta Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), 'core', 'active', '2023-02-01 09:00+03', NULL, NULL, NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p566x001kjbeihg6q'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p567j00vplqeihgoy'), 90, '2026-11-03'),
 ('tpgs07', 'TPG-007', 'Tpg Eta Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), 'core_trained', 'active', '2023-02-02 09:00+03', NULL, NULL, NULL, NULL, NULL, NULL, NULL),
 ('tpgs08', 'TPG-008', 'Tpg Theta Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7b6a00e4s8ekhefr'), 'client', 'active', '2026-10-12 09:00+03', NULL, NULL, 'x', (SELECT id FROM tpg_seed WHERE token = 'cmw9p53r100v09heihgm7'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p53r100v09heihgm7'), NULL, NULL),
 ('tpgs09', 'TPG-009', 'Tpg Iota Primary', NULL, 'client', 'active', '2026-10-13 09:00+03', NULL, NULL, NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p55ge00e766eihg9v'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p55ge00e766eihg9v'), NULL, NULL),
 ('tpgs10', 'TPG-010', 'Tpg Kappa Primary', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 'core', 'closed', '2022-02-02 09:00+03', NULL, '2026-10-10 10:00+03', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p53r100v09heihgm7'), (SELECT id FROM tpg_seed WHERE token = 'cmw9p53sh00eaheeihgjo'), NULL, NULL);
INSERT INTO school
SELECT (jsonb_populate_record(null::school, to_jsonb(t) || jsonb_build_object(
  'id', s.id, 'school_id', s.code, 'name', s.name, 'account_owner_id', s.owner, 'school_type', s.kind,
  'operational_status', s.status, 'created_at', s.created, 'updated_at', s.created, 'deleted_at', NULL,
  'closure_effective_date', s.closes, 'closed_at', s.closed_at,
  'cluster_id', CASE WHEN s.cluster IS NULL THEN NULL ELSE (SELECT id FROM cluster LIMIT 1) END,
  'region_id', CASE WHEN s.region IS NULL THEN NULL ELSE (SELECT region_id FROM district WHERE id = s.region) END,
  'district_id', s.district, 'enrollment', s.enrollment, 'last_enrollment_date', s.enrolled,
  'salesforce_account_id', NULL, 'parish_id', NULL, 'sub_county_id', NULL))).*
FROM tpg_school t, tpg_school_spec s;

-- ── The Alumni project ─────────────────────────────────────────────────────
CREATE TEMP TABLE tpg_project ON COMMIT DROP AS SELECT * FROM project LIMIT 1;
INSERT INTO project SELECT (jsonb_populate_record(null::project, to_jsonb(t) || jsonb_build_object(
  'id', 'tpgp01', 'code', 'TPG-ALUMNI', 'name', 'Tpg Alumni Programme', 'deleted_at', NULL))).* FROM tpg_project t;

-- ── Work ───────────────────────────────────────────────────────────────────
CREATE TEMP TABLE tpg_activity ON COMMIT DROP AS SELECT * FROM activity WHERE id = (SELECT id FROM tpg_seed WHERE token = 'cmw9p8gmw004ge6ekhe0g');
CREATE TEMP TABLE tpg_work (id text, kind text, status text, school text, item text, course text, method text, delivery text,
  actual date, planned date, scheduled timestamptz, teachers int, leaders int, meeting text, project text, attended text[], staff text, created timestamptz) ON COMMIT DROP;
INSERT INTO tpg_work VALUES
 -- client visits: staff completed, partner submitted, staff planned ahead, cancelled, sent back
 ('tpga01', 'school_visit', 'completed', 'tpgs01', NULL, NULL, '', 'staff', '2026-10-20', '2026-10-18', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-01 08:00+03'),
 ('tpga02', 'school_visit', 'submitted_to_pl', 'tpgs05', NULL, NULL, '', 'partner', NULL, '2026-11-04', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), '2026-10-02 08:00+03'),
 ('tpga03', 'school_visit', 'scheduled', 'tpgs08', NULL, NULL, '', 'staff', NULL, '2027-01-12', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7b6a00e4s8ekhefr'), '2026-10-03 08:00+03'),
 ('tpga04', 'school_visit', 'cancelled', 'tpgs01', NULL, NULL, '', 'staff', NULL, '2026-10-25', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-04 08:00+03'),
 ('tpga05', 'follow_up_visit', 'returned_by_pl', 'tpgs09', NULL, NULL, '', 'staff', NULL, NULL, '2026-11-05 10:00+03', 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-05 08:00+03'),
 -- Core visits and trainings
 ('tpga06', 'core_visit', 'completed', 'tpgs02', NULL, NULL, '', 'staff', '2026-10-09', '2026-10-08', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-06 08:00+03'),
 ('tpga07', 'core_visit', 'ia_verified', 'tpgs02', NULL, NULL, '', 'partner', '2026-11-03', NULL, NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-07 08:00+03'),
 ('tpga08', 'core_visit', 'planned', 'tpgs02', NULL, NULL, '', 'staff', NULL, '2027-02-10', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-08 08:00+03'),
 -- trainings: Core orientation (a recruit), CC-SEL online at a Core school,
 -- teacher pedagogy at a client school, ECE with teachers, leadership with leaders
 ('tpga09', 'in_school_training', 'completed', 'tpgs06', (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zvd00u8dgeihgqm'), NULL, '', 'staff', '2026-10-22', NULL, NULL, 4, 2, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), '2026-10-09 08:00+03'),
 ('tpga10', 'in_school_training', 'awaiting_ia_verification', 'tpgs02', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zui00zapceihg6m'), 'online', 'staff', '2026-11-06', NULL, NULL, 6, 1, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-10 08:00+03'),
 ('tpga11', 'in_school_training', 'completed', 'tpgs01', (SELECT id FROM tpg_seed WHERE token = 'cmw9p6ztu007g68eihg3z'), NULL, '', 'staff', '2026-10-28', NULL, NULL, 9, 0, '', 'tpgp01', '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-11 08:00+03'),
 ('tpga12', 'training', 'completed', 'tpgs05', (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zqd0082gueihgtv'), NULL, '', 'staff', '2026-11-07', NULL, NULL, 12, 3, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), '2026-10-12 08:00+03'),
 ('tpga13', 'school_improvement_training', 'in_progress', 'tpgs03', (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zg600734ueihg0f'), NULL, '', 'staff', NULL, '2026-12-02', NULL, 0, 5, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-13 08:00+03'),
 -- a cluster meeting held as a training, at no school, with a register
 ('tpga14', 'cluster_meeting', 'completed', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zle0025h0eihgln'), NULL, '', 'staff', '2026-10-30', NULL, NULL, 10, 4, 'training', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-14 08:00+03'),
 -- an SSA review meeting at a client school
 ('tpga15', 'cluster_meeting_ssa_review', 'completed', 'tpgs08', NULL, NULL, '', 'staff', '2026-11-10', NULL, NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7b6a00e4s8ekhefr'), '2026-10-15 08:00+03'),
 -- a cluster training recorded on the legacy attended list
 ('tpga16', 'cluster_training', 'completed', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zhh00nfwoeihg2u'), NULL, '', 'staff', '2026-10-16', NULL, NULL, 7, 7, '', NULL, '{tpgs01,tpgs03,tpgs04}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-16 08:00+03'),
 -- work at no school: a District Meeting, a camp, a meeting as Cluster Leaders, partner review
 ('tpga17', 'programme_event', 'completed', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p705z00slcbeihg2k'), NULL, '', 'staff', '2026-10-21', NULL, NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-17 08:00+03'),
 ('tpga18', 'programme_event', 'planned', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p6ztj0007xxeihg3z'), NULL, '', 'staff', NULL, '2027-03-03', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), '2026-10-18 08:00+03'),
 ('tpga19', 'cluster_meeting', 'completed', NULL, NULL, NULL, '', 'staff', '2026-11-02', NULL, NULL, 0, 0, 'cluster_leaders', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7b6a00e4s8ekhefr'), '2026-10-19 08:00+03'),
 ('tpga20', 'programme_event', 'submitted_to_pl', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zs60036xueihght'), NULL, '', 'staff', '2026-11-11', NULL, NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), '2026-10-20 08:00+03'),
 -- a session invited but not attended: planned for its schools only
 ('tpga21', 'cluster_training', 'scheduled', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p6zeg00klpueihg7a'), NULL, 'online', 'staff', NULL, '2026-12-15', NULL, 0, 0, '', NULL, '{}', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), '2026-10-21 08:00+03');
INSERT INTO activity
SELECT (jsonb_populate_record(null::activity, to_jsonb(t) || jsonb_build_object(
  'id', w.id, 'activity_type', w.kind, 'fy', '2027', 'status', w.status, 'school_id', w.school,
  'catalogue_item_id', w.item, 'training_course_id', w.course, 'delivery_method_snapshot', w.method, 'delivery_type', w.delivery,
  'actual_delivery_date', w.actual, 'planned_date', w.planned, 'scheduled_date', w.scheduled,
  'teachers_attended', w.teachers, 'leaders_attended', w.leaders, 'meeting_kind', w.meeting, 'project_id', w.project,
  'attended_school_ids', to_jsonb(w.attended), 'responsible_staff_id', w.staff, 'deleted_at', NULL,
  'created_at', w.created, 'updated_at', w.created, 'salesforce_activity_id', NULL, 'paired_school_visit_id', NULL,
  'cluster_id', NULL))).*
FROM tpg_activity t, tpg_work w;

INSERT INTO cluster_activity_attendance (created_at, updated_at, invited, attended, is_guest, recorded_by, activity_id, school_id, teachers, leaders, other) VALUES
 (now(), now(), true, true, false, 'tpg', 'tpga14', 'tpgs01', 0, 0, 0),
 (now(), now(), true, true, false, 'tpg', 'tpga14', 'tpgs03', 0, 0, 0),
 (now(), now(), true, false, false, 'tpg', 'tpga14', 'tpgs08', 0, 0, 0),
 (now(), now(), true, false, false, 'tpg', 'tpga21', 'tpgs02', 0, 0, 0),
 (now(), now(), true, false, false, 'tpg', 'tpga21', 'tpgs06', 0, 0, 0);

-- ── The Core package ───────────────────────────────────────────────────────
INSERT INTO core_plan (created_at, updated_at, id, school_id, fy, status, visits_target, trainings_target, visits_completed, trainings_completed, assessment_completed) VALUES
 (now(), now(), 'tpgc01', 'tpgs02', '2027', 'active', 4, 4, 2, 1, 0),
 (now(), now(), 'tpgc02', 'TPG-006', '2027', 'active', 4, 4, 0, 1, 0);
INSERT INTO core_activity_slot (created_at, updated_at, id, school_id, intervention, activity_type, sequence_number, status, owner, core_plan_id, activity_id, completed_at) VALUES
 (now(), now(), 'tpgk01', 'tpgs02', 'leadership', 'visit', 1, 'completed', 'staff', 'tpgc01', 'tpga06', NULL),
 (now(), now(), 'tpgk02', 'tpgs02', 'leadership', 'visit', 2, 'completed', 'partner', 'tpgc01', 'tpga07', NULL),
 (now(), now(), 'tpgk03', 'tpgs02', 'leadership', 'visit', 3, 'planned', 'staff', 'tpgc01', 'tpga08', NULL),
 (now(), now(), 'tpgk04', 'tpgs02', 'leadership', 'training', 1, 'completed', 'staff', 'tpgc01', NULL, '2026-09-28 10:00+03'),
 (now(), now(), 'tpgk05', 'TPG-006', 'leadership', 'training', 1, 'completed', 'staff', 'tpgc02', 'tpga09', NULL),
 (now(), now(), 'tpgk06', 'TPG-006', 'leadership', 'visit', 1, 'closed', 'staff', 'tpgc02', NULL, '2026-10-29 10:00+03');
INSERT INTO core_school_onboarding (created_at, updated_at, id, school_id, fy, previous_school_type, baseline_ssa_record_id, baseline_average_score,
  onboarded_by_id, onboarded_by_name, onboarded_at, status, core_plan_id) VALUES
 (now(), now(), 'tpgo01', 'tpgs06', '2027', 'client', '', 0, 'tpg', 'tpg', '2026-10-22 09:00+03', 'completed', 'tpgc02');

-- ── SSAs ───────────────────────────────────────────────────────────────────
CREATE TEMP TABLE tpg_ssa ON COMMIT DROP AS SELECT * FROM ssa_record WHERE id = (SELECT id FROM tpg_seed WHERE token = 'cmw9p7xaj00derkekhe6q');
CREATE TEMP TABLE tpg_ssa_spec (id text, school text, at timestamptz, status text, score float8) ON COMMIT DROP;
INSERT INTO tpg_ssa_spec VALUES
 ('tpgq01', 'tpgs01', '2026-10-15 10:00+03', 'confirmed', 6.25),
 ('tpgq02', 'tpgs06', '2026-10-23 10:00+03', 'pending', 5.5),
 ('tpgq03', 'tpgs02', '2026-09-30 22:00+03', 'confirmed', 7.0),
 ('tpgq04', 'tpgs05', '2026-11-05 10:00+03', 'returned', 4.0),
 ('tpgq05', 'tpgs08', '2026-11-09 10:00+03', 'pending', NULL);
INSERT INTO ssa_record SELECT (jsonb_populate_record(null::ssa_record, to_jsonb(t) || jsonb_build_object(
  'id', s.id, 'school_id', s.school, 'date_of_ssa', s.at, 'fy', '2027', 'verification_status', s.status,
  'average_score', s.score, 'deleted_at', NULL, 'salesforce_id', NULL, 'source_activity_id', NULL))).*
FROM tpg_ssa t, tpg_ssa_spec s;

-- ── Evidence and enrolment ─────────────────────────────────────────────────
INSERT INTO impact_discipleship_record (created_at, updated_at, source, environment, country, fy, evidence_reference, notes, recorded_by_user_id,
  verification_status, return_reason, id, observed_on, school_id, discipleship_groups_active) VALUES
 (now(), now(), 'tpg', 'development', 'Uganda', '2027', '', '', 'tpg', 'confirmed', '', 'tpgd01', '2026-10-12', 'tpgs01', 2),
 (now(), now(), 'tpg', 'development', 'Uganda', '2027', '', '', 'tpg', 'pending', '', 'tpgd02', '2026-11-08', 'tpgs06', 0),
 (now(), now(), 'tpg', 'development', 'Uganda', '2027', '', '', 'tpg', 'confirmed', '', 'tpgd03', '2026-11-09', 'tpgs02', 1);
INSERT INTO impact_learning_result (created_at, updated_at, source, environment, country, fy, evidence_reference, notes, recorded_by_user_id,
  verification_status, return_reason, id, assessment_type, assessed_on, grade_level, subject, learners_tested, school_id) VALUES
 (now(), now(), 'tpg', 'development', 'Uganda', '2027', '', '', 'tpg', 'confirmed', '', 'tpgl01', 'onetest', '2026-10-25', 'P4', 'literacy', 30, 'tpgs03'),
 (now(), now(), 'tpg', 'development', 'Uganda', '2027', '', '', 'tpg', 'pending', '', 'tpgl02', 'national_exam', '2026-11-01', 'P7', 'all', 40, 'tpgs02');
INSERT INTO school_enrollment_history (created_at, updated_at, id, fy, enrollment, recorded_at, school_id) VALUES
 (now(), now(), 'tpge01', '2027', 300, '2026-10-02 10:00+03', 'tpgs05');

-- ── Stories ────────────────────────────────────────────────────────────────
INSERT INTO mscs_story (created_at, updated_at, id, user_id, title, narrative, story_date, status, country, intervention, outcome_area, school_id) VALUES
 (now(), now(), 'tpgm01', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7bws00c2f9ekherh'), 'Tpg one', '', '2026-10-19', 'approved', 'Uganda', '', '', 'tpgs01'),
 (now(), now(), 'tpgm02', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7bws00c2f9ekherh'), 'Tpg two', '', '2026-11-04', 'approved', 'Uganda', '', '', NULL),
 (now(), now(), 'tpgm03', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7d6600vvj2ekheu3'), 'Tpg three', '', '2026-11-05', 'submitted', 'Uganda', '', '', 'tpgs05');

-- ── The Uganda Master Priority Plan for FY 2027, its allocations and phasing ─
INSERT INTO hr_strategic_priority (created_at, updated_at, id, fy, level, title, strategic_purpose, weight_min, weight_max, is_mandatory, status, sequence,
  source_document, source_reference, source_title, version, country_id, cycle_id, code)
VALUES (now(), now(), 'tpgh01', '2027', 'country', 'Tpg Uganda Master Priorities', '', 0, 100, false, 'published', 1, '', '', '', 1, 'Uganda', (SELECT id FROM tpg_seed WHERE token = 'cmw9p70ap00h2fieihgfk'), 'TPG');
CREATE TEMP TABLE tpg_milestone (id text, code text, kind text, value numeric, core numeric, client numeric, n int) ON COMMIT DROP;
INSERT INTO tpg_milestone VALUES
 ('tpgi01', 'NEW_SCHOOLS', 'count', 50, 20, 30, 1),
 ('tpgi02', 'CLIENT_VISIT_COVERAGE', 'percentage', 90, NULL, NULL, 2),
 ('tpgi03', 'SEL_TRAINING', 'count', 100, 40, 60, 3),
 ('tpgi04', 'MSC_STORIES', 'count', 10, NULL, NULL, 4),
 ('tpgi05', 'CLIENT_SSA_COVERAGE', 'percentage', 60, NULL, NULL, 5),
 ('tpgi06', 'NEW_CORE_SCHOOLS', 'count', 5, NULL, NULL, 6),
 ('tpgi07', 'SCHOOLS_WITH_DCS', 'percentage', 50, NULL, NULL, 7),
 ('tpgi08', 'TEACHER_PEDAGOGY', 'count', 20, 0, 20, 8),
 ('tpgi09', 'ECD_TEACHERS', 'count', 0, NULL, NULL, 9);
INSERT INTO hr_priority_milestone (created_at, updated_at, id, code, title, source_text, description, milestone_type, measurement_type, progress_source,
  target_unit, target_source_text, denominator_definition, quality_gate, role_applicability, country_applicability, project_applicability,
  activity_catalogue_rules, requires_definition, definition_status, weight, active, version, source_order, priority_id, allocation_method,
  cap_at_100, confirmation_note, needs_confirmation, responsible_role, target_value, core_target, client_target)
SELECT now(), now(), id, code, code, '', '', 'output', kind, 'system', '', '', '', '', '[]', '[]', '[]', '[]', false, 'defined', 1, false, 1, n,
  'tpgh01', 'manual', false, '', false, '', value, core, client FROM tpg_milestone;
CREATE TEMP TABLE tpg_alloc (id text, milestone text, kind text, team text, employee text, allocated numeric, core numeric, client numeric) ON COMMIT DROP;
INSERT INTO tpg_alloc VALUES
 ('tpgn01', 'tpgi03', 'team', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7b6a00e4s8ekhefr'), NULL, 30, 10, 20),
 ('tpgn02', 'tpgi03', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 12, 5, 7),
 ('tpgn03', 'tpgi03', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), 9, NULL, 9),
 ('tpgn04', 'tpgi01', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 7, NULL, NULL),
 ('tpgn05', 'tpgi01', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), 9, NULL, NULL),
 ('tpgn06', 'tpgi02', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 80, NULL, NULL),
 ('tpgn07', 'tpgi04', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7c6000iqchekhe36'), 4, NULL, NULL),
 ('tpgn08', 'tpgi06', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7dez0031o9ekhee5'), 2, NULL, NULL),
 ('tpgn09', 'tpgi05', 'team', (SELECT id FROM tpg_seed WHERE token = 'cmw9p7bf200eymgekhexn'), NULL, 70, NULL, NULL),
 ('tpgn10', 'tpgi01', 'employee', NULL, (SELECT id FROM tpg_seed WHERE token = 'cmw9p7b6a00e4s8ekhefr'), 3, NULL, NULL);
INSERT INTO hr_milestone_allocation (created_at, updated_at, id, allocated_to_type, weight, allocation_reason, allocated_by, effective_date, status, version,
  milestone_id, quarter_distribution, quarter_status, component_split, team_id, employee_id, allocated_target, core_target, client_target, country_id)
SELECT now(), now(), id, kind, 1, '', 'tpg', '2026-10-01', 'approved', 1, milestone, '{}', 'draft', '{}', team, employee, allocated, core, client, 'Uganda' FROM tpg_alloc;
INSERT INTO hr_milestone_period_target (created_at, updated_at, id, scope, period_type, period_start, period_end, planned_value, actual_value, actual_source,
  achievement_percentage, status, milestone_id, allocation_id) VALUES
 (now(), now(), 'tpgt01', 'employee', 'month', '2026-10-01', '2026-10-31', 3, 0, '', 0, 'open', 'tpgi03', 'tpgn02'),
 (now(), now(), 'tpgt02', 'employee', 'month', '2026-11-01', '2026-11-30', 4, 0, '', 0, 'open', 'tpgi03', 'tpgn02'),
 (now(), now(), 'tpgt03', 'employee', 'month', '2026-12-01', '2026-12-31', 5, 0, '', 0, 'open', 'tpgi03', 'tpgn02'),
 (now(), now(), 'tpgt04', 'team', 'month', '2026-10-01', '2026-10-31', 10, 0, '', 0, 'open', 'tpgi03', 'tpgn01'),
 (now(), now(), 'tpgt05', 'employee', 'month', '2026-11-01', '2026-11-30', 2.5, 0, '', 0, 'open', 'tpgi01', 'tpgn04'),
 (now(), now(), 'tpgt06', 'employee', 'quarter', '2026-10-01', '2026-12-31', 9, 0, '', 0, 'open', 'tpgi01', 'tpgn05');

-- ── Country targets IA set ─────────────────────────────────────────────────
INSERT INTO country_report_target (created_at, updated_at, id, fy, key, annual_target, monthly_targets, set_by_user_id, set_by_role) VALUES
 (now(), now(), 'tpgr01', '2027', 'teacher_pedagogy', 25, '{"1": "10.00", "2": "15.00", "3": "0.00", "4": "0.00", "5": "0.00", "6": "0.00", "7": "0.00", "8": "0.00", "9": "0.00", "10": "0.00", "11": "0.00", "12": "0.00"}', 'tpg', 'ImpactAssessment'),
 (now(), now(), 'tpgr02', '2027', 'strategic:schools-with-dc-discipleship-curriculum-rollout-core', 40, NULL, 'tpg', 'Admin'),
 (now(), now(), 'tpgr03', '2027', 'core_visit_1', 12.5, NULL, 'tpg', 'ImpactAssessment');

COMMIT;
