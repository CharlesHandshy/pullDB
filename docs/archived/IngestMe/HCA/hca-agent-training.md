# HCA Agent Training & Validation System

**Version**: 2.0.0  
**Purpose**: Training exercises and validation tests for HCA with MAP principles

---

## Part 1: Foundation Training (Structural)

### Exercise 1.1: Layer Identification

For each component description, identify the correct layer.

| Component | Your Answer | Correct Layer |
|-----------|-------------|---------------|
| A reusable "Save" button | ___ | shared |
| Character hit points data model | ___ | entities |
| "Transfer gold to party member" action | ___ | features |
| Complete inventory panel with grid, filters, actions | ___ | widgets |
| The Game Table page | ___ | pages |
| Date formatting utility | ___ | shared |
| Spell preparation action | ___ | features |
| Item entity with properties | ___ | entities |
| Character sheet sidebar widget | ___ | widgets |
| Generic text input field | ___ | shared |

**Validation**: Score 10/10 required to proceed.

---

### Exercise 1.2: Dependency Direction

Mark each dependency as VALID or INVALID.

| From | To | Valid? |
|------|----|--------|
| pages/gametable/ | widgets/inventory-panel/ | ___ |
| widgets/inventory-panel/ | features/add-item/ | ___ |
| features/add-item/ | entities/item/ | ___ |
| entities/item/ | shared/utils/formatters/ | ___ |
| shared/ui/buttons/ | features/inventory/ | ___ |
| features/spell-cast/ | widgets/spell-panel/ | ___ |
| widgets/character-sheet/ | entities/character/ | ___ |
| entities/character/ | pages/character-page/ | ___ |

**Correct Answers**:

1. VALID - pages can use widgets
2. VALID - widgets can use features
3. VALID - features can use entities
4. VALID - entities can use shared
5. INVALID - shared cannot use features (upward dependency)
6. INVALID - features cannot use widgets (upward dependency)
7. VALID - widgets can use entities
8. INVALID - entities cannot use pages (upward dependency)

**Validation**: Score 8/8 required to proceed.

---

### Exercise 1.3: Path Reading

Read each path and write what you understand about the component.

**Path 1**: `/shared/ui/buttons/icon-button/IconButton.php`

Expected understanding:

- Layer: Shared (universal, no domain knowledge)
- Category: UI component
- Type: Button
- Variant: Icon-based button
- This is a reusable button that displays an icon, usable anywhere

**Path 2**: `/features/inventory-management/item-transfer/transfer-validator/TransferValidator.php`

Expected understanding:

- Layer: Features (user action)
- Domain: Inventory management
- Feature: Item transfer between locations/characters
- Sub-component: Validation logic for transfers
- This validates that a transfer operation is allowed

**Path 3**: `/widgets/spell-panel/spell-list/spell-list-item/SpellListItem.php`

Expected understanding:

- Layer: Widgets (self-contained UI block)
- Widget: Spell panel
- Sub-widget: List of spells
- Atom: Individual spell item in the list
- This renders one spell entry in a spell list within the spell panel

---

## Part 2: Decision Training (Structural)

### Exercise 2.1: Where Does This Go?

For each requirement, provide the full path where the code should be created.

**Requirement 1**: "A dropdown select input that can be used anywhere"

```text
Your answer: ___
Correct: /shared/ui/inputs/select-dropdown/SelectDropdown.php
```

**Requirement 2**: "Logic to calculate a character's armor class"

```text
Your answer: ___
Correct: /entities/character/character-stats/armor-class-calculator/ArmorClassCalculator.php
```

**Requirement 3**: "The action of adding a spell to a character's spellbook"

```text
Your answer: ___
Correct: /features/spell-management/add-to-spellbook/AddToSpellbookController.php
```

**Requirement 4**: "A complete party management panel showing all party members with actions"

```text
Your answer: ___
Correct: /widgets/party-panel/PartyPanel.php (coordinator)
         /widgets/party-panel/party-member-list/
         /widgets/party-panel/party-actions/
```

**Requirement 5**: "The LFG search results page"

```text
Your answer: ___
Correct: /pages/lfg/lfg-search-results/LfgSearchResultsPage.php
```

