# Create or update configuration

If `.skillsaw.yaml` does not exist, run `skillsaw init` and tell the user this
file controls rule settings.

Then write every setting the user confirmed for the **Configure** bucket into
the file: a rule option, `severity: info`, or `enabled: false`, each under its
rule with a `#` comment giving the reason. Leave everything else in an existing
file unchanged. Lint again and report how many findings the configuration
removed.

Record whether the file was created or changed, then return to the router.
