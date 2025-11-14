# Drift Resolution Checklist

Mark each item with `[x]` once you decide whether to update the constitution or
realign the implementation. Add any notes under the corresponding section.

## 1. CLI Direct-to-MySQL Access
- [ ] Accept drift: update constitution to permit CLI ↔ MySQL connections.
- [X ] Reject drift: restore CLI → API HTTP flow (no direct database access).
- Notes:
  - 

## 2. Schema Location vs Constitution
- [X ] Accept drift: amend constitution to recognize `schema/pulldb/*.sql` as the
      canonical migration format.
- [ ] Reject drift: move numbered SQL files into `migrations/` (or equivalent)
      to comply with existing mandate.
- Notes:
  - 

## 3. Default Host / Secret Definition
- [X ] Accept drift: update constitution to document `localhost` default and
      `/pulldb/mysql/db-local-dev` secret.
- [ ] Reject drift: revert seeds/config/docs to legacy SUPPORT default described
      in current constitution.
- Notes:
  - 

## Additional Items
Add further drift decisions here as they arise.
- [ ] Item:
- Notes:
  - 
