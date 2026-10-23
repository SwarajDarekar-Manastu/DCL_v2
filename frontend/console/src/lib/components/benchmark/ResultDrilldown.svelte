<script lang="ts">
	import type { BenchmarkCase, BenchmarkResult } from '$lib/api_endpoint';
	import { caseHref, percent, score, viewerHref } from './links';
	import { checks, numericChecks, resultError, retrievalOf } from './run_view';
	import Notice from '$lib/components/shell/Notice.svelte';

	interface Props {
		result: BenchmarkResult;
		testCase: BenchmarkCase | null;
	}

	let { result, testCase }: Props = $props();
	let metrics = $derived(result.metrics ?? {});
	let error = $derived(resultError(result));
	let numbers = $derived(numericChecks(metrics));
	let scored = $derived(checks(metrics));
	let retrieval = $derived(retrievalOf(metrics));
	let mode = $derived(typeof metrics.mode === 'string' ? metrics.mode : null);
</script>

<section class="grid gap-4 px-4 py-4 text-sm" aria-label="Case drilldown">
	<p class="m-0">
		<a class="font-mono text-xs" href={caseHref(result.case_id)}>{result.case_id}</a> <span class="text-muted-foreground num">v{result.case_version}</span>
		{#if testCase}<span class="text-muted-foreground">·</span> {testCase.question}{/if}
		{#if result.trace_id}<span class="text-muted-foreground">· trace</span> <code>{result.trace_id}</code>{/if}
	</p>

	{#if error}
		<Notice tone="error">The runner could not score this case: {error}</Notice>
	{:else}
		{#if mode}<p class="text-muted-foreground m-0">Answer mode <code class="text-foreground">{mode}</code></p>{/if}
		<div class="grid gap-4 lg:grid-cols-2">
			{#if numbers.length}
				<div class="grid content-start gap-1.5">
					<h4 class="eyebrow">Numbers</h4>
					<div class="bg-card overflow-hidden rounded-md border">
						<table class="data-table [--sticky-top:0px]">
							<thead><tr><th>Metric</th><th class="num">Expected</th><th class="num">Tolerance</th><th>Found in the answer</th><th><span class="sr-only">Within tolerance</span></th></tr></thead>
							<tbody>
								{#each numbers as n, i (i)}
									<tr class={n.ok === false ? 'text-hard' : ''}>
										<td>{n.metric}</td>
										<td class="num font-mono">{n.expected ?? '—'} {n.unit}</td>
										<td class="num font-mono">{n.tolerancePct === null ? '—' : `±${n.tolerancePct}%`}</td>
										<td class="font-mono">{n.found ?? 'not found'}</td>
										<td class={n.ok ? 'text-ok' : ''}>{n.ok === null ? '' : n.ok ? '✓' : '✗'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}

			<div class="grid content-start gap-1.5">
				<h4 class="eyebrow">Checks</h4>
				<ul class="m-0 grid list-none gap-1 p-0" aria-label="Checks">
					{#each scored as c (c.name)}
						<li class="flex gap-2">
							<span class={c.passed === false ? 'text-hard' : c.passed ? 'text-ok' : 'text-muted-foreground'} aria-label={c.passed === null ? 'not scored' : c.passed ? 'passed' : 'failed'}
								>{c.passed === null ? '–' : c.passed ? '✓' : '✗'}</span
							>
							<span><strong class="font-medium">{c.name}</strong>{#if c.detail}<span class="text-muted-foreground">{` · ${c.detail}`}</span>{/if}</span>
						</li>
					{:else}
						<li class="text-muted-foreground">No checks recorded.</li>
					{/each}
				</ul>
				<dl class="kv mt-2">
					<dt>Faithfulness</dt>
					<dd class="num">{percent(metrics.faithfulness)}</dd>
					<dt>Retrieval</dt>
					<dd class="num">recall@8 {percent(retrieval.recallAt8)} · recall@30 {percent(retrieval.recallAt30)} · rerank margin {score(retrieval.rerankMargin)}</dd>
					<dt>Latency, cost</dt>
					<dd class="num">{result.latency_ms ?? '—'} ms · {result.cost_estimate === null || result.cost_estimate === undefined ? '—' : `$${result.cost_estimate.toFixed(4)}`}</dd>
				</dl>
			</div>
		</div>
	{/if}

	{#if testCase?.spec.retrieval_gold_anchors?.length}
		<div class="grid gap-1">
			<h4 class="eyebrow">Gold passages</h4>
			<ul class="m-0 list-none space-y-0.5 p-0">
				{#each testCase.spec.retrieval_gold_anchors as g (g.doc_id + g.anchor)}
					<li><a class="font-mono text-xs" href={viewerHref(g.doc_id, g.anchor)}>{g.anchor}</a> <span class="text-muted-foreground text-xs">{g.doc_id}</span></li>
				{/each}
			</ul>
		</div>
	{/if}
</section>