---

### Exercise 2.2: Refactoring Decisions

A file has grown too large. Determine how to split it.

**Scenario**: `InventoryGrid.php` is 480 lines containing:

- Grid rendering (150 lines)
- Item sorting logic (120 lines)
- Item filtering logic (130 lines)
- Drag-drop handling (80 lines)

**Your refactoring plan**:

```text
Current:
widgets/inventory-panel/inventory-grid/InventoryGrid.php (480 lines)

Refactored to:
widgets/inventory-panel/inventory-grid/
  └── InventoryGrid.php (100 lines - coordinator)
  └── grid-renderer/
        └── GridRenderer.php (150 lines)
  └── grid-sorting/
        └── GridSorter.php (120 lines)
  └── grid-filtering/
        └── GridFilter.php (130 lines)
  └── grid-interactions/
        └── DragDropHandler.php (80 lines)
```

---

### Exercise 2.3: Anti-Pattern Recognition

Identify what's wrong with each structure.

**Structure 1**:

```text
components/
  └── Button.php
  └── Input.php
  └── InventoryGrid.php
  └── CharacterSheet.php
```

**Problems**:

1. Flat structure with no hierarchy
2. Mixed levels (atoms and organisms together)
3. No categorical organization
4. Path tells you nothing about relationships

**Structure 2**:

```text
features/
  └── inventory/
        └── utils/
              └── helpers.php
              └── common.php
```

**Problems**:

1. Generic names (utils, helpers, common)
2. Not clear what these files contain
3. Likely a junk drawer for miscellaneous code
4. Should be split into specific, named atoms

**Structure 3**:

```text
shared/ui/buttons/PrimaryButton.php
shared/ui/buttons/SecondaryButton.php
shared/ui/buttons/IconButton.php
```

**Problems**:

1. Files directly in container directory (no component subdirectory)
2. Should be:
   - shared/ui/buttons/primary-button/PrimaryButton.php
   - shared/ui/buttons/secondary-button/SecondaryButton.php
   - shared/ui/buttons/icon-button/IconButton.php

---

## Part 3: Behavioral Training (MAP)

### Exercise 3.1: Interface Design

For each scenario, determine if an interface is needed and design it.

**Scenario 1**: "Add item to inventory" feature

```php
// Should this feature have an interface? YES
// Why? It's a public feature that may be called by multiple widgets

interface AddItemInterface {
    public function execute(ItemData $item, ContainerId $destination): Result;
    public function validate(ItemData $item): ValidationResult;
    public function canExecute(UserId $user): bool;
}
```

**Scenario 2**: Private helper function to format currency

```php
// Should this have an interface? NO
// Why? It's an internal implementation detail, not a public contract
```

**Scenario 3**: Database repository for items

```php
// Should this have an interface? YES
// Why? Data access should be swappable (testing, different databases)

interface ItemRepositoryInterface {
    public function find(int $id): ?Item;
    public function findByContainer(ContainerId $containerId): array;
    public function save(Item $item): void;
    public function delete(int $id): void;
}
```

---

### Exercise 3.2: Event Design

Determine which events should be emitted for each feature.

**Feature**: Sell Item to Vendor

```text
Events that should be emitted:
1. item.sold - When sale is complete
   Payload: { item, vendor, price, seller }
   
2. gold.received - When gold is added
   Payload: { amount, source: 'vendor_sale', userId }
   
3. inventory.updated - When item is removed
   Payload: { containerId, action: 'remove', itemId }

Who might listen?
- Achievement system (track items sold, gold earned)
- Audit log (record all transactions)
- Notification system (confirm sale to user)
- Analytics (track economy)
```

**Feature**: Cast Spell

```text
Events that should be emitted:
1. spell.cast - When spell is successfully cast
   Payload: { spell, caster, target, result }

2. spell-slot.consumed - When a spell slot is used
   Payload: { caster, level, remaining }

Who might listen?
- Combat tracker (apply spell effects)
- Character sheet (update spell slots)
- Achievement system (track spells cast)
- Session log (record actions)
```

---

### Exercise 3.3: Configuration Identification

Identify what should be configurable in each component.

