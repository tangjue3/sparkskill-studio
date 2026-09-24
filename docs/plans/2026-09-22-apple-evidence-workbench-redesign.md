# SparkSkill Studio Apple-style Evidence Workbench Redesign

## Goal

Redesign the existing local Evidence Workbench as a bright, refined, presentation-ready professional product interface. The page must help a competition judge understand, within 90 seconds, how a natural-language visual task becomes a verified Agent Skill and a traceable evidence result.

This is a visual and information-architecture redesign, not a change to the underlying benchmark history, evidence artifacts, truth labels, or project claims.

## Audience and intent

The primary viewer is a hackathon judge looking at a projected desktop screen. They need to understand the product before they inspect technical details.

The interface should feel like an Apple product presentation fused with a professional evidence review tool: calm, precise, bright, spacious, credible, and visually memorable. It must not look like a generic admin dashboard, a terminal, or a collection of equal-weight cards.

## Domain vocabulary

- Agent execution chain
- Skill compilation
- Visual evidence
- Provenance
- Verification gate
- Final decision
- Benchmark history

## Signature element

The signature is the **Evidence Ribbon**: a continuous nine-stage execution rail from `User Task` to `Tier-3 Verification`. Each stage communicates the actor, transformation, artifact, and truth level. It is the narrative spine of the product rather than a decorative stepper.

## Visual system

- Canvas: Apple-like soft white `#F5F5F7`.
- Primary surface: clean white `#FFFFFF`.
- Primary text: graphite `#1D1D1F`.
- Secondary text: restrained neutral gray.
- Interaction accent: Apple blue near `#0071E3`.
- Verified: green used only for verified states.
- Recorded/blocked/failure: distinct semantic treatments with text and symbols, never color alone.
- Depth: subtle layered shadows and quiet translucent separators. No dramatic shadows.
- Typography: refined system-first Chinese/Latin stack with strong display hierarchy and readable projected text. Data fields may use a restrained monospace face.
- Spacing: generous negative space; minimum body text suitable for projection; no 10–11px primary content.
- Motion: short, calm transitions; no bounce, glow, or decorative animation.

Avoid purple gradients, dark terminal styling, oversized pills, equal-weight card grids, excessive glass effects, permanent raw JSON, and decorative icons without meaning.

## Information architecture

### 1. Minimal top bar

The top bar contains the product name, a concise descriptor, run selection, and the current truth/status. Environment and model details are available as secondary disclosure rather than a row of competing badges.

### 2. Hero result summary

The first screen leads with the active task, target description, one-sentence result, and a large real keyframe. The visual evidence image is the dominant object. The judge should immediately understand what was searched, what was found, and whether the result is verified.

### 3. Evidence Ribbon

The nine stages appear as a horizontal narrative rail:

1. User Task
2. StepFun Plan
3. DSH Skill Match
4. VisualTaskSpec
5. Video Frames
6. Qwen Evidence
7. Global Timeline
8. Final Decision
9. Tier-3 Verification

The entire sequence should be visible or obviously horizontally navigable at common desktop widths. Selecting a stage updates the main evidence canvas.

### 4. Stage evidence canvas

The selected stage shows the most relevant content, not a generic block:

- Visual stages lead with large keyframes and timeline information.
- Planning and Skill stages show concise input/output summaries.
- Verification stages lead with verdicts and comparisons.
- Artifact paths, full contracts, and raw JSON are secondary disclosures.

### 5. Provenance Inspector

Provenance becomes a right-side drawer or contextual panel opened from selected evidence. It must answer where a conclusion came from without permanently consuming one third of the screen.

### 6. Verification finale

The lower presentation area gives the final result visual emphasis:

- Final Decision
- Security 9/9
- Correctness 9/9
- Discoverability 9/9
- Effectiveness 9/9
- Runtime 3534.4s → 800.5s

The complete history remains available and honest: Initial PARTIAL → E9 remediation → evaluator v1 finding → evaluator v2 PASS.

