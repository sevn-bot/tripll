# EARS acceptance criteria (specs only)

Use this pattern in **`about-sevn.bot/specs/`** — not in PRDs. PRDs carry product intent
(`FR-`, `UJ-`, `KPI-`); specs carry normative, testable **shall** statements for engineering
and the tests-first wave model.

## GEARS clause order (recommended)

```
[Where <static precondition>]
[While <stateful precondition>]
[When <trigger>]
The <subject> shall <behavior>.
```

Map to Given-When-Then tests:

| GWT | GEARS clause |
| --- | --- |
| Given | Where + While |
| When | When |
| Then | shall |

## EARS patterns (pick one per requirement)

| Pattern | Template |
| --- | --- |
| Ubiquitous | The `<subject>` shall `<behavior>`. |
| Event-driven | When `<trigger>`, the `<subject>` shall `<behavior>`. |
| State-driven | While `<state>`, the `<subject>` shall `<behavior>`. |
| Unwanted | If `<condition>`, then the `<subject>` shall `<behavior>`. |
| Optional | Where `<feature>`, the `<subject>` shall `<behavior>`. |

## Spec section placement

In each spec user story or behavior subsection:

```markdown
### Requirement: Session timeout

When the operator is idle for 30 minutes, the gateway shall invalidate the web session.

#### Scenario: Idle logout

- **Given** an authenticated Mission Control session
- **When** 30 minutes pass without activity
- **Then** the session is invalidated and the login screen is shown
```

## OpenSpec brownfield updates

When a wave changes an existing spec, append a row to the PRD **Change Log** (delta token +
spec id + section), then edit the spec using delta sections:

```markdown
## MODIFIED Requirements

### Requirement: Session timeout

When the operator is idle for 45 minutes, the gateway shall invalidate the web session.
```

Archive merges MODIFIED/ADDED/REMOVED into the canonical spec body after the wave lands.

## Validation

- PRD files: `make prd-validate PRD=…`
- Spec EARS lint (optional): adopt [vale-ears](https://github.com/tbhb/vale-ears) in docs CI
  when specs gain formal shall-statements at scale.
