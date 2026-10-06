/**
 * Process Gate Extension
 *
 * Enforces `PROCESS.md`: no write, edit, or mutating bash against the repo until
 * a **validated** process anchor (stage + one or more stories [+ context]) has
 * been set.
 *
 * - `set_process_anchor` (tool): the model declares the anchor. It is validated
 *   against the filesystem — unknown stages, unknown bounded contexts, and
 *   unknown stories are rejected, and missing upstream artifacts are reported.
 *   Cross-story work names every story it touches; the first is primary.
 * - `/anchor` (prompt template, `.pi/prompts/anchor.md`): the user-facing way to
 *   drive the tool.
 * - `/process` (command): show (`/process`) or clear (`/process clear`) the
 *   current anchor.
 * - `tool_call`: block unanchored mutations (fail-safe).
 * - `before_agent_start`: surface the current anchor in the system prompt.
 *
 * Read-only tools and read-only bash are never gated, so the agent can always
 * inspect the repo to resolve an anchor. The anchor is persisted as a session
 * entry so it survives compaction and follows the active branch.
 */

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import { Type } from "typebox";

const STAGES = [
	"story-map",
	"gherkin",
	"formalize",
	"explain-plan",
	"bdd",
	"audit",
	"explain-as-built",
	"refactor",
	"restructure",
	"harness",
] as const;
type Stage = (typeof STAGES)[number];

/**
 * The configured default bounded context, read from the environment (`.env`,
 * surfaced by run-pi.sh). There is no hardcoded default: when unset, a stage
 * that needs a context must name one.
 */
function configuredContext(): string {
	return (process.env.CONTEXT ?? process.env.PIPELINE_CONTEXT ?? "").trim();
}
const ANCHOR_TYPE = "process-anchor";
const STORY_RE = /^[a-z0-9][a-z0-9-]*$/;
/** Bounded-context slugs may also contain underscores (e.g. expense_tracking). */
const CONTEXT_RE = /^[a-z0-9][a-z0-9_-]*$/;

const REFUSAL =
	"Not anchored in PROCESS.md. No write, edit, or mutating bash is allowed " +
	"until a process anchor is set. Call set_process_anchor with {stage, stories} " +
	"(it validates against the repo), or ask the user to run /anchor. " +
	`Stages: ${STAGES.join(", ")}.`;

interface Anchor {
	stage: Stage;
	/** Primary context first; a restructure may span several. */
	contexts: string[];
	context: string;
	/** Primary story first; the rest are stories this task also touches. */
	stories: string[];
	artifact: string;
	intent?: string;
	note?: string;
	at: number;
}

const STORY_SPLIT = /[\s,]+/;

/** Flatten `stories` + the single-story shorthand into a de-duplicated slug list. */
function storyList(stories?: string[], story?: string): string[] {
	const out: string[] = [];
	for (const value of [...(stories ?? []), ...(story ? [story] : [])]) {
		for (const part of String(value).split(STORY_SPLIT)) {
			const slug = part.trim();
			if (slug && !out.includes(slug)) out.push(slug);
		}
	}
	return out;
}

/** Flatten `contexts` + the single `context` shorthand into a de-duplicated list. */
function contextList(contexts?: string[], context?: string): string[] {
	const out: string[] = [];
	for (const value of [...(contexts ?? []), ...(context ? [context] : [])]) {
		for (const part of String(value).split(STORY_SPLIT)) {
			const slug = part.trim();
			if (slug && !out.includes(slug)) out.push(slug);
		}
	}
	return out;
}

