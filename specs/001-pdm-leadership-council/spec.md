# Feature Specification: AI PDM Leadership Council

**Feature Branch**: `001-pdm-leadership-council`

**Created**: 2026-08-12

**Status**: Draft

**Input**: User description: "Full app MVP — a product-management advice application where junior and mid-level Product Managers ask situational questions and receive answers grounded in the published thinking of experienced product leaders, either from one selected expert or as a compared 'council' of perspectives. Derived from requirement_pdm_council.txt, requirement_assignment.txt, and the PLAN_*.md design documents."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask the Product Council (Priority: P1)

A junior or mid-level PM faces a situation they have never handled before (e.g., "My engineering team keeps pushing back on my roadmap. What should I do?"). They type their situation into the app and receive a structured answer that (a) restates their situation, (b) presents two or more contrasting perspectives, each attributed to a specific named product leader and grounded in that leader's published thinking, and (c) closes with a numbered list of concrete recommended actions. The answer appears progressively (streams) rather than after a long blank wait.

**Why this priority**: This is the core product promise — "learn how great product leaders think" applied to the user's own situation. Without it there is no product; every other story refines or supports it.

**Independent Test**: Can be fully tested by entering a valid API key, typing one realistic PM situation, and verifying the response contains ≥2 distinct expert-attributed perspectives, a recommended-actions list, and visible source attributions.

**Acceptance Scenarios**:

1. **Given** a user with a valid API key entered, **When** they submit a realistic PM situation in council mode, **Then** the answer contains at least two perspectives attributed to different named experts, followed by numbered recommended actions.
2. **Given** the same setup, **When** the answer is generated, **Then** text appears progressively while it is being produced, and each perspective's claims are traceable to listed sources.
3. **Given** a question on a PM topic where the knowledge base has material from only one expert, **When** the user asks it in council mode, **Then** the app presents what it has and states plainly that other council voices have little published on this topic (it does not fabricate perspectives).
4. **Given** a first-time visitor with an empty conversation, **When** the app loads, **Then** it presents a small set of realistic example PM situations, and selecting one submits it as the user's question.

---

### User Story 2 - Ask a Specific Expert (Priority: P2)

The PM wants one particular leader's take (e.g., "Ask Shreyas"). They select an expert from a roster before asking. The answer draws only on that expert's published thinking, is framed as "in the spirit of {expert}'s published thinking" (never first-person impersonation), and says so when that expert's material doesn't cover the question.

**Why this priority**: The second half of the product's two advertised modes; high user value but the council mode alone is already a viable product.

**Independent Test**: Select one expert, ask a question that expert has famously written about, and verify all cited sources belong to that expert; then ask something outside their published material and verify the app admits the gap instead of borrowing other experts' content.

**Acceptance Scenarios**:

1. **Given** an expert is selected, **When** the user asks a question, **Then** every cited source in the answer belongs to that expert.
2. **Given** an expert is selected, **When** the user asks something that expert's material does not cover, **Then** the answer states the coverage gap honestly rather than substituting other experts' content or inventing a position.
3. **Given** council mode is active, **When** the user's question itself names a specific expert ("What would Shreyas say about this?"), **Then** the app answers from that expert's material as if the expert had been selected.

---

### User Story 3 - Bring Your Own API Key (Priority: P2)

Before asking anything, the user chooses one of three AI providers (OpenAI, Google Gemini, or Claude) and pastes their own API key. The key works for the whole session, is never stored beyond the session, never appears in any log or saved file, and an invalid key produces an immediate, understandable error — not a cryptic failure mid-answer.

**Why this priority**: A hard prerequisite for stories 1 and 2 to run at all, and a hard constraint of the assignment — but it's plumbing, not the product's value, so it ranks below the council experience it enables.

**Independent Test**: Paste an invalid key and verify a clear immediate error; paste a valid key and verify a question succeeds; restart the app and verify the key is gone.

**Acceptance Scenarios**:

1. **Given** a fresh session, **When** the user submits a question without entering a key, **Then** the app explains a key is required and how to provide one, and makes no paid calls.
2. **Given** an invalid or expired key, **When** the user first tries to use it, **Then** they see a clear error identifying the problem before any answer is attempted.
3. **Given** a valid key was used, **When** the session ends, **Then** the key is not retained anywhere — a new session starts with no key present.

---

### User Story 4 - Verify the Sources (Priority: P3)

After receiving an answer, a skeptical PM wants to check that the advice really reflects the named experts. Each answer lists its sources: for written material, the expert's name, the piece's title, and a link to the original; for podcast material, the episode and a link that jumps to the moment in the recording where the expert says it.

