## Why

An instruction that says "never use X" without saying what to use instead
leaves the model with no path forward. It knows what to avoid but has to
guess the alternative — and its guess may be worse than X. Pairing every
prohibition with a positive alternative gives the model a clear action.

## Examples

**Bad:**

```markdown
Don't use `var` in JavaScript.
Never commit directly to main.
```

**Good:**

```markdown
Use `const` or `let` instead of `var`.
Create a feature branch and open a PR — never commit directly to main.
```

## How to fix

Keep the prohibition and add what to do instead. If the alternative is
obvious from context, state it explicitly anyway — what is obvious to
you may not be the model's first choice. `skillsaw fix --llm` can add
positive alternatives automatically.
