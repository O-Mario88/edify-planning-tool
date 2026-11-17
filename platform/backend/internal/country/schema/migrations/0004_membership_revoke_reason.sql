-- Membership management (docs/migration/80-multi-country-phase-0.md, §10):
-- a revoked membership keeps why it was revoked beside who revoked it and
-- when, as a grant keeps its reason. A revocation without a reason is
-- refused by the table, not only by the API.
ALTER TABLE country_registry.country_membership ADD COLUMN revoke_reason text;
ALTER TABLE country_registry.country_membership ADD CONSTRAINT country_membership_revoke_reason
  CHECK ((revoked_at IS NULL) = (revoke_reason IS NULL) AND revoke_reason <> '');