## Data and truth constraints

- Use the existing `app/data/demo-manifest.json` and real artifact assets.
- Do not invent frames, benchmark values, model calls, Skill executions, or provenance.
- Preserve all seven run records and positive/negative modes.
- Preserve `Verified`, `Recorded`, `Structural`, `Blocked`, and `Synthetic Fixture` distinctions.
- Preserve the statement that the global timeline is evidence aggregation, not cross-camera identity tracking.
- Preserve benchmark limitations and failure history.
- The page remains a read-only display of recorded artifacts, not a live model execution UI.

## Interaction requirements

- Run selector updates all relevant regions.
- Evidence Ribbon stages are mouse- and keyboard-operable.
- Positive/negative modes remain available where supported.
- Keyframe and timeline selection updates provenance.
- Raw JSON is shown in an accessible modal or drawer and is hidden by default.
- Escape closes overlays and returns focus to the trigger.
- Loading, empty, error, and hidden states must work correctly.
- `[hidden]` elements must never be overridden by component display rules.

## Layout requirements

- Desktop targets: 1920×1080, 1440×900, and 1280×800.
- 1024×768 must remain usable through intentional adaptation, not a single long collapsed column.
- The page must not expand into a 3000px-tall imitation of three columns.
- The primary story, Evidence Ribbon, and result must be visible in the initial desktop viewport.
- Long paths and technical strings must wrap or truncate with an explicit reveal action.
- No unintended horizontal overflow.

## Accessibility and quality gates

- Semantic landmarks and headings.
- Visible focus states.
- Keyboard support for all actions.
- Status meaning is not color-only.
- Text contrast suitable for bright projection.
- No console errors or missing application assets.
- No permanent overlays, clipped task text, or broken independent scrolling.

## Scope

The Windows implementation may replace `app/index.html`, `app/styles.css`, and `app/app.js`, and may add small local assets when necessary. It must not modify benchmark inputs, artifacts, schemas, Skill logic, model services, credentials, or cloud services.

The redesign is implemented and visually verified locally first. Upload to the DGX Spark server is a separate, explicitly authorized task.

## Approved Chinese copy refinement

The primary presentation language is Chinese. Product and model proper nouns such as StepFun, DSH, Qwen, Tier-3, VisualTaskSpec, and SparkSkill Studio may remain in English, but navigation and explanatory copy should not require judges to decode an English dashboard.

### Hero hierarchy

For the recorded positive single-video example, replace the raw target description as the giant heading with a two-level result statement:

- Primary subject: `日落山湖中的太阳`
- Result line: `已被确认出现`
- Supporting target description: `明亮的太阳圆盘，位于山脊线附近`
- Result summary: `目标首次确认于 0 ms，最后确认于 4000 ms，共获得 5 帧有效证据。所有结论均可回溯至关键帧与证据时间线。`

The implementation must derive equivalent concise Chinese result copy for other run types and negative states rather than hard-coding a false positive statement globally. Raw paths, `frame_path`, schema field names, and artifact identifiers remain available through Provenance or JSON disclosure instead of appearing in the hero paragraph.

### Evidence Ribbon localization

- `EXECUTION PROVENANCE` → `执行证据链`
- `Evidence Ribbon` → `证据链路`
- `User Task` → `用户任务`
- `StepFun Plan` → `StepFun 任务规划`
- `DSH Skill Match` → `DSH 技能匹配`
- `VisualTaskSpec` → `视觉任务规范`
- `Video Frames` → `视频抽帧`
- `Qwen Evidence` → `Qwen 视觉证据`
- `Global Timeline` → `全局证据时间线`
- `Final Decision` → `最终结论`
- `Tier-3 Verification` → `Tier-3 验证`

Short Chinese descriptions should be used beneath each stage. The proper-noun actor or implementation detail may remain as secondary metadata. Existing node identifiers, data binding, keyboard interaction, truth status, and provenance contracts must not change.
