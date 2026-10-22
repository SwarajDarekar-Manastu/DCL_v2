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
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
	import { cn } from '$lib/utils';
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
	let passedCount = $derived(data ? data.results.filter((r) => r.passed === true).length : 0);
	let failedCount = $derived(data ? data.results.filter((r) => r.passed === false).length : 0);
	let unscoredCount = $derived(data ? data.results.filter((r) => r.passed === null).length : 0);
	const runTone = (status: string) => (status === 'completed' ? 'ok' : /fail|error/i.test(status) ? 'hard' : 'neutral');
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
	{#if error && !data}
		<div class="px-6 pt-5"><Notice tone="error">{error}</Notice></div>
	{/if}
	{#if data}
		{@const run = data.run}
		<Page title="Run {run.run_id.slice(0, 8)}" width="full">
			{#snippet actions()}
				<Button variant="outline" size="sm" href={suiteHref(run.suite)}>Suite {run.suite}</Button>
				<Button variant="ghost" size="sm" href={runHref(run.run_id)}>Permalink</Button>
				{#if canRun && (run.status === 'queued' || run.status === 'running')}<Button variant="destructive" size="sm" onclick={cancel}>Cancel run</Button>{/if}
			{/snippet}
			{#snippet below()}
				<div class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
					<ToneBadge tone={runTone(run.status)}>{run.status}</ToneBadge>
					<span><span class="num text-foreground font-mono">{Object.keys(run.case_versions).length}</span> cases</span>
					<span><span class="num text-foreground font-mono">{passedCount + failedCount + unscoredCount}</span> results</span>
					<span class="text-ok"><span class="num font-mono font-medium">{passedCount}</span> passed</span>
					<span class={failedCount ? 'text-hard' : ''}><span class="num font-mono font-medium">{failedCount}</span> failed</span>
					{#if run.git_commit}<span>commit <code>{run.git_commit.slice(0, 10)}</code></span>{/if}
					{#if run.started_at}<span class="num">started {run.started_at.slice(0, 16).replace('T', ' ')}</span>{/if}
				</div>
			{/snippet}

			{#if error}<Notice tone="error" class="mb-4">{error}</Notice>{/if}
			{#if run.status === 'queued'}<Notice tone="info" class="mb-4">Waiting for the benchmark runner.</Notice>{/if}

			<div class="mb-4 flex flex-wrap items-end gap-3">
				{#if others.length}
					<label class="grid gap-1"
						><span class="field-label">Baseline</span>
						<select class="field w-56" bind:value={baselineId}>
							<option value="">none</option>
							{#each others as o (o.run_id)}<option value={o.run_id}>{o.run_id.slice(0, 8)} · {o.started_at?.slice(0, 10) ?? ''}</option>{/each}
						</select>
					</label>
					{#if baselineId}<Button variant="outline" size="sm" href={compareHref(baselineId, run.run_id)}>Full comparison</Button>{/if}
					{#if !baselineId}<span class="text-muted-foreground pb-1.5 text-sm">Pick a baseline to see what moved.</span>{/if}
				{/if}
			</div>

			{#if items.length}
				<ul class="m-0 mb-5 grid list-none grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border p-0 md:grid-cols-4" aria-label="Summary">
					{#each items as item (item.key)}
						<li class="bg-card grid gap-0.5 px-4 py-3">
							<span class="text-muted-foreground text-xs">{item.label}</span><span class="num font-mono text-lg font-semibold">{item.value}</span>
							{#if item.delta}<span
									class={cn('num font-mono text-xs', item.better === true && 'text-ok', item.better === false && 'text-hard', item.better === null && 'text-muted-foreground')}
									>{item.delta}</span
								>{/if}
						</li>
					{/each}
				</ul>
			{/if}

			{#if failures.length || categories.length || (comparison && (comparison.newly_failing.length || comparison.newly_passing.length))}
				<div class="mb-5 grid gap-4 lg:grid-cols-3">
					{#if failures.length}
						<section class="panel">
							<div class="panel-header"><h2 class="panel-title">Failure classes</h2></div>
							<ul class="m-0 list-none space-y-1 p-4 text-sm">
								{#each failures as [cls, n] (cls)}<li class="flex justify-between gap-3"><span class="font-mono text-xs">{cls}</span><strong class="num font-mono">{n}</strong></li>{/each}
							</ul>
						</section>
					{/if}
					{#if categories.length}
						<section class="panel">
							<div class="panel-header"><h2 class="panel-title">By category</h2></div>
							<table class="data-table">
								<tbody
									>{#each categories as c (c.category)}<tr><td>{c.category}</td><td class="num font-mono">{c.passed}/{c.total}</td></tr>{/each}</tbody
								>
							</table>
						</section>
					{/if}
					{#if comparison && (comparison.newly_failing.length || comparison.newly_passing.length)}
						<section class="panel">
							<div class="panel-header"><h2 class="panel-title">Versus baseline</h2></div>
							<div class="space-y-2 p-4 text-sm">
								{#if comparison.newly_failing.length}<p class="text-hard m-0">Newly failing: {comparison.newly_failing.map((d) => d.case_id).join(', ')}</p>{/if}
								{#if comparison.newly_passing.length}<p class="text-ok m-0">Newly passing: {comparison.newly_passing.map((d) => d.case_id).join(', ')}</p>{/if}
							</div>
						</section>
					{/if}
				</div>
			{/if}

			<section class="panel" aria-labelledby="cases-title">
				<div class="panel-header"><h2 id="cases-title" class="panel-title">Cases</h2></div>
				<table class="data-table" aria-label="Results">
					<thead><tr><th>Case</th><th>Result</th><th>Failure class</th><th class="num">Latency</th><th><span class="sr-only">Details</span></th></tr></thead>
					<tbody>
						{#each data.results as r (r.case_id)}
							<tr class={cn(newlyFailing.has(r.case_id) && 'shadow-[inset_3px_0_0_var(--hard)]', open === r.case_id && 'bg-muted/60')}>
								<td class="font-mono text-xs">{r.case_id}{#if newlyFailing.has(r.case_id)}<span class="sr-only"> (newly failing)</span>{/if}</td>
								<td>
									{#if r.passed === null}<span class="text-muted-foreground">—</span>{:else if r.passed}<ToneBadge tone="ok">✓ pass</ToneBadge>{:else}<ToneBadge
											tone="hard">✗ fail</ToneBadge
										>{/if}
								</td>
								<td class="font-mono text-xs">{r.failure_class ?? ''}</td>
								<td class="num font-mono">{r.latency_ms ?? '—'} ms</td>
								<td class="text-right">
									<Button variant="ghost" size="xs" aria-expanded={open === r.case_id} onclick={() => (open = open === r.case_id ? null : r.case_id)}
										>{open === r.case_id ? 'Hide' : 'Details'}</Button
									>
								</td>
							</tr>
							{#if open === r.case_id}
								<tr class="hover:bg-transparent"><td colspan="5" class="bg-muted/30 p-0"><ResultDrilldown result={r} testCase={caseMap.get(r.case_id) ?? null} /></td></tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</section>
		</Page>
	{/if}
</RoleGate>
