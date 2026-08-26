/**
 * Backup: collect the files that exist only on this machine, then mirror the
 * backup folder to drive B.
 *
 * Run with `node scripts/backup.mjs`. A Windows scheduled task runs it daily.
 *
 * Two different jobs, deliberately kept separate:
 *
 *   Collect   Refresh copies of the project's local-only files into backup/local/.
 *             This project has no live database to snapshot, so this is what
 *             takes that slot: GitHub already holds everything tracked, and
 *             these files are the ones a fresh clone would not bring back.
 *
 *   Mirror    Copy everything in backup/ to B:\Claude Backup\Infra Monitor\,
 *             then read both copies back and compare hashes. A mirror protects
 *             against losing the C: drive. It does not protect against bad data,
 *             which is why nothing here is ever deleted.
 *
 * Nothing here deletes anything. If the drive is missing or a copy fails, it
 * says so and exits non-zero, leaving what is already on disk alone.
 */

import { createHash } from 'node:crypto'
import { exec } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const execAsync = promisify(exec)

// ---- CONFIG ----------------------------------------------------------------
const PROJECT = path.resolve(fileURLToPath(import.meta.url), '..', '..')
const LOCAL = path.join(PROJECT, 'backup')
const DUMPS = path.join(LOCAL, 'db')
const REMOTE = 'B:\\Claude Backup\\Infra Monitor'
const DATABASE = null   // no live database in this project: the snapshot step skips itself
const PUSH = false      // origin NTRS-ZIB/RSS-Feed is PUBLIC and staying public
const ALLOW_PUBLIC_PUSH = false   // <-- see the comment on pushCommits before touching
const LOG = path.join(LOCAL, 'backup.log')

/** Files that exist ONLY on this machine, and where each is kept under backup/.
 *
 *  Everything tracked by git is already on GitHub, so these are the project's
 *  only genuinely unprotected files. They are copied fresh on every run rather
 *  than once at setup, because a copy taken once silently goes stale and then
 *  reports success forever.
 *
 *  The destinations deliberately flatten `.git/` to `git/`: a real `.git`
 *  directory nested inside backup/ confuses tools that walk upward looking for
 *  a repository root. backup/README.txt explains how to put each one back.
 *
 *  `required` marks a file whose absence is a REAL FAILURE rather than a normal
 *  state. Most of these legitimately do not exist right after a fresh clone and
 *  get rebuilt by hand from docs/local-workflow.md, so their absence must not
 *  cry wolf. The article is different: nothing rebuilds it and nothing else
 *  holds a copy, so if it stops being there the run must stop saying OK. */
const LOCAL_ONLY = [
	{ from: 'docs/miner-ai-pivot-article.md', to: 'local/docs/miner-ai-pivot-article.md', required: true },
	// Split out of docs/handoff.md on 2026-08-26 because the repo is public and
	// this carries unpublished drafts. Same reason the article is here: nothing
	// rebuilds it and nothing else holds a copy.
	{ from: 'docs/x-posts.md', to: 'local/docs/x-posts.md', required: true },
	// The backup mechanism itself. Untracked in git and PUSH is false, so without
	// this line the script that produces the backup lives only on the drive the
	// backup exists to protect against.
	{ from: 'scripts/backup.mjs', to: 'local/scripts/backup.mjs', required: true },
	{ from: '.claude/settings.local.json', to: 'local/claude/settings.local.json' },
	{ from: '.git/config', to: 'local/git/config' },
	{ from: '.git/info/exclude', to: 'local/git/info-exclude' },
	// The file that actually binds the state files to the stateremote merge
	// driver. Without it .git/config declares a driver that matches nothing, and
	// the failure is silent: merges just quietly stop using it.
	{ from: '.git/info/attributes', to: 'local/git/info-attributes' },
	{ from: '.git/hooks/pre-commit', to: 'local/git/hooks-pre-commit' },
	{ from: '.git/state-merge.sh', to: 'local/git/state-merge.sh' },
]
// ----------------------------------------------------------------------------

/** Local calendar date as YYYY-MM-DD. Not UTC: a dump is named for the day the
 *  user had, not the day Greenwich had. */