/** The story a repo-relative path belongs to, if it is under app/stories/<X>/. */
function isStoryPath(rel: string): string | undefined {
	return rel.replace(/\\/g, "/").match(/(?:^|\/)app\/stories\/([^/]+)\//)?.[1];
}

/** True when `rel` is `dir` itself or lies underneath it. */
function underDir(rel: string, dir: string): boolean {
	const r = rel.replace(/\\/g, "/");
	return r === dir || r.startsWith(`${dir}/`);
}

/** Stages whose anchor freezes the app's semantic inputs (prevention). */
const FREEZES_STORIES = new Set<Stage>(["harness", "restructure"]);
const FREEZES_LEXICON = new Set<Stage>(["restructure"]);

/** The repo-relative directories a stage must not mutate. */
function frozenPaths(stage: Stage): string[] {
	const dirs: string[] = [];
	if (FREEZES_STORIES.has(stage)) dirs.push("app/stories");
	if (FREEZES_LEXICON.has(stage)) dirs.push("app/lexicon");
	return dirs;
}

/** Accept anchors persisted before multi-story / multi-context support. */
function normalizeAnchor(a: (Anchor & { story?: string; contexts?: string[] }) | null): Anchor | null {
	if (!a) return null;
	const stories = a.stories?.length ? a.stories : a.story ? [a.story] : [];
	const contexts = a.contexts?.length ? a.contexts : a.context && a.context !== "-" ? [a.context] : [];
	return { ...a, stories, contexts, context: contexts[0] ?? a.context };
}

const AnchorParams = Type.Object({
	stage: StringEnum(STAGES),
	stories: Type.Optional(
		Type.Array(Type.String(), {
			description:
				"story slugs this task may change; the first is primary. Required unless the stage is context-scoped (harness, restructure). " +
				"Name every story the work crosses — a change to story B that story A needs goes here.",
		}),
	),
	story: Type.Optional(
		Type.String({ description: "single-story shorthand for `stories` (comma/space separated)" }),
	),
	context: Type.Optional(
		Type.String({ description: "bounded context (required unless CONTEXT is set); may be comma/space separated" }),
	),
	contexts: Type.Optional(
		Type.Array(Type.String(), {
			description:
				"bounded context slugs in scope; the first is primary. Restructure may list several " +
				"(e.g. a split names the existing context and the new ones).",
		}),
	),
	artifact: Type.Optional(Type.String({ description: "file/dir this stage will change (informational)" })),
	intent: Type.Optional(Type.String({ description: "one line: what this stage will do" })),
});

const STAGE_ARTIFACT: Record<Stage, (story: string, context: string) => string> = {
	"story-map": (s) => `app/stories/${s}/story-map.md`,
	gherkin: (s) => `app/stories/${s}/features/`,
	formalize: (s, c) => `app/stories/${s}/formal/invariants.qnt + app/architecture/${c}/domain.als`,
	"explain-plan": (s) => `app/stories/${s}/class-plan.yaml`,
	bdd: (s) => `app/stories/${s}/bdd-report.md`,
	audit: (s) => `app/stories/${s}/audit-report.md`,
	"explain-as-built": (_s, c) => `app/architecture/${c}/class.md`,
	refactor: (s) => `app/stories/${s}/audit-report.md`,
	restructure: (_s, c) => `app/architecture/${c}/restructure-report.md`,
	harness: () => "PROCESS.md / scripts/ / tools/ / pipeline/ / containers/",
};

const UPSTREAM: Record<Stage, (story: string) => string[]> = {
	"story-map": () => [],
	gherkin: (s) => [`app/stories/${s}/story-map.md`],
	formalize: (s) => [`app/stories/${s}/story-map.md`, `app/stories/${s}/features/`],
	"explain-plan": (s) => [`app/stories/${s}/features/`],
	bdd: (s) => [`app/stories/${s}/features/`],
	audit: (s) => [`app/stories/${s}/bdd-report.md`],
	"explain-as-built": (s) => [`app/stories/${s}/audit-report.md`],
	refactor: (s) => [`app/stories/${s}/audit-report.md`],
	restructure: () => [],
	harness: () => [],
};

function relExists(cwd: string, rel: string): boolean {
	return fs.existsSync(path.join(cwd, rel));
}

function knownStories(cwd: string): string[] {
	const dir = path.join(cwd, "app", "stories");
	if (!fs.existsSync(dir)) return [];
	return fs
		.readdirSync(dir, { withFileTypes: true })
		.filter((e) => e.isDirectory())
		.map((e) => e.name)
		.filter((n) => STORY_RE.test(n))
		.sort();
}

type Resolve = { ok: true; anchor: Anchor; warnings: string[] } | { ok: false; error: string };

function resolveAnchor(
	cwd: string,
	params: {
		stage: string;
		story?: string;
		stories?: string[];
		context?: string;
		artifact?: string;
		intent?: string;
	},
): Resolve {
	const stage = params.stage as Stage;
	if (!(STAGES as readonly string[]).includes(stage)) {
		return { ok: false, error: `unknown stage "${params.stage}". Valid stages: ${STAGES.join(", ")}.` };
	}

	if (stage === "harness") {
		return {
			ok: true,
			anchor: {
				stage,
				context: "-",
				contexts: [],
				stories: [],
				artifact: params.artifact?.trim() || STAGE_ARTIFACT.harness("", ""),
				intent: params.intent?.trim(),
				at: Date.now(),
			},
			warnings: [],
		};
	}

	if (stage === "restructure") {
		let contexts = contextList(params.contexts, params.context);
		if (contexts.length === 0) {
			const fallback = configuredContext();
			if (!fallback) {
				return { ok: false, error: "no bounded context: name one (context/contexts) or set CONTEXT." };
			}
			contexts = [fallback];
		}
		for (const context of contexts) {
			if (!CONTEXT_RE.test(context)) {
				return { ok: false, error: `invalid context slug "${context}" (expected [a-z0-9][a-z0-9_-]*).` };
			}
		}
		const missing = contexts.filter((context) => !relExists(cwd, `app/architecture/${context}/pipeline.yaml`));
		if (missing.length === contexts.length) {
			return {
				ok: false,
				error: `unknown bounded context(s): ${missing.join(", ")} (no app/architecture/<context>/pipeline.yaml).`,
			};
		}
		const named = storyList(params.stories, params.story);
		for (const story of named) {
			if (!STORY_RE.test(story)) {
				return { ok: false, error: `invalid story slug "${story}" (expected [a-z0-9][a-z0-9-]*).` };
			}
		}
		const warnings = missing.length ? [`context(s) not yet present (new?): ${missing.join(", ")}`] : [];
		const artifacts = contexts.map((context) => STAGE_ARTIFACT.restructure("", context));
		return {
			ok: true,
			anchor: {
				stage,
				contexts,
				context: contexts[0],
				stories: named,
				artifact: params.artifact?.trim() || artifacts.join("; "),
				intent: params.intent?.trim(),
				note: "context-scoped: app/stories and app/lexicon are frozen (invariant)",
				at: Date.now(),
			},
			warnings,
		};
	}

	const stories = storyList(params.stories, params.story);
	if (stories.length === 0) {
		return {
			ok: false,
			error: "at least one story is required (unless the stage is context-scoped: harness, restructure).",
		};
	}
	for (const story of stories) {
		if (!STORY_RE.test(story)) {
			return { ok: false, error: `invalid story slug "${story}" (expected [a-z0-9][a-z0-9-]*).` };
		}
	}

	const context = (params.context ?? "").trim() || configuredContext();
	if (!context) {
		return { ok: false, error: "no bounded context: pass `context` or set CONTEXT." };
	}
	if (!relExists(cwd, `app/architecture/${context}/pipeline.yaml`)) {
		return {
			ok: false,
			error: `unknown bounded context "${context}" (no app/architecture/${context}/pipeline.yaml).`,
		};
	}

	for (const story of stories) {
		if (!relExists(cwd, `app/stories/${story}`) && stage !== "story-map") {
			const known = knownStories(cwd);
			return {
				ok: false,
				error:
					`unknown story "${story}" for stage "${stage}". ` +
					`A new story must enter at story-map. ` +
					`Known stories: ${known.length ? known.join(", ") : "(none)"}.`,
			};
		}
	}

	const warnings: string[] = [];
	for (const story of stories) {
		for (const rel of UPSTREAM[stage](story)) {
			if (!relExists(cwd, rel)) {
				warnings.push(
					stories.length > 1
						? `[${story}] missing upstream artifact: ${rel}`
						: `missing upstream artifact: ${rel}`,
				);
			}
		}
	}

	const artifacts = stories
		.map((story) => STAGE_ARTIFACT[stage](story, context))
		.filter((value, index, all) => all.indexOf(value) === index);

	return {
		ok: true,
		anchor: {
			stage,
			context,
			contexts: [context],
			stories,
			artifact: params.artifact?.trim() || artifacts.join("; "),
			intent: params.intent?.trim(),
			note: warnings.length ? warnings.join("; ") : undefined,
			at: Date.now(),
		},
		warnings,
	};
}

// --- mutating-tool detection --------------------------------------------------

const READ_ONLY_CMDS = new Set([
	"ls",
	"cat",
	"bat",
	"head",
	"tail",
	"less",
	"more",
	"grep",
	"rg",
	"ag",
	"find",
	"fd",
	"tree",
	"wc",
	"sort",
	"uniq",
	"cut",
	"tr",
	"column",
	"stat",
	"file",
	"du",
	"df",
	"diff",
	"comm",
	"pwd",
	"whoami",
	"id",
	"date",
	"env",
	"printenv",
	"which",
	"type",
	"echo",
	"printf",
	"xxd",
	"hexdump",
	"strings",
	"jq",
	"true",
	"false",
	"cd",
	"test",
	"[",
]);

const GIT_READ_ONLY = new Set([
	"status",
	"diff",
	"log",
	"show",
	"branch",
	"remote",
	"config",
	"describe",
	"rev-parse",
	"ls-files",
	"ls-tree",
	"blame",
	"shortlog",
	"tag",
	"reflog",
	"cat-file",
	"grep",
	"name-rev",
	"whatchanged",
	"rev-list",
]);

function firstWord(segment: string): string | undefined {
	const tokens = segment.trim().split(/\s+/);
	let i = 0;
	while (i < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[i])) i++;
	return tokens[i];
}

