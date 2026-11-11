# 9. Accounts and roles, owned by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "User creation, invitations and account lifecycle. Roles and
permission management." Second piece of that brief, after
[sign-in](08-sign-in.md).

## 9.1 What moved

`platform/proto/edify/identity/v1/accounts.proto`, served by
`platform/backend/internal/accounts`, behind the normal session check.

**The person's own account** (`AccountService`):

| Procedure | Existing rule it ports |
|---|---|
| `SwitchRole` | `frontend/views/auth_views.switch_role_view`: only a held role; saved on the account and audited (`role_switch`), so a renewed session stays in it; a refused switch audited with its reason |
| `SetNewPassword` | `force_change_password_view` and `accounts/middleware.py`: a password an administrator chose is replaced before anything else |

While a new password is owed, the gateway refuses every call except reading
the session and setting it (`PASSWORD_CHANGE_REQUIRED`), as the web holds a
person on its change-password page. The existing API never applied this, so
an app sign-in with an administrator's password went straight in; it no
longer does.

**Account administration** (`AccountAdminService`, `user.manage`: the Admin
alone, owner 2026-10-09):

| Procedure | Existing rule it ports (apps/admin_users/services.py) |
|---|---|
| `ListAccounts`, `GetAccount` | `list_users`, paged, searchable, with the invitation's and lock's state |
| `CreateAccount` | `create`: the account, its staff profile (title = role), its districts, and an invitation or a first password that must be changed; the existing emails |
| `UpdateAccount` | `update_user`: name, email, phone, roles; nobody changes their own role; only an Admin grants Admin or touches an Admin; never Admin and CCEO together; the staff profile's title follows |
| `ResendInvitation`, `RevokeInvitation` | `resend_invite`, `revoke_invite` |
| `SetAccountStatus` | `suspend`, `disable`, `reactivate`: closing an account ends its sessions and revokes its open invitation |
| `SendPasswordReset` | `force_password_reset`: a 45-minute link, and every session ended now |
| `SetTemporaryPassword` | `set_temporary_password`: must be changed, sessions ended, lock lifted |
| `UnlockAccount` | `AuthenticationLockoutService.admin_unlock` |
| `DeleteAccount` | `delete_user`: soft delete, address freed, staff profile tombstoned; never yourself, never the last active Admin |

The role → permission matrix is the existing `ROLE_PERMISSIONS`, exported to
`platform/backend/internal/rbac/role_permissions.json` by
`manage.py export_rbac_matrix`; `apps/core/test_rbac_matrix_export.py` fails
when the two differ, so Go never checks a different matrix.

Two deliberate differences, both stricter:

- **Resend invitation** is offered only for an account still waiting on its
  first password. The existing code would also turn an active account back
  into an invited, inactive one.
- **Closing an account** revokes its invitation in the same transaction as
  the closure. The existing code revoked it before checking whether the
  caller was allowed to close the account.

## 9.2 What still happens in the existing application

Two consequences of an account change belong to parts that have not moved.
Go posts the event server to server (`POST /api/auth/internal/account-events`,
internal key; `apps/accounts/account_event_relay.py`), and the existing code
does exactly what it does after a web change:

- **`roles_changed`**: the person's open planned days are re-priced at their
  new post (`_reprice_planned_days`).
- **`account_deleted`**: an organisation whose login it was goes back to be
  set up again (audited `admin.partner_login_released`), and the person's web
  sessions end.

The supervisor and managed-people settings (`supervisor_service`) moved to
Go next, as their own Actions on each row:
[10-teams.md](10-teams.md). Add user still creates the account without a
supervisor; one is set from the row's Supervisor action afterwards.

## 9.3 The app

- **More → Work as**: the roles the account holds, the current one ticked.
  Choosing one switches the whole app (menu, bottom tabs, screens).
- **Password Change Required**: the web's card and words, before anything
  else.
- **Users** (Admin, from the web's own `/admin-panel/users` menu link): search,
  status filter, one Actions menu per row (Configure, Reset password, Resend /
  Revoke invitation, Unlock, Deactivate / Activate, Remove account), and Add
  user as a platform drawer — the owner's 2026-10-09 rules.

## 9.4 What the database role may do

`platform/deploy/db/identity_roles.sql` now also grants account
administration: inserting accounts, staff profiles, district assignments and
invitations; updating an account's name, email, phone, roles, active role,
status and the must-change flag; soft deletion. Still refused, and proven
(`TestGatewayRoleCanNeitherWriteNorReadSecrets`): making an existing account
a superuser or staff, enrolling a second factor, changing an id, deleting an
account or session, rewriting or deleting an audit row.

One residual: the `"user"` table gives `is_superuser` and `is_staff` no
database default, so inserting an account requires inserting those columns.
The gateway always writes `false` (`TestTheAdminInvitesAnAccountThatSetsItsOwnPassword`
checks it), and can never update either flag afterwards. A database default
or check constraint would close this fully; that is a schema change and needs
the owner's approval.