**Why this priority**: Trust and verifiability differentiate this product from generic AI advice, but the feature only matters once answers (P1/P2) exist.

**Independent Test**: Ask any question, click every listed source, and confirm each link opens the claimed original material (and, for podcast sources, lands at the referenced moment).

**Acceptance Scenarios**:

1. **Given** any completed answer, **When** the user reviews it, **Then** a sources list is present and every entry names the expert and the original work with a working link.
2. **Given** an answer that drew on a podcast conversation, **When** the user follows that source link, **Then** it opens the recording at (or near) the cited moment.

---

### User Story 5 - Rebuild the Knowledge Base from the Repository (Priority: P2)

A corpus maintainer — or the course reviewer verifying the project for certification — clones
the repository and rebuilds the knowledge base from scratch using the included collection and
curation tooling, without needing anything that isn't in the repo or documented in it. The
rebuild collects the experts' public material, cleans and organizes it with full attribution,
and produces the exact artifacts the deployed app answers from. Running it again without
source changes reproduces the same result rather than duplicating content.

**Why this priority**: The assignment certifies the project partly by reviewing this exact
capability (collection scripts in the repo, reviewable evidence of the data sources), and the
app's trustworthiness rests on a corpus whose provenance can be audited. It ranks below the
council experience only because users never touch it directly.

**Independent Test**: On a fresh clone, follow the documented rebuild steps for a single
expert and verify attributed, validated corpus records are produced; then run the full rebuild
and verify every roster expert is represented and the app can answer from the result.

**Acceptance Scenarios**:

1. **Given** a fresh clone of the repository and its documented setup steps, **When** the
   maintainer runs the collection process for one expert, **Then** it produces corpus records
   each carrying the expert's name, the original work's title and link, and its publication
   context — with no manual editing required.
2. **Given** a completed full rebuild, **When** the maintainer inspects the corpus summary,
   **Then** every expert on the roster is represented, and material from at least two
   independent public source collections is present.
3. **Given** an already-built corpus, **When** the collection process runs again with no
   source changes, **Then** the corpus is unchanged — no duplicated works.
4. **Given** the rebuild process, **When** it runs end to end, **Then** it uses only the
   maintainer's own credentials and never a key belonging to an app user, and nothing about
   the rebuild is required at the moment a user asks a question.

---

### Edge Cases

