<script lang="ts">
	import { goto } from '$app/navigation';
	import { ApiError, exportSuite, listRuns, listSuites, startRun, type BenchmarkRun, type SuiteSummary } from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import { compareHref, percent, runHref, suiteHref } from '$lib/components/benchmark/links';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import { live } from '$lib/live.svelte';

	let suites = $state<SuiteSummary[]>([]);
	let runs = $state<BenchmarkRun[]>([]);
	let error = $state('');
	let busy = $state(false);
	let picked = $state<string[]>([]);
	let canRun = $derived(hasRole(session.user?.roles ?? [], 'reviewer'));

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		void live.lastRunEvent;
		Promise.all([listSuites(), listRuns()])
			.then(([s, r]) => {
				suites = s;
				runs = r;
				error = '';
			})
			.catch((e) => (error = describe(e)));
	});

	async function run(suite: string) {
		busy = true;
		try {
			const created = await startRun({ suite });
			await goto(runHref(created.run_id));
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	async function download(suite: string) {
		try {
			const data = await exportSuite(suite);
			const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
			const a = Object.assign(document.createElement('a'), { href: url, download: `${suite}.json` });
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			error = describe(e);
		}
	}

	const passRate = (r: BenchmarkRun) => r.aggregate?.pass_rate;
	function toggle(runId: string) {
		picked = picked.includes(runId) ? picked.filter((p) => p !== runId) : [...picked, runId].slice(-2);
	}
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<div class="head">
		<h1>Benchmark</h1>
		<a href="/benchmark/retrieval">Retrieval lab</a>
		{#if canRun}<a href="/benchmark/cases/new">New case</a>{/if}
	</div>
	{#if error}<p class="error" role="alert">{error}</p>{/if}

	<h2>Suites</h2>
	{#if suites.length === 0 && !error}<p class="muted">No suites yet. Import one or create a case.</p>{/if}
	<table class="grid" aria-label="Suites">
		<thead><tr><th>Suite</th><th>Active</th><th>Drafts</th><th>Categories</th><th>Last run</th><th></th></tr></thead>
		<tbody>
			{#each suites as s (s.suite)}
				<tr>
					<td><a href={suiteHref(s.suite)}>{s.suite}</a></td>
					<td>{s.cases_by_status.active ?? 0}</td>
					<td>{#if s.cases_by_status.draft}<a href="{suiteHref(s.suite)}?status=draft">{s.cases_by_status.draft} to review</a>{:else}0{/if}</td>
					<td class="cats">{Object.entries(s.cases_by_category).map(([c, n]) => `${c} ${n}`).join(' · ')}</td>
					<td>
						{#if s.last_run}<a href={runHref(s.last_run.run_id)}>{s.last_run.status}</a> · {percent(s.last_run.pass_rate)}{:else}—{/if}
					</td>
					<td class="actions">
						{#if canRun}<button type="button" disabled={busy || !s.cases_by_status.active} onclick={() => run(s.suite)}>Run</button>{/if}
						<button type="button" onclick={() => download(s.suite)}>Export</button>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>

	<h2>Recent runs</h2>
	{#if picked.length === 2}<a class="compare" href={compareHref(picked[0], picked[1])}>Compare the two selected runs</a>{/if}
	<table class="grid" aria-label="Runs">
		<thead><tr><th></th><th>Run</th><th>Suite</th><th>Status</th><th>Cases</th><th>Pass rate</th><th>Commit</th><th>Started</th></tr></thead>
		<tbody>
			{#each runs as r (r.run_id)}
				<tr>
					<td><input type="checkbox" aria-label="Select run {r.run_id.slice(0, 8)}" checked={picked.includes(r.run_id)} onchange={() => toggle(r.run_id)} /></td>
					<td><a href={runHref(r.run_id)}>{r.run_id.slice(0, 8)}</a></td>
					<td>{r.suite}</td>
					<td>{r.status}</td>
					<td>{Object.keys(r.case_versions).length}</td>
					<td>{percent(passRate(r))}</td>
					<td><code>{r.git_commit?.slice(0, 8) ?? ''}</code></td>
					<td>{r.started_at?.slice(0, 16).replace('T', ' ') ?? 'queued'}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</RoleGate>

<style>
	.head {
		display: flex;
		gap: 1rem;
		align-items: baseline;
	}
	h1 {
		font-size: 1.15rem;
	}
	h2 {
		font-size: 1rem;
		margin-top: 1.4rem;
	}
	.grid {
		border-collapse: collapse;
		width: 100%;
		font-size: 0.84rem;
	}
	.grid th,
	.grid td {
		border-bottom: 1px solid var(--border);
		padding: 0.35rem 0.45rem;
		text-align: left;
	}
	.cats {
		font-size: 0.76rem;
		opacity: 0.85;
	}
	.actions {
		white-space: nowrap;
	}
	button {
		font: inherit;
		font-size: 0.8rem;
		padding: 0.2rem 0.6rem;
		cursor: pointer;
	}
	.compare {
		font-size: 0.85rem;
	}
	.muted {
		opacity: 0.7;
	}
	.error {
		color: var(--hard);
	}
</style>
