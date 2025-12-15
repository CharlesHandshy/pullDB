# Appendix C — Icon Inventory

> 101 unique icons, 354 instances across 43 files.

---

## Shared Layer (~15 icons)
Infrastructure icons.

| Icon | Description | Used In |
|------|-------------|---------|
| `database` | Ellipse + vertical lines | Hosts, restore, jobs |
| `server` | Rect + horizontal lines | Host management |
| `cloud` | Cloud shape | S3/backup references |
| `folder` | Folder shape | Directory paths |
| `globe` | Circle + meridians | External links |
| `cog` | Gear | Settings, config |

---

## Entities Layer (~16 icons)
Data model icons.

| Icon | Description | Used In |
|------|-------------|---------|
| `user` | Circle + body | User badges, profile |
| `users-group` | 2 users + circle | Team, manager views |
| `key` | Key shape | Password, API keys |
| `lock` | Padlock | Security, password |
| `shield` | Shield | Admin, audit |
| `layers` | 3 stacked paths | Logo, branding |

---

## Features Layer (~18 icons)
Business logic icons.

| Icon | Description | Used In |
|------|-------------|---------|
| `search` | Circle + line | Search inputs |
| `download` | Arrow down + line | Export, download |
| `trash` | Trash can | Delete, cleanup |
| `eye` | Ellipse + circle | View details |
| `edit-pen` | Pen/pencil | Edit actions |
| `refresh` | Circular arrow | Restore, retry |
| `plus` | + shape | Add actions |
| `minus` | - shape | Remove actions |
| `check` | Checkmark | Success, confirm |
| `x-mark` | X shape | Cancel, error |
| `lightning` | Bolt | Quick actions |
| `clock` | Circle + hands | Time, duration |

---

## Widgets Layer (~20 icons)
UI component icons.

| Icon | Description | Used In |
|------|-------------|---------|
| `chevron-down` | V down | Dropdowns |
| `chevron-up` | V up | Collapse |
| `chevron-right` | > arrow | Expand |
| `chevron-left` | < arrow | Back |
| `sort` | Up/down arrows | Table headers |
| `close` | X in circle | Modals |
| `spinner` | Partial circle | Loading |
| `check-circle` | Check in circle | Success |
| `warning` | Triangle + ! | Warnings |
| `info` | Circle + i | Tooltips |
| `hamburger` | 3 lines | Mobile menu |
| `dots-vertical` | 3 dots | More menu |

---

## Pages Layer (~12 icons)
Navigation icons.

| Icon | Description | Used In |
|------|-------------|---------|
| `dashboard` | 4-square grid | Dashboard nav |
| `document-stack` | Doc + lines | Jobs nav |
| `home` | House | Error page |
| `logout` | Door + arrow out | Logout |
| `login` | Arrow + door in | Login |
| `sun` | Circle + rays | Light mode |
| `moon` | Crescent | Dark mode |
| `external-link` | Arrow + box | External |

---

## Unknown (40 icons)

**Action Required in PR 0**: Manually review and categorize.

Run audit to see:
```bash
python3 scripts/audit_inline_svgs.py | grep -A5 "Unknown"
```