/**
 * The subcommand of a `git ...` invocation, skipping global options — including
 * ones that take a separate value (`-C <path>`, `-c <name=value>`,
 * `--git-dir <path>`), whose argument must not be mistaken for the subcommand.
 */
const GIT_VALUE_FLAGS = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace"]);
function gitSubcommand(tokens: string[]): string | undefined {
	for (let i = 0; i < tokens.length; i++) {
		const t = tokens[i];
		if (t === "--") return undefined;
		if (t.startsWith("-")) {
			// `--opt=value` carries its value inline; a value flag consumes the next.
			if (!t.includes("=") && GIT_VALUE_FLAGS.has(t)) i++;
			continue;
		}
		return t;
	}
	return undefined;
}

function writesFile(segment: string): boolean {
	// Any redirection other than fd duplication (`2>&1`) or `/dev/null`.
	const re = /(?<![0-9])>>?(?!&)\s*([^\s|;&]+)/g;
	let m: RegExpExecArray | null;
	while ((m = re.exec(segment))) {
		const target = m[1];
		if (target === "/dev/null" || target === "&1" || target === "&2") continue;
		return true;
	}
	return false;
}

function segmentIsReadOnly(segment: string): boolean {
	const word = firstWord(segment);
	if (!word) return true;
	if (word === "git") {
		const sub = segment
			.trim()
			.split(/\s+/)
			.slice(1)
			.find((t) => !t.startsWith("-"));
		return sub !== undefined && GIT_READ_ONLY.has(sub);
	}
	return READ_ONLY_CMDS.has(word);
}

