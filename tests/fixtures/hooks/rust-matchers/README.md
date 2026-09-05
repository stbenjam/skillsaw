# Pinned hook matcher evidence

[evidence.json](evidence.json) records 34 exact patterns and their expected Skillsaw
findings. The helper tests consume these rows, and the CLI tests check the existing
Grok and Muse fixtures against them. Nothing here runs a hook or installs a host.

## What each observation means

- `pattern` is the decoded regex string, including any newline or literal backslash.
- `record` identifies the original saved audit batch and case. The top-level hashes
  identify those original records; the portable observations are copied into each row.
- `rust_verdict` records compilation by ripgrep 15.2.0 (revision `e89fff89ac`), with
  `--no-config --engine default`. `rust_exit` distinguishes a match (0), a compiled
  pattern with no match (1), and a compiler refusal (2). Compilation acceptance does
  not prove a hook fires or that a particular tool name matches.
- `grok_verdict` records whether Grok 1.0.13 retained the target matcher group in
  `inspect --json`; `grok_handler_targets` preserves the observed command identities.
  `unresolved` with `null` targets means there is no Grok observation for that row.
- `skillsaw_finding` is the expected matcher diagnostic with the host rule explicitly
  selected and default severity: `warning` or `null`. `skillsaw_assessment` separately
  marks conservative abstention. For example, Rust refuses `(?x)(`, while Skillsaw
  withholds a finding because extended-mode parsing is unresolved. A null finding
  therefore cannot be used as evidence of native acceptance.

There are 27 saved Grok controls: 13 retained their target group and 14 lost it.
Four further controls distinguish literal flag-like text from real inline flags.
Three existing extended-mode abstention controls make the checker limit explicit.
All 34 have Rust-engine observations; the latter seven have no Grok observation.

## Grok provenance and inspection input

The evidence pins the executable version and SHA-256 independently from the official
source revision. The source snapshot is **not claimed to be the binary's source**.
The pinned [`matcher.rs`](https://github.com/xai-org/grok-build/blob/72a61251fcffb464bcc687aeb5a998e5a98ec0c9/crates/codegen/xai-grok-hooks/src/matcher.rs)
compiles non-simple patterns with `regex::Regex::new`, and
[`config.rs`](https://github.com/xai-org/grok-build/blob/72a61251fcffb464bcc687aeb5a998e5a98ec0c9/crates/codegen/xai-grok-hooks/src/config.rs)
applies this when constructing matcher groups. Source file hashes are also recorded.

[inspection-input.json](inspection-input.json) preserves the synthetic four-handler
input. Replace only `hooks.PreToolUse[0].matcher` with a row's exact `pattern` to
reconstruct its JSON input. The first two command strings identify the target and
same-group canary; the next two identify the same-event and other-event canaries.
The 27 observations retain both unaffected canaries, so missing target groups cannot
be mistaken for an empty inspection or an undiscovered file.

The saved inspection used one user-scope file under an isolated `GROK_HOME/hooks/`,
an empty session directory, a masked home, disabled Claude/Cursor compatibility hooks
and an unavailable network. Only `grok inspect --json` ran; the command strings were
metadata and no hook was dispatched. These observations establish load-time retention,
not hook execution, project trust, or runtime tool-name matching.

The host's empty/`*` catch-alls, exact-name alternatives, and ignored matcher events
have separate rule tests. Do not feed those host conventions to a generic compiler
and infer host rejection. The portable table covers active regex-form PreToolUse
matchers only.

## Optional Rust-engine replay

From the repository root, with ripgrep already installed:

```sh
.venv/bin/python3 scripts/replay-rust-matchers.py
```

The script passes each pattern as an argument and a tiny constant subject through
stdin. It does not read repository files through ripgrep, use a shell, execute fixture
commands, contact a service, or invoke Grok/Muse. It prints the current ripgrep version,
compiler outcome, and matching output separately; exit 1 means a verdict changed or
could not be established. It never overwrites the pinned observations. Normal tests
need neither ripgrep nor either host binary.

The [Rust regex syntax reference](https://docs.rs/regex/1.13.1/regex/#syntax) explains
flags and scalar escapes, but does not replace a host observation. Ripgrep itself
wraps regex patterns: the accepted extended-mode comment control intentionally ends
with a newline so its comment cannot consume ripgrep's wrapper. Preserve that newline;
changing it creates a different input and can change the engine comparison.

## Muse limit

The matcher helper is shared with Muse; this table does not validate a current Muse
loader. The historical Muse 1.0.2-R2040.1 canary matrix described in the maintenance
reference predates this audit. Loader-only 1.0.3-R2198.1 controls did not distinguish
working from malformed inputs and are inconclusive.

The public corpus supplied five meaningful samples: two committed project configs,
one installer template, and two generator transcriptions. No generator was executed.
The latter authors describe unverified contract assumptions. Zero findings in these
samples neither validate the current loader nor establish a false-positive rate.
`muse-hooks-valid` remains opt-in; shared hook inventory and security rules are unchanged.

The audit's pinned public origins are:

| Kind | Source |
|---|---|
| Project config | [rmems/grok-ozempic](https://github.com/rmems/grok-ozempic/blob/4464a74ce5e7a7dbac34ec12dfa285041966e700/.muse/hooks.json) |
| Project config | [ducnd58233/vibe-agent](https://github.com/ducnd58233/vibe-agent/blob/ca2af14fcee8cfc2b904c0b93c78e037329c561b/.muse/hooks.json) |
| Installer template | [cgraf78/agentguard](https://github.com/cgraf78/agentguard/blob/a86483be48843aa303a32203f673c382e76d22ad/share/agentguard/integrations/muse/hooks.json) |
| Generator read for transcription | [corveil/crow](https://github.com/corveil/crow/blob/4a95b30ded75ec2a0cf6492159d914e58d7aeb1f/Packages/CrowMuse/Sources/CrowMuse/MuseHookConfigWriter.swift#L64) |
| Generator read for transcription | [intutic/intutic](https://github.com/intutic/intutic/blob/18b720d183d4a3500d3c4955c9b51b50df50eb3d/services/sync-daemon/src/harness/museHooks.ts#L200) |

These links identify the original sources. The generator sources are not exact JSON
payloads; the audit transcribed their shapes and substituted parameter values.