function today() {
	const now = new Date()
	const pad = (n) => String(n).padStart(2, '0')
	return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

const lines = []
function say(message) {
	console.log(message)
	lines.push(`${new Date().toISOString()}  ${message}`)
}

/** Record that a run began, immediately, before any work.
 *
 *  say() only buffers in memory until the finally block, so a run killed by a
 *  shutdown, a Task Scheduler time limit, or a hung drive writes nothing at all
 *  and leaves the previous run's "OK:" sitting there as the last line. A reader
 *  following backup/README.txt would call that healthy. This marker means a
 *  started-but-never-finished run is visible as a "run started" line with no
 *  verdict under it. */
async function markStart() {
	try {
		await fs.mkdir(LOCAL, { recursive: true })
		await fs.appendFile(LOG, `${new Date().toISOString()}  --- run started ---\n`)
	} catch {
		// Nowhere to record this. The non-zero exit is the remaining signal.
	}
}

async function sha256(file) {
	return createHash('sha256').update(await fs.readFile(file)).digest('hex')
}

/** The first line of a failure that actually says something. exec puts the real
 *  complaint on stderr, but npx prints its own install notices there first, and
 *  reporting one of those as the cause sends the reader down the wrong path. */
function reason(error) {
	// Strip colour codes: wrangler writes them to stderr even when not on a
	// terminal, and they arrive in the log as unreadable escape sequences.
	const text = (error.stderr || error.message || String(error)).replace(/\u001b\[[0-9;]*m/g, '')
	const useful = text
		.split('\n')
		.map((line) => line.trim())
		.find((line) => line && !/^npm (warn|notice|err)/i.test(line))
	return (useful || text.split('\n')[0] || 'unknown error').trim()
}

async function exists(target) {
	try {
		await fs.access(target)
		return true
	} catch {
		return false
	}
}

/** PRIVATE, PUBLIC, INTERNAL, or UNKNOWN if it cannot be established. Asks
 *  GitHub rather than trusting anything cached locally, because the answer can
 *  change after setup without a single local file changing. */
async function originVisibility(git) {
	try {
		const url = await git('remote get-url origin')
		// gh.exe, not gh: PowerShell blocks the shim on this machine.
		const { stdout } = await execAsync(`gh.exe repo view ${url} --json visibility -q .visibility`, {
			cwd: PROJECT,
			timeout: 60_000,
		})
		return stdout.trim().toUpperCase() || 'UNKNOWN'
	} catch {
		return 'UNKNOWN'
	}
}

/** Dump the live database to a dated file. Returns the path, or null if the
 *  export failed, or true when there is nothing to snapshot. A failure here must
 *  not stop the mirror: existing files still deserve copying. Leave this function
 *  in place even with no database, since the summary below reads its result. */
async function snapshotDatabase() {
	if (!DATABASE) {
		say('snapshot: no database configured for this project, skipping')
		return true
	}

	await fs.mkdir(DUMPS, { recursive: true })
	const out = path.join(DUMPS, `${DATABASE}-${today()}.sql`)

	// wrangler streams the download straight into --output with no temp file of
	// its own, so exporting onto the dated name would leave a truncated file
	// wearing that name if the export is killed or times out. Export to a scratch
	// name and rename only once it is known good: rename is atomic, so a file at
	// the dated path always means a finished export.
	const partial = `${out}.partial`

	if (await exists(out)) {
		say('snapshot: already have a dump for today, leaving it alone')
		return out
	}

	say(`snapshot: exporting ${DATABASE} from Cloudflare`)
	try {
		await fs.rm(partial, { force: true })

		// One command string through the shell, rather than execFile with an
		// args array. Two Windows quirks force this: PowerShell refuses the bare
		// `npx` .ps1 shim, and since Node 18.20 spawning a .cmd without a shell
		// fails with EINVAL.
		await execAsync(
			`npx.cmd wrangler d1 export ${DATABASE} --remote --output "${partial}" -y`,
			{ cwd: PROJECT, timeout: 300_000 },
		)

		// Inside the try: if wrangler exits 0 without producing the file, stat
		// throws, and that belongs in the same failure path as any other.
		const { size } = await fs.stat(partial)
		if (size === 0) throw new Error('export produced an empty file')

		await fs.rename(partial, out)
		say(`snapshot: wrote ${path.basename(out)} (${size} bytes)`)
		return out
	} catch (error) {
		// Leave no debris. A stray .partial must never outlive the run that made
		// it, or a later run could mistake it for real data.
		await fs.rm(partial, { force: true })
		say(`snapshot FAILED: ${reason(error)}`)
		say('snapshot: continuing to the mirror anyway, so existing files still get copied')
		return null
	}
}

/** Refresh backup/local/ from the project's local-only files.
 *
 *  A file that is absent is reported but does NOT fail the run: the pre-commit
 *  hook and the merge driver are rebuilt by hand after a re-clone and can be
 *  legitimately missing for a while. Nothing is deleted, so a copy already taken
 *  survives its source going away, which is the behaviour a backup should have.
 *
 *  A file that is present but cannot be read, or whose copy does not verify, IS
 *  a failure. That is the case where something is genuinely wrong. */
async function collectLocalFiles() {
	let copied = 0
	let current = 0
	const absent = []
	const missing = []
	const failures = []

	for (const item of LOCAL_ONLY) {
		const from = path.join(PROJECT, item.from)
		const to = path.join(LOCAL, item.to)

		if (!(await exists(from))) {
			// A required file that has vanished is a failure, not a note. Anything
			// else is an ordinary post-clone state and must not cry wolf.
			if (item.required) missing.push(item.from)
			else absent.push(item.from)
			continue
		}

		// Per file, so one unreadable file is recorded rather than aborting the
		// loop and silently skipping every file after it.
		try {
			const before = await sha256(from)
			const unchanged = (await exists(to)) && (await sha256(to)) === before
			if (unchanged) {
				current += 1
				continue
			}
			await fs.mkdir(path.dirname(to), { recursive: true })
			await fs.copyFile(from, to)

			// Read it back rather than trusting the copy.
			if ((await sha256(to)) === before) copied += 1
			else failures.push(`${item.from} (copy did not verify)`)
		} catch (error) {
			failures.push(`${item.from} (${error.code || error.message})`)
		}
	}

	say(`collect: ${LOCAL_ONLY.length} local-only files, ${copied} refreshed, ${current} already current`)
	for (const gone of absent) {
		say(`collect: not present in the project: ${gone}`)
		say('  normal right after a fresh clone. Any copy already in backup/local/ is kept.')
	}
	for (const gone of missing) {
		say(`collect FAILED: ${gone} has GONE MISSING from the project`)
		say('  this file is not rebuildable and nothing else holds a copy.')
		say('  The copy in backup/local/ is being kept and is now the ONLY one.')
	}
	for (const bad of failures) say(`collect FAILED: ${bad}`)
	return failures.length === 0 && missing.length === 0
}

/** Report work that exists only in the working tree.
 *
 *  This lives outside pushCommits() on purpose. The equivalent warning in there
 *  sits after the `if (!PUSH) return` guard, so with pushing disabled, which is
 *  this project's mandated setting, it can never run. That left the run printing
 *  "everything else up to date" while an uncommitted or untracked file was on
 *  neither GitHub nor drive B. Reporting it is not a failure: it is the normal
 *  state of a working day, and the author is the one who decides when to commit.
 *
 *  Returns the count so the final verdict line can carry it: backup/README.txt
 *  tells the owner to read the LAST line, so a caveat further up is one they
 *  will never see. */
async function reportUnprotectedWork() {
	try {
		// Deliberately NOT stdout.trim(): porcelain puts a two-character status in
		// columns 1-2, and a modified-not-staged file leads with a SPACE. Trimming
		// the whole output eats that space on the first line only, shifting its
		// slice by one and turning ".gitignore" into "gitignore". Strip trailing
		// newlines only, so every line keeps its exact 3-character prefix.
		const { stdout } = await execAsync('git status --porcelain', { cwd: PROJECT })
		const changed = stdout.replace(/\n+$/, '')
		if (!changed.trim()) {
			say('working tree: clean, nothing uncommitted')
			return 0
		}
		const files = changed.split('\n').map((l) => l.slice(3).trim()).filter(Boolean)
		say(`working tree: ${files.length} uncommitted or untracked path(s), NOT on GitHub`)
		for (const f of files.slice(0, 10)) say(`  ${f}`)
		if (files.length > 10) say(`  ...and ${files.length - 10} more`)
		say('  these are protected by drive B only if they sit inside backup/.')
		say('  Commit and push them yourself if you want them off this machine.')
		return files.length
	} catch (error) {
		say(`working tree: could not be checked (${reason(error)})`)
		return 0
	}
}

/** Every file under backup/, as paths relative to backup/. */
async function listFiles(root, prefix = '') {
	const found = []
	for (const entry of await fs.readdir(path.join(root, prefix), { withFileTypes: true })) {
		const relative = path.join(prefix, entry.name)
		if (entry.isDirectory()) found.push(...(await listFiles(root, relative)))
		// Skip the log, and skip any .partial left by a run that died between
		// wrangler writing and the rename. Half a dump is not worth mirroring.
		else if (entry.name !== path.basename(LOG) && !entry.name.endsWith('.partial')) found.push(relative)
	}
	return found
}

/** Copy backup/ to drive B and verify by hashing both sides. */
async function mirror() {
	// Two CONFIG mistakes that would otherwise crash obscurely or pass silently.
	//
	// The placeholder: Windows rejects < and > in a path, so leaving it in
	// surfaces as a bare ENOENT from mkdir, reading like a broken drive.
	//
	// Single backslashes: 'B:\Claude Backup\Foo' is not a syntax error in JS,
	// it quietly becomes "B:Claude BackupFoo" because \C and \F are not escape
	// sequences. That writes a real folder in the wrong place and then reports
	// success, which is the worst possible outcome for a backup.
	if (REMOTE.includes('<')) {
		say(`mirror FAILED: REMOTE is still the placeholder, edit CONFIG (${REMOTE})`)
		return false
	}
	if (!REMOTE.startsWith('B:\\Claude Backup\\')) {
		say('mirror FAILED: REMOTE must sit under B:\\Claude Backup\\ and needs')
		say(`  doubled backslashes in the string. Got: ${REMOTE}`)
		return false
	}

	// A missing drive is the difference between "backed up" and "not backed up",
	// so treat it as a hard failure rather than a warning nobody reads.
	if (!(await exists('B:\\'))) {
		say('mirror FAILED: drive B is not attached, nothing was copied')
		return false
	}

	await fs.mkdir(REMOTE, { recursive: true })
	const files = await listFiles(LOCAL)

	let copied = 0
	let matched = 0
	const failures = []

	for (const relative of files) {
		const from = path.join(LOCAL, relative)
		const to = path.join(REMOTE, relative)

		// Per file, so one locked or unreadable file is recorded as a failure
		// rather than aborting the loop and silently skipping everything after it.
		try {
			const before = await sha256(from)
			const unchanged = (await exists(to)) && (await sha256(to)) === before
			if (!unchanged) {
				await fs.mkdir(path.dirname(to), { recursive: true })
				await fs.copyFile(from, to)
				copied += 1
			}

			// Read the destination back rather than trusting the copy. This is the
			// whole point of the exercise: an unverified backup is a guess.
			if ((await sha256(to)) === before) matched += 1
			else failures.push(relative)
		} catch (error) {
			failures.push(`${relative} (${error.code || error.message})`)
		}
	}

	say(`mirror: ${files.length} files, ${copied} copied, ${matched} verified identical`)
	for (const bad of failures) say(`mirror FAILED to verify: ${bad}`)
	return failures.length === 0
}

/** Push commits already made to the private GitHub repo.
 *
 *  This deliberately does not commit anything. Committing on a timer would
 *  sweep up half-finished work, and worse, could publish a file the author had
 *  not yet decided to track. Only work the author already chose to commit gets
 *  sent, and never with --force. */
async function pushCommits() {
	if (!PUSH) {
		say('push: disabled in CONFIG for this project')
		return true
	}

	const git = async (command) => (await execAsync(`git ${command}`, { cwd: PROJECT })).stdout.trim()

	try {
		if (!(await git('remote'))) {
			say('push: no GitHub remote configured, skipping')
			return true
		}

		// Refuse to publish to the world on a timer.
		//
		// A setup session checks visibility once, by hand, at setup time. This
		// task then runs every day for years. If origin is public, every commit
		// the author ever makes is published unattended within a day, including
		// one that accidentally contains a key. The one-time scan cannot see a
		// secret that does not exist yet, so the guard has to live here.
		//
		// Unknown counts as refuse. If gh cannot answer, the safe assumption is
		// the one that does not publish.
		const visibility = await originVisibility(git)
		if (visibility !== 'PRIVATE' && !ALLOW_PUBLIC_PUSH) {
			say(`push REFUSED: origin visibility is ${visibility}, not PRIVATE.`)
			say('  A daily automatic push would publish every future commit.')
			say('  Make the repo private, or set ALLOW_PUBLIC_PUSH in CONFIG if')
			say('  publishing this project really is intended.')
			return false
		}

		// A repo with no commits has no HEAD, and everything below would fail
		// with "ambiguous argument 'HEAD'", which says nothing useful.
		try {
			await git('rev-parse --verify HEAD')
		} catch {
			say('push: no commits in this repository yet, nothing to push')
			return true
		}

		// Uncommitted work is not protected by the push, and the author may not
		// realise. Say so rather than reporting a clean success.
		const dirty = await git('status --porcelain')
		if (dirty) {
			const count = dirty.split('\n').length
			say(`push: note, ${count} uncommitted file(s) in the project are NOT backed up to GitHub`)
		}

		const branch = await git('rev-parse --abbrev-ref HEAD')

		// A branch with no upstream is one the author has never published. An
		// unattended task must not be the thing that publishes it for them.
		const tracked = await git(`branch --list --format=%(upstream) ${branch}`)
		if (!tracked) {
			say(`push: ${branch} has never been pushed, so it is NOT backed up to GitHub.`)
			say(`  Run "git push -u origin ${branch}" yourself once if you want it protected.`)
			return true
		}

		const ahead = await git(`rev-list --count ${tracked}..HEAD`)
		if (ahead === '0') {
			say('push: GitHub is already up to date')
			return true
		}

		say(`push: sending ${ahead} commit(s) to GitHub`)
		await git(`push origin ${branch}`)
		say('push: done')
		return true
	} catch (error) {
		// Offline, or the remote moved ahead. Neither is worth a force-push;
		// the local history and drive B are both still intact.
		say(`push FAILED: ${reason(error)}`)
		return false
	}
}

let dump = null
let collected = false
let mirrored = false
let pushed = false
let unprotected = 0

await markStart()

try {
	dump = await snapshotDatabase()
	collected = await collectLocalFiles()
	unprotected = await reportUnprotectedWork()

	// A freshness stamp, written before the mirror so it travels with it.
	//
	// Without this, drive B has no way to say when it was last refreshed:
	// backup.log is deliberately excluded from the mirror, and fs.copyFile
	// preserves the source's timestamps, so an untouched file copied today wears
	// its original date. A mirror frozen for six months and one refreshed this
	// morning would otherwise be indistinguishable on drive B.
	await fs.mkdir(LOCAL, { recursive: true })
	await fs.writeFile(
		path.join(LOCAL, 'last-run.txt'),
		`This backup last ran: ${new Date().toString()}\n` +
			`If that date is not recent, the backup has stopped running.\n`,
	)

	mirrored = await mirror()
	pushed = await pushCommits()

	// The caveat rides on the verdict line itself. The owner is told to read the
	// last line, so anything only mentioned further up does not reach them.
	const caveat = unprotected > 0
		? ` (${unprotected} uncommitted path(s) are on this machine only, see above)`
		: ''

	if (dump && collected && mirrored && pushed) say(`OK: drive B mirrored and everything else up to date${caveat}`)
	else if (mirrored) say(`PARTIAL: drive B is up to date, but see the failures above${caveat}`)
	else say('PROBLEM: the mirror did not complete, drive B is not up to date')
} catch (error) {
	// Nothing may escape without reaching the log. The log is the only thing the
	// user reads, so a crash that wrote nothing would leave the previous run's
	// "OK" sitting there as the last line, reading as healthy.
	say(`PROBLEM: the backup crashed before finishing: ${error.message || error}`)
} finally {
	try {
		await fs.mkdir(LOCAL, { recursive: true })
		await fs.appendFile(LOG, lines.join('\n') + '\n')
	} catch (error) {
		// The log itself is unwritable. Nowhere left to record that, but the
		// non-zero exit below still reaches the scheduled task's LastTaskResult.
		console.error(`could not write ${LOG}: ${error.message}`)
	}
}

process.exit(dump && collected && mirrored && pushed ? 0 : 1)