function isMutatingBash(command: string): boolean {
	const segments = command.split(/\|\||&&|[|;]|\n/);
	for (const raw of segments) {
		const segment = raw.trim();
		if (!segment) continue;
		if (writesFile(segment)) return true;
		if (!segmentIsReadOnly(segment)) return true;
	}
	return false;
}

/**
 * `git` subcommands that only snapshot or stage state the working-tree guard
 * already governs (index and refs), never the content of a tracked file on
 * disk. Committing is bookkeeping over work that was itself anchored when it
 * was written, so it is allowed at any stage and without an anchor.
 */
const GIT_BOOKKEEPING = new Set(["add", "commit", "tag"]);

/**
 * True when the command is *nothing but* git bookkeeping (`git add`/`commit`/
 * `tag`), optionally with env-var prefixes and shell chaining, plus read-only
 * commands that may surround it (e.g. `git status && git add -A && git
 * commit`). A command that also runs anything mutating is not bookkeeping and
 * is handled by the normal anchor rules.
 */
function isGitBookkeepingOnly(command: string): boolean {
	let sawBookkeeping = false;
	for (const raw of command.split(/\|\||&&|[|;]|\n/)) {
		const segment = raw.trim();
		if (!segment) continue;
		if (writesFile(segment)) return false;
		const tokens = segment.split(/\s+/);
		let i = 0;
		while (i < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[i])) i++;
		const word = tokens[i];
		if (word === "git") {
			const sub = gitSubcommand(tokens.slice(i + 1));
			if (sub !== undefined && GIT_BOOKKEEPING.has(sub)) {
				sawBookkeeping = true;
				continue;
			}
			// A read-only git segment (status/diff/log/…) may surround the
			// bookkeeping; any other git subcommand is not bookkeeping.
			if (sub !== undefined && GIT_READ_ONLY.has(sub)) continue;
			return false;
		}
		// Non-git segments must be read-only (e.g. `git status`, `echo done`).
		if (!segmentIsReadOnly(segment)) return false;
	}
	return sawBookkeeping;
}