**Component**: Inventory Grid

```php
// inventory-grid.config.php
return [
    'max_items_per_page' => 50,        // Configurable
    'default_sort_field' => 'name',    // Configurable
    'default_sort_order' => 'asc',     // Configurable
    'enable_drag_drop' => true,        // Feature flag
    'show_item_weight' => true,        // Display option
    'grid_columns' => 5,               // Layout option
];

// NOT configurable (implementation details):
// - How sorting algorithm works
// - Database query structure
// - Internal variable names
```

**Component**: Item Transfer Feature

```php
// item-transfer.config.php
return [
    'enabled' => true,                    // Feature toggle
    'require_confirmation' => true,       // UX option
    'max_items_per_transfer' => 10,       // Limit
    'allow_cross_character' => true,      // Permission
    'weight_limit_enforcement' => 'warn', // 'warn', 'block', 'ignore'
    'notify_recipient' => true,           // Notification flag
];
```

---

### Exercise 3.4: Plugin Hook Points

Identify where plugins should be able to hook in.

**Feature**: Add Item to Inventory

```text
Filter hooks (modify data):
1. 'item.before_add' - Modify item data before adding
   Use: Premium plugin adds custom properties

2. 'item.after_validate' - Modify validation result
   Use: VIP plugin bypasses weight restrictions

3. 'item.price_calculation' - Modify calculated price
   Use: Merchant plugin applies discounts

Action hooks (side effects):
1. 'item.added' - React after item added
   Use: Achievement plugin checks for milestones

2. 'item.validation_failed' - React to validation failure
   Use: Tutorial plugin shows helpful message
```

---

## Part 4: Integration Testing (Combined)

### Test 3.1: Complete Feature Implementation

**Task**: Implement "Sell Item to Vendor" feature

**Required Output**:

```text
ANALYSIS:
- This is a user action → features/
- Domain: inventory management → features/inventory-management/
- Specific action: selling → features/inventory-management/sell-item/

DEPENDENCY ANALYSIS:
- Needs: Item entity (entities/item/)
- Needs: Gold/currency entity (entities/currency/)
- Needs: Vendor entity (entities/vendor/)
- Needs: Form UI atoms (shared/ui/)
- Provides: Sell action for widgets to use

INTERFACE DESIGN (MAP):
- SellItemInterface - public contract for this feature
- Depends on: ItemRepositoryInterface, EventDispatcherInterface

EVENT DESIGN (MAP):
- Emits: ItemSoldEvent, GoldReceivedEvent
- Listeners: AchievementTracker, AuditLogger, NotificationService

CONFIGURATION (MAP):
- sell-item.config.php with feature flags and limits

STRUCTURE:
features/inventory-management/sell-item/
  └── SellItemController.php           # Main coordinator (150 lines)
  └── SellItemInterface.php            # Public contract (MAP)
  └── sell-item.config.php             # Configuration (MAP)
  └── events/                          # Domain events (MAP)
        └── ItemSoldEvent.php
  └── sell-item-form/
        └── SellItemForm.php           # Form rendering (100 lines)
        └── sell-item-form.css
        └── sell-item-form.js
  └── sell-item-validation/
        └── SellItemValidator.php      # Validation rules (80 lines)
        └── validation-rules/
              └── ItemSellableRule.php
              └── VendorAcceptsRule.php
              └── PriceCalculationRule.php
  └── sell-item-transaction/
        └── SellTransaction.php        # Transaction logic (100 lines)

DEPENDENCIES (all valid - same layer or below):
require_once '/entities/item/item-data/ItemModel.php';
require_once '/entities/currency/gold/GoldModel.php';
require_once '/entities/vendor/vendor-data/VendorModel.php';
require_once '/shared/ui/buttons/submit-button/SubmitButton.php';
require_once '/shared/ui/inputs/number-input/NumberInput.php';
require_once '/shared/contracts/repositories/ItemRepositoryInterface.php';
require_once '/shared/contracts/events/EventDispatcherInterface.php';
```

---

### Test 3.2: Widget Composition

**Task**: Create the Inventory Panel widget

**Required Output**:

```text
ANALYSIS:
- Self-contained UI block → widgets/
- Contains multiple sub-components that work together
- Orchestrates features from below

STRUCTURE:
widgets/inventory-panel/
  └── InventoryPanel.php               # Widget coordinator
  └── inventory-panel.css              # Panel-level styles
  └── inventory-header/
        └── InventoryHeader.php
        └── inventory-header.css
  └── inventory-grid/
        └── InventoryGrid.php
        └── inventory-grid.css
        └── inventory-grid.js
        └── grid-item/
              └── GridItem.php
              └── grid-item.css
  └── inventory-filters/
        └── InventoryFilters.php
        └── inventory-filters.css
        └── inventory-filters.js
  └── inventory-actions/
        └── InventoryActions.php
        └── inventory-actions.css

COORDINATOR CONTENT (InventoryPanel.php):
```

```php
<?php
class InventoryPanel {
    public function __construct(private array $config = []) {}
    
    public function render(array $items): string {
        // Compose from children and features
        $header = (new InventoryHeader())->render();
        $filters = (new InventoryFilters())->render();
        $grid = (new InventoryGrid())->render($items);
        $actions = (new InventoryActions())->render();
        
        return $this->template($header, $filters, $grid, $actions);
    }
    
    private function template(...$components): string {
        // Assemble components into panel HTML
    }
}
```

```php
DEPENDENCIES:
// Children (within this widget)
require_once __DIR__ . '/inventory-header/InventoryHeader.php';
require_once __DIR__ . '/inventory-grid/InventoryGrid.php';
require_once __DIR__ . '/inventory-filters/InventoryFilters.php';
require_once __DIR__ . '/inventory-actions/InventoryActions.php';

// Features (from layer below)
require_once __DIR__ . '/../../features/inventory-management/item-filter/ItemFilterController.php';
require_once __DIR__ . '/../../features/inventory-management/add-item/AddItemController.php';

// Entities (from layer below)
require_once __DIR__ . '/../../entities/item/item-data/ItemModel.php';
```

---

## Part 5: Validation Exam

### Final Exam: 25 Questions

Score 25/25 to achieve HCA v2.0 Agent certification.

1. What is the deepest level of a directory tree?
   - [ ] Containers
   - [x] Atoms (files that do actual work)

2. Dependencies flow in which direction?
   - [x] Downward only (to same layer or below)
   - [ ] Upward only
   - [ ] Any direction

3. A component in shared/ can import from features/?
   - [ ] Yes
   - [x] No (shared is below features)

4. What type of names are prohibited?
   - [x] utils, helpers, common, misc, base
   - [ ] Descriptive specific names

5. Where does a reusable loading spinner belong?
   - [x] shared/ui/
   - [ ] features/
   - [ ] widgets/

6. A 500-line file should be:
   - [ ] Left as is
   - [x] Split into a container with atomic subdivisions

7. Files should be placed directly in categorical directories (e.g., /atoms/Button.php)?
   - [ ] Yes
   - [x] No (should be /atoms/buttons/button/Button.php)

8. The path /features/spell-casting/prepare-spell/PrepareSpellController.php tells us:
   - [x] A feature for spell casting, specifically preparation, this is the controller
   - [ ] Nothing useful

9. An entity knows about:
   - [ ] The widgets that display it
   - [ ] The features that use it
   - [x] Only its own data and shared utilities

10. A widget can import from:
    - [x] Features, entities, shared
    - [ ] Pages, widgets, features
    - [ ] Only shared

11. When code is needed in multiple places, you should:
    - [ ] Copy it to each location
    - [x] Put it in the appropriate shared location and reference it

12. A coordinator file should:
    - [ ] Contain all implementation logic
    - [x] Orchestrate atoms/children, minimal implementation

13. Directory names should be:
    - [x] lowercase-kebab-case
    - [ ] PascalCase
    - [ ] camelCase

14. The six layers in order from bottom to top:
    - [x] shared → entities → features → widgets → pages → plugins
    - [ ] atoms → molecules → organisms → templates → pages

15. A character's HP display component belongs in:
    - [ ] shared/ui/
    - [x] entities/character/character-display/
    - [ ] features/

