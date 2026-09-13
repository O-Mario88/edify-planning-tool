// The role accounts `manage.py seed --demo` creates, one per role the page
// inventory knows: [account role, inventory role, email].
const localRoleAccounts = [
  ['CCEO', 'CCEO', 'cceo@edify.org'],
  ['PL', 'PL', 'pl1@edify.org'],
  ['CD', 'CD', 'cd@edify.org'],
  ['RVP', 'RVP', 'rvp@edify.org'],
  ['IA', 'IA', 'ia@edify.org'],
  ['ACCOUNTANT', 'ACCOUNTANT', 'accountant@edify.org'],
  ['HR', 'HR', 'hr@edify.org'],
  ['PROJECT_COORDINATOR', 'PROJECT_COORDINATOR', 'coordinator@edify.org'],
  ['PARTNER_ADMIN', 'PARTNER', 'partner-admin@edify.org'],
  ['PARTNER', 'PARTNER', 'partner@edify.org'],
  ['BUSINESS_TRANSFORMATION', 'BUSINESS_TRANSFORMATION', 'business-transformation@edify.org'],
  ['MFI_ADMIN', 'MFI_ADMIN', 'mfi-admin@edify.org'],
  ['MFI_OFFICER', 'MFI_OFFICER', 'mfi-officer@edify.org'],
  ['ADMIN', 'ADMIN', 'admin@edify.org'],
];

// A server on this machine is a disposable seeded database (CI's job, or a
// developer's own). Anything else is a shared deployment whose agreements are
// not ours to accept.
function isDisposableTarget(baseURL) {
  return ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(baseURL).hostname);
}

module.exports = { localRoleAccounts, isDisposableTarget };