function isMutating(toolName: string, input: Record<string, unknown>): boolean {
	if (toolName === "write" || toolName === "edit") return true;
	if (toolName === "bash") return isMutatingBash(String(input.command ?? ""));
	return false;
}

// --- extension ----------------------------------------------------------------

export default function processGate(pi: ExtensionAPI) {
	let anchor: Anchor | null = null;

	const persist = (value: Anchor | null) => {
		anchor = value;
		pi.appendEntry<Anchor | null>(ANCHOR_TYPE, value);
	};

	const reconstruct = (ctx: ExtensionContext) => {
		anchor = null;
		const entries = ctx.sessionManager.getBranch() as Array<{
			type: string;
			customType?: string;
			data?: unknown;
		}>;
		for (const entry of entries) {
			if (entry.type === "custom" && entry.customType === ANCHOR_TYPE) {
				anchor = normalizeAnchor(entry.data as (Anchor & { story?: string }) | null);
			}
		}
	};

	const anchorText = (a: Anchor | null): string => {
		if (!a) {
			return [
				"PROCESS ANCHOR: NONE.",
				"Read-only inspection is allowed. Before any write, edit, or mutating bash,",
				"call set_process_anchor with {stage, stories} (validated), or ask the user",
				"to run /anchor. If the request names no stage and story, refuse it.",
			].join("\n");
		}
		const where =
			a.stage === "harness"
				? "harness"
				: a.stage === "restructure"
					? `restructure @ ${a.contexts.join(" + ")}`
					: `${a.stories.join(" + ")} @ ${a.context}`;
		return [
			`PROCESS ANCHOR: ${a.stage} — ${where}`,
			a.intent ? `intent: ${a.intent}` : "",
			`artifact: ${a.artifact}`,
			a.note ? `note: ${a.note}` : "",
			"Stay in this stage; run only its enabled gates. A change of stage or story needs a new anchor.",
		]
			.filter(Boolean)
			.join("\n");
	};

	pi.on("session_start", (_event, ctx) => reconstruct(ctx));
	pi.on("session_tree", (_event, ctx) => reconstruct(ctx));

	pi.on("before_agent_start", (event) => {
		event.systemPromptOptions.sections.process_anchor = anchorText(anchor);
	});

	// Fail-safe: an unanchored mutation is blocked. Read-only tools pass.
	pi.on("tool_call", async (event, ctx) => {
		const input = event.input as Record<string, unknown>;
		if (!isMutating(event.toolName, input)) return undefined;

		// Committing is bookkeeping over already-anchored work: `git add`/
		// `commit`/`tag` only touch the index and refs, never a tracked file's
		// content (which the working-tree guard already governs). Allow it at any
		// stage and without an anchor, so a commit never has to fabricate a stage.
		if (event.toolName === "bash" && isGitBookkeepingOnly(String(input.command ?? ""))) {
			return undefined;
		}

		if (!anchor) return { block: true, reason: REFUSAL };

		// The architectural refactor freezes the app's semantic inputs: the
		// lexicon and every story (including its formal and informal models).
		if (event.toolName === "write" || event.toolName === "edit") {
			const raw = String(input.path ?? "");
			const rel = (path.isAbsolute(raw) ? path.relative(ctx.cwd, raw) : raw).replace(/\\/g, "/");

			if (FREEZES_LEXICON.has(anchor.stage) && underDir(rel, "app/lexicon")) {
				return {
					block: true,
					reason:
						`The ${anchor.stage} anchor freezes the lexicon (target: "${rel}"). ` +
						`The ubiquitous language and its relations are invariant under an architectural refactor. ` +
						`To change them, re-anchor to /formalize for the owning story.`,
				};
			}

			const story = isStoryPath(rel);
			if (story) {
				if (FREEZES_STORIES.has(anchor.stage)) {
					return {
						block: true,
						reason:
							`The ${anchor.stage} anchor freezes stories (target: "${story}"). ` +
							`Stories, their features and their formal models are invariant under an architectural refactor. ` +
							`To change one, re-anchor to its stage: /anchor <stage> ${story}`,
					};
				}
				if (!anchor.stories.includes(story)) {
					return {
						block: true,
						reason:
							`Story "${story}" is not in the current anchor ` +
							`(anchored: ${anchor.stories.join(", ")}). If this work crosses into it, ` +
							`re-anchor with it included: /anchor ${anchor.stage} ${[...anchor.stories, story].join(",")}`,
					};
				}
			}
		}

		// Mutating bash must not route around the frozen inputs. `git commit` and
		// `git tag` only snapshot state (the working tree is already guarded), so a
		// frozen path named in their message is inert.
		if (event.toolName === "bash") {
			const frozen = frozenPaths(anchor.stage);
			for (const raw of String(input.command ?? "").split(/\|\||&&|[|;]|\n/)) {
				const segment = raw.trim();
				if (!segment) continue;
				const tokens = segment.split(/\s+/);
				let i = 0;
				while (i < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[i])) i++;
				if (tokens[i] === "git") {
					const sub = tokens.slice(i + 1).find((t) => !t.startsWith("-"));
					if (sub === "commit" || sub === "tag") continue;
				}
				for (const dir of frozen) {
					if (new RegExp(`\\b${dir}\\b`).test(segment)) {
						return {
							block: true,
							reason:
								`The ${anchor.stage} anchor freezes ${dir}/; this mutating command references it. ` +
								`Read-only inspection is fine; changing a frozen input needs an anchor for its own stage.`,
						};
					}
				}
			}
		}
		return undefined;
	});

	pi.registerTool({
		name: "set_process_anchor",
		label: "Set Process Anchor",
		description:
			"Declare the PROCESS.md anchor (stage + stories, or a bounded context for harness/restructure) for the current task. " +
			"Validated against the repo: unknown stages and unknown stories are rejected, " +
			"and missing upstream artifacts are reported. Name every story the work crosses; " +
			"the first is primary. Required before any write, edit, or mutating bash.",
		parameters: AnchorParams,
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const result = resolveAnchor(ctx.cwd, params);
			if (!result.ok) {
				return {
					content: [{ type: "text", text: `Anchor rejected: ${result.error}\n\n${REFUSAL}` }],
					details: { ok: false, error: result.error },
				};
			}
			persist(result.anchor);
			const scope =
				result.anchor.stage === "harness"
					? ""
					: result.anchor.stage === "restructure"
						? ` for context(s) ${result.anchor.contexts.map((c) => `"${c}"`).join(" + ")}`
						: ` for ${result.anchor.stories.map((s) => `"${s}"`).join(" + ")} in context "${result.anchor.context}"`;
			const lines = [
				`Anchor established: ${result.anchor.stage}${scope}`,
				`characteristic artifact: ${result.anchor.artifact}`,
				...result.warnings,
			];
			return {
				content: [{ type: "text", text: lines.join("\n") }],
				details: { ok: true, anchor: result.anchor },
			};
		},
	});

	pi.registerCommand("process", {
		description: "Show (/process) or clear (/process clear) the current PROCESS.md anchor",
		handler: async (args, ctx) => {
			if (args.trim().toLowerCase() === "clear") {
				persist(null);
				ctx.ui.notify("Process anchor cleared. Mutations are blocked until a new anchor is set.", "warning");
				return;
			}
			if (!anchor) {
				ctx.ui.notify("No process anchor set. Run /anchor <stage> <story>[,<story>], or ask the agent.", "info");
				return;
			}
			ctx.ui.notify(anchorText(anchor), "info");
		},
	});
}
