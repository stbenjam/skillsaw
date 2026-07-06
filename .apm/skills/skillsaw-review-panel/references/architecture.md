# Architecture Reviewer — Scope

Reviews structural quality of the change:

- **Single Responsibility**: Does each new function/type/module have one clear job?
- **Cross-file impact**: Do changes propagate through all callers and dependents without breakage?
  Trace imports from changed modules to verify no downstream breakage.
- **Abstraction level**: Are new abstractions justified or premature? Three similar
  lines is better than a premature abstraction.
- **Module boundaries**: Are package/module imports clean? Any circular dependencies?
  Does the change respect the existing architecture (context.py -> config.py ->
  rule.py -> linter.py pipeline)?
- **Error handling**: Are errors propagated to callers without being swallowed? Exceptions
  should carry actionable messages.
- **Pattern consistency**: Do new patterns match existing architectural conventions
  in the codebase?

Anti-patterns to flag: god functions, shotgun surgery, feature envy,
inappropriate intimacy, premature abstraction.
