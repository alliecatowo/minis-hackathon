# ADR 002: Canonical Subject, Scoped Projections, and Access Semantics

## Status
Proposed

## Context
Minis needs one identity model that works across review prediction, memory
retrieval, assistant prompting, and future team-aware surfaces.

The recent audit surfaced a recurring failure mode: the system can collect a lot
of evidence about a person, but then blur together four different concerns:

- who the subject is
- what slice of that subject is relevant in a given repo or team context
- who is asking, and what they are allowed to see
- which version of the subject model is being used

When those are conflated, the product gets brittle. Repo-local behavior leaks
into global identity, team-level norms get mistaken for personal beliefs, and
different surfaces disagree because they are implicitly using different slices
of the same person.

This ADR codifies the intended model.

## Decision

Minis will use a single canonical subject per person, and every product surface
will read that subject through an explicit scoped projection.

The five independent axes are:

1. `canonical_subject`
   The durable identity anchor for a real person.

2. `scope`
   The context boundary that determines which evidence is relevant.

3. `perspective`
   The reader role or use case that determines how the subject should be
   rendered.

4. `visibility`
   The access rule that determines whether the current reader may see the data
   at all.

5. `version`
   The exact model snapshot or extraction snapshot being used.

These are separate concepts and must not be collapsed into one field.

## Core Terms

### Canonical subject

The canonical subject is the stable, system-wide identity for a person.

Rules:

- there is exactly one canonical subject per real person
- all subject data attaches to that identity, even if it was observed in a
  specific repo or team
- the canonical subject is not a view, not a repo clone, and not a prompt
  wrapper

### Scoped projection

A scoped projection is a derived view of the canonical subject for a specific
use case.

A projection answers: "show me this subject as it matters here."

Examples:

- `subject + repo scope` for review prediction in one repository
- `subject + team container` for cross-repo norms shared by an org team
- `subject + author perspective` for relationship-aware feedback tone
- `subject + version pin` for reproducible evals

Projections are derived, never primary.

### Perspective

Perspective is the reading stance.

It describes who is asking and what their role implies:

- reviewer
- author
- teammate
- admin
- evaluator

Perspective affects formatting, detail level, and what is surfaced, but it does
not rewrite the underlying subject.

### Access semantics

Access semantics decide whether a perspective may read a given fact, and at
what fidelity.

Visibility is a data property. Access is an evaluation against the current
reader.

Example:

- a fact may be `private`
- the current reader may still be authorized to see it
- the same fact may render differently for an author, a teammate, and an eval
  job

## Scope Model

Minis must distinguish the following scope types.

### Repo scope

Repo scope is the narrowest operational scope.

It includes:

- repository conventions
- repo-specific review history
- local architectural precedents
- domain language used in that codebase

Repo scope should be used when answering questions like:

- "What would this person block on in this repo?"
- "Which repo precedent applies here?"
- "What does this subject care about in this codebase?"

Repo scope is not a whole identity. It is a slice of the subject under a repo
boundary.

### Team container

A team container is a higher-level grouping that can span multiple repos or
surfaces.

It includes:

- shared engineering norms
- common review policy
- cross-repo terminology
- organizational context that applies across a team boundary

Team containers are useful when a person behaves consistently across several
repos, or when a team has shared conventions that should inherit into each
repo's projection.

Team container data may inform a repo projection, but it must not overwrite
repo-specific evidence.

### Visibility

Visibility is an access label on a record, fact, or edge.

Suggested classes:

- `public`
- `team`
- `repo`
- `private`
- `eval_only`

Visibility answers "who may read this?"

It does not answer:

- which repository the fact came from
- which team owns the subject
- which version is current
- which projection should be rendered

### Versioning

Versioning is the state of the model, extractor output, or snapshot.

Versioning answers "which exact interpretation are we using?"

Version labels are required for:

- reproducible evaluations
- prompt regression analysis
- schema migrations
- comparing old and new extraction quality

Versioning must not be used as a hidden proxy for visibility or scope.

## Field Contract

Any persisted subject artifact should be able to declare the following fields
or their equivalents:

```json
{
  "subject_id": "subject:allie",
  "scope": {
    "type": "repo",
    "id": "repo:minis-ai"
  },
  "perspective": "reviewer",
  "visibility": "team",
  "version": "subject-model-v3"
}
```

Minimum interpretation rules:

- `subject_id` identifies the canonical subject
- `scope` selects the evidence boundary
- `perspective` selects the rendering policy
- `visibility` selects the access policy
- `version` selects the snapshot

If any one of these is missing, the surface is underspecified.

## Resolution Order

When Minis builds a subject view, it must resolve in this order:

1. Resolve the canonical subject.
2. Select the requested scope.
3. Apply visibility filtering for the current reader.
4. Select the perspective-specific rendering policy.
5. Pin the version or snapshot.
6. Materialize the projection.

This order matters.

If versioning is resolved before scope, a stale global snapshot can override a
more relevant repo-local slice. If visibility is applied too late, forbidden
data can leak into prompt construction. If perspective is ignored, the subject
will be rendered with the wrong tone or level of detail.

## Practical Rules

1. Store canonical facts once.
   If a fact is about the person, attach it to the canonical subject. Do not
   duplicate it as separate per-repo identities.

2. Store scope-specific behavior as scoped evidence.
   Repo-local review habits, team-specific norms, and delivery-context rules
   belong in scoped projections or scoped evidence records.

3. Never let a scope become an identity.
   "Allie in repo A" is not a second Allie.

4. Never let visibility change meaning.
   Visibility only changes who can see the data, not what the data means.

5. Never let versioning stand in for context.
   A version pin makes the result reproducible. It does not decide relevance.

6. Projections are read models, not sources of truth.
   The source of truth is the canonical subject plus its scoped evidence.

7. A surface must declare its scope explicitly.
   If a prompt, API response, or eval artifact does not state its scope, it is
   not reliable enough to ship.

## Implementation Implications

This ADR is docs-only, but it defines the contract that future implementation
must follow.

Expected consequences for implementation:

- the subject graph should keep a stable canonical subject node
- repo and team boundaries should be modeled as scopes, not duplicated
  identities
- access control should be evaluated before projection rendering
- review and prompt generation should request a specific perspective
- evals should pin versions so results are comparable over time

## Non-Goals

- We are not introducing a separate identity graph for every surface.
- We are not making repo scope the primary identity.
- We are not treating visibility as a substitute for authorization.
- We are not collapsing team and repo boundaries into one generic context
  bucket.

## Relationship to Existing Docs

This ADR complements:

- `docs/REVIEW_INTELLIGENCE.md` for review behavior and perspective-aware
  output
- `docs/ADR_001_UNIFIED_GRAPH_MEMORY.md` for the underlying graph-memory
  direction
- `docs/VISION.md` for the product-level decision-framework strategy

If a future design conflicts with this model, it should be treated as a model
bug, not a formatting preference.
