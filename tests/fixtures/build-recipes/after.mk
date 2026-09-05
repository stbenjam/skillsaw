after-generation:
	@test -d "$$TMPDIR"
	@printf '%s\n' "$$TMPDIR" > after.txt
