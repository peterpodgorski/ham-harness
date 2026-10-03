IMAGE ?= harness-pi:latest
PODMAN ?= podman
CONTEXT ?=

# Local configuration (gitignored .env), e.g. APP_REPO and APP_BIN. Loaded here
# so `make` picks it up without repeating it on every invocation.
-include .env

# The app and alloy-connect repositories are external, so their names and
# locations are configuration, not assertions. Set APP_REPO to the app
# repository root and ALLOY_REPO to the alloy-connect root (there are no
# defaults); set APP_BIN to the app's release binary for `make run-release`.
# These may live in the gitignored .env loaded above.
APP_REPO ?=
APP_BIN ?=
ALLOY_REPO ?=

# Every target except build-pi, run-pi and run-release executes inside the
# harness image (scripts/*.sh). The harness repo is bind-mounted at /workspace,
# the app repo at /workspace/app and alloy-connect at /workspace/alloy-connect,
# the host user is mapped onto the image's
# `pi` user (uid/gid 1000) so generated files keep the caller's ownership, and
# the image entrypoint is replaced by bash so the script can be run
# non-interactively.
CONTAINER_RUN = test -n "$(APP_REPO)" || { echo "APP_REPO is not set; point it at the app repository (make APP_REPO=/path/to/app ...)" >&2; exit 1; }; \
	test -f "$(APP_REPO)/Cargo.toml" || { echo "app repository not found at: $(APP_REPO)" >&2; exit 1; }; \
	test -n "$(ALLOY_REPO)" || { echo "ALLOY_REPO is not set; point it at the alloy-connect repository (make ALLOY_REPO=/path/to/alloy-connect ...)" >&2; exit 1; }; \
	test -f "$(ALLOY_REPO)/Cargo.toml" || { echo "alloy-connect repository not found at: $(ALLOY_REPO)" >&2; exit 1; }; \
	$(PODMAN) run --rm \
	--userns=keep-id:uid=1000,gid=1000 \
	--volume "$(CURDIR):/workspace:rw" \
	--volume "$(APP_REPO):/workspace/app:rw" \
	--volume "$(ALLOY_REPO):/workspace/alloy-connect:ro" \
	--env "PIPELINE_CONTEXT=$(CONTEXT)" \
	--workdir /workspace \
	--entrypoint /bin/bash \
	$(IMAGE)

.PHONY: build-pi run-pi run-release test-bdd test lexicon-check \
	lexicon-check-quint lexicon-conformance alloy-check alloy-catalog \
	scenario-coverage mbt-alloy mbt-quint arch-class arch-class-diff arch-db \
	pipeline-check pipeline-plan pipeline-run restructure-check \
	model-discipline attest attest-check

build-pi: ## Build the pi agent image (containers/Containerfile.pi)
	$(PODMAN) build -t $(IMAGE) -f containers/Containerfile.pi .

run-pi: ## Launch the pi agent on the compose network (containers/run-pi.sh)
	./containers/run-pi.sh

run-release:
	@[ -n "$(APP_REPO)" ] && [ -n "$(APP_BIN)" ] || { echo "set APP_REPO and APP_BIN (app repository and release binary)" >&2; exit 1; }
	cd "$(APP_REPO)" && cargo run --release --bin "$(APP_BIN)"

test-bdd: ## Run BDD tests end to end: in-memory pass, then a second pass over real SQLite
	$(CONTAINER_RUN) scripts/test-bdd.sh

test: ## Run the full test suite (unit + integration + property + BDD)
	$(CONTAINER_RUN) scripts/test.sh

lexicon-check: ## Validate Gherkin features against the controlled vocabulary (lexicon/)
	$(CONTAINER_RUN) scripts/lexicon-check.sh

lexicon-check-quint: ## Validate and verify the Quint models against the lexicon
	$(CONTAINER_RUN) scripts/lexicon-check-quint.sh

scenario-coverage: ## Verify every Quint action is exercised by its story's Gherkin
	$(CONTAINER_RUN) scripts/scenario-coverage.sh

lexicon-conformance: ## Verify derived read models against lexicon relations (architecture/lexicon-conformance.md)
	$(CONTAINER_RUN) scripts/lexicon-conformance.sh

alloy-catalog: ## Regenerate the Alloy category catalog from the conformance oracle
	$(CONTAINER_RUN) scripts/alloy-catalog.sh

alloy-check: ## Verify the per-context Alloy domain models against the lexicon (structure gate)
	$(CONTAINER_RUN) scripts/alloy-check.sh

mbt-alloy: ## Replay Alloy-generated domain traces against the real app (alloy-connect)
	$(CONTAINER_RUN) scripts/mbt-alloy.sh

mbt-quint: ## Replay Quint-generated traces against the real app (quint-connect)
	$(CONTAINER_RUN) scripts/mbt-quint.sh

arch-class: ## Regenerate the as-built class model from code (deterministic)
	$(CONTAINER_RUN) scripts/arch-class.sh

arch-class-diff: arch-class ## Diff an authored class plan against the as-built model (PLAN=path/to/class-plan.yaml)
	$(CONTAINER_RUN) scripts/arch-class-diff.sh $(PLAN)

arch-db: ## Regenerate the as-built database model from the adapter DDL (deterministic)
	$(CONTAINER_RUN) scripts/arch-db.sh

pipeline-check: ## Validate the pipeline registry and every context configuration
	$(CONTAINER_RUN) scripts/pipeline.sh check

pipeline-plan: ## Print the resolved gate set for CONTEXT=<context>
	$(CONTAINER_RUN) scripts/pipeline.sh plan --context $(CONTEXT)

pipeline-run: ## Run the configured automated gates for CONTEXT=<context>
	$(CONTAINER_RUN) scripts/pipeline.sh run --context $(CONTEXT)

restructure-check: ## Verify stories/ and lexicon/ are unchanged (architecture-scope refactor invariant)
	$(CONTAINER_RUN) scripts/restructure-check.sh

model-discipline: ## Report and validate every escape hatch / exemption (residual risk)
	$(CONTAINER_RUN) scripts/model-discipline.sh

# Measurement and result are app artifacts; the logic is harness tooling.
ATTEST ?= app/attestations/$(CONTEXT).json

attest: ## Write the verification attestation into the app (ATTEST=path)
	$(CONTAINER_RUN) scripts/attest.sh emit --context $(CONTEXT) --out $(ATTEST)

attest-check: ## Verify the app's recorded attestation matches the spec (ATTEST=path)
	$(CONTAINER_RUN) scripts/attest.sh check --context $(CONTEXT) --attestation $(ATTEST)
