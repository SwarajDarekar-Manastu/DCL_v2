<script lang="ts">
	import { goto } from '$app/navigation';
	import { ApiError, exportSuite, listRuns, listSuites, startRun, type BenchmarkRun, type SuiteSummary } from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import { compareHref, percent, runHref, suiteHref } from '$lib/components/benchmark/links';
	import { RUN_TONE } from '$lib/components/benchmark/run_view';
	import { Button } from '$lib/components/ui/button';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
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

	// While a run is going, its pass rate covers only the finished cases: say how many.
	const passRate = (r: BenchmarkRun) => {
		const { pass_rate, cases_done, cases_total } = r.aggregate ?? {};
		const value = percent(pass_rate);
		return typeof cases_done === 'number' && typeof cases_total === 'number' && cases_done < cases_total && value !== '—'
			? `${value} of ${cases_done}/${cases_total}`
			: value;
	};
	function toggle(runId: string) {
		picked = picked.includes(runId) ? picked.filter((p) => p !== runId) : [...picked, runId].slice(-2);
	}
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<Page title="Benchmark" description="Golden suites, runs and regressions. Pick two runs to compare them.">
		{#snippet actions()}
			<Button variant="outline" size="sm" href="/benchmark/retrieval">Retrieval lab</Button>
			{#if canRun}<Button size="sm" href="/benchmark/cases/new">New case</Button>{/if}
		{/snippet}

		{#if error}<Notice tone="error" class="mb-4">{error}</Notice>{/if}

		<section class="panel mb-6" aria-labelledby="suites-title">
			<div class="panel-header"><h2 id="suites-title" class="panel-title">Suites</h2></div>
			{#if suites.length === 0 && !error}
				<EmptyState class="m-4" title="No suites yet" description="Import one or create a case." />
			{:else}
				<table class="data-table" aria-label="Suites">
					<thead><tr><th>Suite</th><th class="num">Active</th><th>Drafts</th><th>Categories</th><th>Last run</th><th><span class="sr-only">Actions</span></th></tr></thead>
					<tbody>
						{#each suites as s (s.suite)}
							<tr>
								<td class="font-medium"><a href={suiteHref(s.suite)}>{s.suite}</a></td>
								<td class="num font-mono">{s.cases_by_status.active ?? 0}</td>
								<td>{#if s.cases_by_status.draft}<a href="{suiteHref(s.suite)}?status=draft">{s.cases_by_status.draft} to review</a>{:else}<span class="text-muted-foreground">0</span>{/if}</td>
								<td class="text-muted-foreground text-xs">{Object.entries(s.cases_by_category).map(([c, n]) => `${c} ${n}`).join(' · ')}</td>
								<td class="whitespace-nowrap">
									{#if s.last_run}<a href={runHref(s.last_run.run_id)}>{s.last_run.status}</a> · <span class="num font-mono">{percent(s.last_run.pass_rate)}</span>{:else}<span class="text-muted-foreground">—</span>{/if}
								</td>
								<td class="text-right whitespace-nowrap">
									{#if canRun}<Button size="xs" disabled={busy || !s.cases_by_status.active} onclick={() => run(s.suite)}>Run</Button>{/if}
									<Button variant="outline" size="xs" onclick={() => download(s.suite)}>Export</Button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>

		<section class="panel" aria-labelledby="runs-title">
			<div class="panel-header">
				<h2 id="runs-title" class="panel-title">Recent runs</h2>
				{#if picked.length === 2}
					<Button size="xs" href={compareHref(picked[0], picked[1])}>Compare the two selected runs</Button>
				{:else}
					<span class="text-muted-foreground text-xs">Select two runs to compare</span>
				{/if}
			</div>
			<table class="data-table" aria-label="Runs">
				<thead><tr><th class="w-8"><span class="sr-only">Select</span></th><th>Run</th><th>Suite</th><th>Status</th><th class="num">Cases</th><th class="num">Pass rate</th><th>Commit</th><th>Started</th></tr></thead>
				<tbody>
					{#each runs as r (r.run_id)}
						<tr class={picked.includes(r.run_id) ? 'bg-muted/60' : ''}>
							<td><input type="checkbox" aria-label="Select run {r.run_id.slice(0, 8)}" checked={picked.includes(r.run_id)} onchange={() => toggle(r.run_id)} /></td>
							<td><a class="font-mono text-xs" href={runHref(r.run_id)}>{r.run_id.slice(0, 8)}</a></td>
							<td>{r.suite}</td>
							<td><ToneBadge tone={RUN_TONE[r.status]}>{r.status}</ToneBadge></td>
							<td class="num font-mono">{Object.keys(r.case_versions).length}</td>
							<td class="num font-mono">{passRate(r)}</td>
							<td><code class="text-muted-foreground">{r.git_commit?.slice(0, 8) ?? ''}</code></td>
							<td class="num text-muted-foreground whitespace-nowrap">{r.started_at?.slice(0, 16).replace('T', ' ') ?? 'queued'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			{#if runs.length === 0 && !error}<p class="text-muted-foreground m-0 px-4 py-6 text-center">No runs yet.</p>{/if}
		</section>
	</Page>
</RoleGate>
