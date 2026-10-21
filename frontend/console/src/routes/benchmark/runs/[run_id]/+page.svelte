<script lang="ts">
	import { page } from '$app/state';
	import {
		ApiError,
		cancelRun,
		compareRuns,
		getRun,
		listBenchmarkCases,
		listRuns,
		type BenchmarkCase,
		type BenchmarkRun,
		type RunComparison,
		type RunResults
	} from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import ResultDrilldown from '$lib/components/benchmark/ResultDrilldown.svelte';
	import { compareHref, runHref, suiteHref } from '$lib/components/benchmark/links';
	import { byCategory, failureCounts, ribbon } from '$lib/components/benchmark/run_view';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import { live } from '$lib/live.svelte';

	let runId = $derived(page.params.run_id ?? '');
	let data = $state<RunResults | null>(null);
	let cases = $state<BenchmarkCase[]>([]);
	let others = $state<BenchmarkRun[]>([]);
	let baselineId = $state('');
	let comparison = $state<RunComparison | null>(null);
	let open = $state<string | null>(null);
	let error = $state('');
	let canRun = $derived(hasRole(session.user?.roles ?? [], 'reviewer'));

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		const id = runId;
		const event = live.lastRunEvent;
		if (event && event.key !== id && data) return;
		getRun(id)
			.then(async (result) => {
				data = result;
				error = '';
				const [list, runs] = await Promise.all([listBenchmarkCases({ suite: result.run.suite }), listRuns(result.run.suite)]);
				cases = list.items;
				others = runs.filter((r) => r.run_id !== id && r.status === 'completed');
				if (!baselineId && others.length) baselineId = others[0].run_id;
			})
			.catch((e) => (error = describe(e)));
	});

	$effect(() => {
		const [base, head] = [baselineId, runId];
		comparison = null;
		if (!base) return;
		compareRuns(base, head)
			.then((c) => (comparison = c))
			.catch(() => (comparison = null));
	});

	let caseMap = $derived(new Map(cases.map((c) => [c.case_id, c])));
	let items = $derived(data ? ribbon(data.run.aggregate, comparison?.base.aggregate ?? null) : []);
	let failures = $derived(data ? failureCounts(data.results) : []);
	let categories = $derived(data ? byCategory(data.results, cases) : []);
	let newlyFailing = $derived(new Set(comparison?.newly_failing.map((d) => d.case_id) ?? []));

	async function cancel() {
		try {
			await cancelRun(runId);
			data = await getRun(runId);
		} catch (e) {
			error = describe(e);
		}
	}
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#if data}
		{@const run = data.run}
		<nav class="crumbs"><a href="/benchmark">Benchmark</a> › <a href={suiteHref(run.suite)}>{run.suite}</a> › run {run.run_id.slice(0, 8)}</nav>
		<p class="meta">
			<strong>{run.status}</strong> · {Object.keys(run.case_versions).length} cases · {data.results.length} results
			{#if run.git_commit}· commit <code>{run.git_commit.slice(0, 10)}</code>{/if}
			{#if run.started_at}· started {run.started_at.slice(0, 16).replace('T', ' ')}{/if}
			{#if canRun && (run.status === 'queued' || run.status === 'running')}<button type="button" onclick={cancel}>Cancel run</button>{/if}
		</p>
		{#if run.status === 'queued'}<p class="muted">Waiting for the benchmark runner.</p>{/if}

		{#if others.length}
			<label class="baseline"
				>Baseline
				<select bind:value={baselineId}>
					<option value="">none</option>
					{#each others as o (o.run_id)}<option value={o.run_id}>{o.run_id.slice(0, 8)} · {o.started_at?.slice(0, 10) ?? ''}</option>{/each}
				</select>
				{#if baselineId}<a href={compareHref(baselineId, run.run_id)}>full comparison</a>{/if}
			</label>
		{/if}

		{#if items.length}
			<ul class="ribbon" aria-label="Summary">
				{#each items as item (item.key)}
					<li>
						<span class="label">{item.label}</span><span class="value">{item.value}</span>
						{#if item.delta}<span class="delta" class:good={item.better === true} class:worse={item.better === false}>{item.delta}</span>{/if}
					</li>
				{/each}
			</ul>
		{/if}

		<div class="panels">
			{#if failures.length}
				<section>
					<h2>Failure classes</h2>
					<ul class="plain">{#each failures as [cls, n] (cls)}<li><strong>{n}</strong> {cls}</li>{/each}</ul>
				</section>
			{/if}
			{#if categories.length}
				<section>
					<h2>By category</h2>
					<table class="grid">
						<tbody>{#each categories as c (c.category)}<tr><td>{c.category}</td><td>{c.passed}/{c.total}</td></tr>{/each}</tbody>
					</table>
				</section>
			{/if}
			{#if comparison && (comparison.newly_failing.length || comparison.newly_passing.length)}
				<section>
					<h2>Versus baseline</h2>
					{#if comparison.newly_failing.length}<p class="worse">Newly failing: {comparison.newly_failing.map((d) => d.case_id).join(', ')}</p>{/if}
					{#if comparison.newly_passing.length}<p class="good">Newly passing: {comparison.newly_passing.map((d) => d.case_id).join(', ')}</p>{/if}
				</section>
			{/if}
		</div>

		<h2>Cases</h2>
		<table class="grid results" aria-label="Results">
			<thead><tr><th>Case</th><th>Result</th><th>Failure class</th><th>Latency</th><th></th></tr></thead>
			<tbody>
				{#each data.results as r (r.case_id)}
					<tr class:newly={newlyFailing.has(r.case_id)}>
						<td>{r.case_id}</td>
						<td>{r.passed === null ? '—' : r.passed ? '✓ pass' : '✗ fail'}</td>
						<td>{r.failure_class ?? ''}</td>
						<td>{r.latency_ms ?? '—'} ms</td>
						<td><button type="button" class="link" aria-expanded={open === r.case_id} onclick={() => (open = open === r.case_id ? null : r.case_id)}>{open === r.case_id ? 'Hide' : 'Details'}</button></td>
					</tr>
					{#if open === r.case_id}
						<tr><td colspan="5"><ResultDrilldown result={r} testCase={caseMap.get(r.case_id) ?? null} /></td></tr>
					{/if}
				{/each}
			</tbody>
		</table>
		{#if others.length && !baselineId}<p class="muted">Pick a baseline to see what moved.</p>{/if}
		<p><a href={runHref(run.run_id)}>Permalink</a></p>
	{/if}
</RoleGate>

<style>
	.crumbs,
	.meta {
		font-size: 0.85rem;
	}
	.meta button {
		margin-left: 0.6rem;
		font: inherit;
		font-size: 0.8rem;
		padding: 0.15rem 0.6rem;
		cursor: pointer;
	}
	.baseline {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		font-size: 0.84rem;
	}
	select {
		font: inherit;
		padding: 0.2rem;
		background: var(--surface);
		color: inherit;
		border: 1px solid var(--border);
	}
	.ribbon {
		list-style: none;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
		margin: 0.8rem 0;
	}
	.ribbon li {
		display: grid;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 0.4rem;
		padding: 0.45rem 0.7rem;
		min-width: 8rem;
	}
	.label {
		font-size: 0.72rem;
		opacity: 0.75;
	}
	.value {
		font-size: 1.05rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.delta {
		font-size: 0.75rem;
	}
	.good {
		color: var(--ok);
	}
	.worse {
		color: var(--hard);
	}
	.panels {
		display: flex;
		flex-wrap: wrap;
		gap: 1.5rem;
	}
	h2 {
		font-size: 0.95rem;
		margin: 1rem 0 0.4rem;
	}
	.plain {
		list-style: none;
		padding: 0;
		margin: 0;
		font-size: 0.84rem;
	}
	.grid {
		border-collapse: collapse;
		font-size: 0.84rem;
	}
	.results {
		width: 100%;
	}
	.grid td,
	.grid th {
		border-bottom: 1px solid var(--border);
		padding: 0.3rem 0.5rem;
		text-align: left;
	}
	tr.newly td:first-child {
		border-left: 3px solid var(--hard);
	}
	.link {
		background: none;
		border: 0;
		color: var(--accent);
		cursor: pointer;
		font: inherit;
	}
	.muted {
		opacity: 0.7;
		font-size: 0.84rem;
	}
	.error {
		color: var(--hard);
	}
</style>
