.PHONY: check verify

check:
	node scripts/check-pstack.mjs
	node --test scripts/*.node-tests.mjs
	git diff --check
	@if command -v actionlint >/dev/null 2>&1; then \
		echo "Running actionlint..."; \
		actionlint -shellcheck=; \
	else \
		echo "Skipping actionlint (not on PATH)"; \
	fi
	@if command -v shellcheck >/dev/null 2>&1; then \
		echo "Running shellcheck..."; \
		shellcheck actions/*/*.sh; \
	else \
		echo "Skipping shellcheck (not on PATH)"; \
	fi
	@if command -v terraform >/dev/null 2>&1; then \
		echo "Running terraform fmt -check..."; \
		terraform fmt -check -recursive modules/; \
	else \
		echo "Skipping terraform (not on PATH)"; \
	fi

verify: check
	(cd actions/report-findings && node --test)