- **Off-topic question** (e.g., cooking advice): the app politely explains its scope (product-management situations) and does not spend the user's money generating a full answer.
- **Weak retrieval**: if nothing sufficiently relevant exists in the knowledge base, the app says the council's published material doesn't cover this well, rather than padding an answer from marginal matches.
- **Provider outage or mid-answer failure**: the user sees an understandable error and can retry; a partial answer is clearly incomplete, not silently truncated.
- **Very long question** (multi-paragraph situation dump): accepted and handled; the app answers the situation as described.
- **Rapid repeated submissions**: earlier in-flight answers are superseded cleanly; the user is not double-charged for abandoned generations beyond what was already produced.
- **One expert dominating**: in council mode, no single expert's material may crowd out all other voices when multiple experts have relevant material.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST answer PM situational questions using a curated knowledge base built from the published thinking (articles, newsletters, podcast interviews) of a roster of named, real product leaders.
- **FR-002**: Every piece of knowledge in the system MUST carry attribution to its expert and original source, and that attribution MUST survive into the answers users see.
- **FR-003**: The system MUST offer two modes: "Ask the Council" (multiple compared perspectives) and "Ask an Expert" (one selected expert only).
- **FR-004**: Council-mode answers MUST follow the structure: restatement of the situation → two or more expert-attributed perspectives → numbered recommended actions.
- **FR-005**: Expert-mode answers MUST draw exclusively on the selected expert's material and MUST disclose when that material does not cover the question.
- **FR-006**: The system MUST NOT impersonate experts in the first person; answers are framed as grounded in the expert's published thinking.
- **FR-007**: Users MUST be able to select one of three AI providers — OpenAI, Google Gemini, or Claude — and supply their own API key through the interface.
- **FR-008**: The system MUST NOT store user API keys beyond the active session, include them in logs, or ship any key with the application.
- **FR-009**: The system MUST validate the user's key early and report key problems in plain language before attempting an answer.
- **FR-010**: Answers MUST stream progressively as they are generated.
- **FR-011**: Every answer MUST include a sources list; written sources link to the original piece, and podcast sources link to the cited moment in the recording.
- **FR-012**: The system MUST recognize off-topic questions and respond with a brief scope explanation instead of a paid full answer.
- **FR-013**: When a council-mode question names a specific expert, the system MUST answer from that expert's material.
- **FR-014**: The complete experience (all modes, several questions) MUST be tryable for US$0.50 or less on the user's key; no user-triggered action may start an expensive processing job on the user's key.
- **FR-015**: All knowledge-base construction (collection, cleaning, organizing) MUST happen offline before deployment, never at user expense, and the collection/curation tooling MUST be part of the project repository.
- **FR-016**: The application MUST be publicly reachable as a hosted web app (assignment constraint: a public Hugging Face Space) with documentation stating what it is, which API keys a user needs, and the expected trial cost.
- **FR-017**: The expert roster for the MVP MUST include at least the experts named in the product concept for whom public material exists (target: ~8, including Shreyas Doshi, Marty Cagan, Teresa Torres, Elena Verna, Julie Zhuo, Gibson Biddle, Casey Winters, Brian Chesky).
- **FR-018**: The project MUST include an evaluation of answer quality and knowledge-base coverage — the question set, the measurement tooling, and the results — with the evaluation materials in the repository and the results published in the README.
- **FR-019**: The project MUST implement at least 5 of the course assignment's optional functionalities and list the implemented ones in the README.
- **FR-020**: The knowledge base MUST draw on at least two independent public source collections (e.g., experts' own blogs/newsletters and a public podcast-interview transcript archive), with the collection evidence reviewable in the repository.
- **FR-021**: On first visit (empty conversation), the app MUST offer a small set of example PM situations that can be selected to start a conversation, and MUST show the expert roster so the user can see whose thinking the council draws on before asking anything.

### Key Entities

- **Expert**: A named, real product leader on the council roster; has a canonical name and a body of attributed source material.
- **Source Work**: A single original piece by an expert — an article, newsletter issue, deck, or podcast appearance — with title, original link, publication date, and type.
- **Excerpt**: A retrievable passage of a source work; always attributed to exactly one expert and one source work; podcast excerpts also carry the moment (timestamp) in the recording.
- **Question**: The PM's situation as submitted, plus the chosen mode and (in expert mode) the selected expert.
- **Answer**: The structured response; composed of expert-attributed perspectives and recommended actions, linked to the excerpts that ground it.
- **Citation**: The user-visible pointer from an answer to a source work (and moment, where applicable).
- **Session**: One user's visit — provider choice, API key, and conversation; nothing about it persists after it ends.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time user with a valid API key gets their first complete, cited answer within 3 minutes of opening the app.
- **SC-002**: A user can exercise every capability (both modes, source checking, several questions) for US$0.50 or less in API charges.
- **SC-003**: At least 90% of council-mode answers to on-topic questions present two or more distinct expert-attributed perspectives.
- **SC-004**: 100% of answers display a sources list, and every listed source resolves to real published material by the named expert.
- **SC-005**: In expert mode, 100% of cited sources belong to the selected expert.
- **SC-006**: On a held-out evaluation set of PM questions, the material the answer needs is found in the knowledge base for at least 80% of questions (measured by the project's evaluation harness, results published in the README).
- **SC-007**: The first words of an answer appear within 5 seconds of submission under normal conditions.
- **SC-008**: Off-topic questions receive a scope reply that costs the user less than US$0.01.

## Assumptions

- The knowledge base is built from publicly available material by the named experts (blogs, free newsletter posts, public decks, and a public archive of podcast interview transcripts), used with attribution for a personal course project; per-expert corpus stays modest (dozens of works, not full-site mirrors).
- English-only for the MVP: questions, answers, and corpus.
- No user accounts, no cross-session history; a session is anonymous and self-contained.
- Multi-turn follow-up within a session is supported conversationally, but each session starts fresh.
- The three supported providers' mainstream cost-efficient models are sufficient for answer quality; users are not offered model-level configuration.
- Course-assignment delivery obligations are binding requirements of this feature (see FR-014 through FR-020), not aspirations: public Hugging Face Space, README contents (cost estimate, required-keys list, implemented optional functionalities), and published evaluation results.
- The project's design documents (`PLAN.md`, `PLAN_DATA_PIPELINE.md`, `PLAN_TRANSCRIPTS.md`, `PLAN_QUERY_FLOW.md`) predate this spec and serve as implementation-planning input; where this spec and those documents disagree on WHAT the product does, this spec wins.