16. The action "equip item" belongs in:
    - [ ] entities/item/
    - [x] features/inventory-management/ or features/equipment-management/
    - [ ] widgets/

17. A container that has no coordinator file is:
    - [ ] Correct
    - [x] Missing its assembly point (should have index/coordinator)

18. Changes to a shared atom should:
    - [x] Automatically reflect everywhere it's used
    - [ ] Require manual updates in each location

19. The correct response to "add filter to inventory" is:
    - [ ] Add filter code to InventoryPanel.php
    - [x] Create features/inventory-management/item-filter/ and compose into widget

20. Reading a file path should tell you:
    - [ ] Just the file name
    - [x] What the component does, what contains it, how it relates to others

21. Law 6 states that modules communicate through:
    - [ ] Direct instantiation of classes
    - [ ] Global variables
    - [x] Contracts (interfaces and events)

22. When should a feature emit an event?
    - [ ] Never, use direct function calls
    - [x] When other parts of the system should know something happened
    - [ ] Only for errors

23. Configuration files should contain:
    - [ ] Business logic and implementation
    - [x] Settings, feature flags, and externalized values
    - [ ] Database credentials only

24. The correct place for interface definitions is:
    - [x] shared/contracts/ for global, or with implementation for feature-specific
    - [ ] In the same file as the implementation
    - [ ] Never use interfaces

25. Plugin hooks should be defined:
    - [ ] By plugins themselves
    - [x] By the core system at appropriate extension points
    - [ ] Only in configuration files

---

## Certification

Upon scoring 25/25 on the Final Exam:

**The HCA v2.0 Agent is certified to:**

- Design new features following HCA structural principles
- Design interfaces and events following MAP behavioral principles
- Refactor existing code toward HCA compliance
- Review code for HCA/MAP violations
- Train other agents/developers on HCA v2.0

**The HCA v2.0 Agent commits to:**

- Never create files in wrong layers
- Never create upward dependencies
- Never use generic names
- Always split oversized files
- Always compose rather than duplicate
- Always make paths tell the story
- Always define interfaces for public features
- Always emit events for cross-feature communication
- Always externalize configuration
- Always provide hook points for extensibility

---

## Quick Reference Card

```text
┌─────────────────────────────────────────────────────────────┐
│                 HCA v2.0 QUICK REFERENCE                    │
├─────────────────────────────────────────────────────────────┤
│ LAYERS (bottom to top):                                     │
│   shared → entities → features → widgets → pages → plugins  │
│                                                             │
│ THE SIX LAWS:                                               │
│   1. Atoms at the bottom                                    │
│   2. Containers only contain                                │
│   3. Dependencies flow down                                 │
│   4. Names tell the story                                   │
│   5. Single source of truth                                 │
│   6. Modules communicate through contracts                  │
│                                                             │
│ STRUCTURAL (WHERE):                                         │
│   layer/domain/feature/component/Component.php              │
│   Atoms at bottom, containers going up                      │
│   Every container has coordinator file                      │
│                                                             │
│ BEHAVIORAL (HOW):                                           │
│   Features expose interfaces                                │
│   Cross-feature communication via events                    │
│   Configuration externalized in .config.php                 │
│   Plugins via hook registry                                 │
│                                                             │
│ FILE LIMITS:                                                │
│   Atoms: 200 lines ideal, 300 max                           │
│   Coordinators: 300 lines ideal, 400 max                    │
│   Total component: 500 lines max                            │
│                                                             │
│ NAMING:                                                     │
│   Directories: lowercase-kebab-case                         │
│   PHP Classes: PascalCase                                   │
│   CSS/JS: match-component-name                              │
│   NEVER: utils, helpers, common, misc, base                 │
│                                                             │
│ NEW FILE TYPES (MAP):                                       │
│   ComponentInterface.php - Contract                         │
│   component.config.php - Configuration                      │
│   events/*.php - Domain events                              │
│                                                             │
│ MANTRA:                                                     │
│   "The path tells the story"                                │
│   "Compose, never duplicate"                                │
│   "Dependencies flow down"                                  │
│   "Modules communicate through contracts"                   │
└─────────────────────────────────────────────────────────────┘
```
