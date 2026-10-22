<script lang="ts">
	import type { BenchmarkCase, BenchmarkResult } from '$lib/api_endpoint';
	import { caseHref, percent, score, viewerHref } from './links';
	import { numericChecks } from './run_view';
	import Notice from '$lib/components/shell/Notice.svelte';

	interface Props {
		result: BenchmarkResult;
		testCase: BenchmarkCase | null;
	}

	let { result, testCase }: Props = $props();
	let metrics = $derived(result.metrics ?? {});
	let numbers = $derived(numericChecks(metrics));
	const obj = (v: unknown) => (v !== null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
	let citations = $derived(obj(metrics.citations));
	let tools = $derived(obj(metrics.tools));
	let warnings = $derived(Array.isArray(metrics.warnings) ? (metrics.warnings as unknown[]).map(String) : []);
	const list = (v: unknown) => (Array.isArray(v) ? v.map(String).join(', ') : '—');
</script>

<section class="grid gap-4 px-4 py-4 text-sm" aria-label="Case drilldown">
	<p class="m-0">
		<a class="font-mono text-xs" href={caseHref(result.case_id)}>{result.case_id}</a> <span class="text-muted-foreground num">v{result.case_version}</span>
		{#if testCase}<span class="text-muted-foreground">·</span> {testCase.question}{/if}
		{#if result.trace_id}<span class="text-muted-foreground">· trace</span> <code>{result.trace_id}</code>{/if}
	</p>

	<div class="grid gap-4 lg:grid-cols-2">
		{#if numbers.length}
			<div class="grid content-start gap-1.5">
				<h4 class="eyebrow">Numbers</h4>
				<div class="bg-card overflow-hidden rounded-md border">
					<table class="data-table [--sticky-top:0px]">
						<thead><tr><th>Metric</th><th class="num">Expected</th><th class="num">Actual</th><th>Unit</th><th><span class="sr-only">Within tolerance</span></th></tr></thead>
						<tbody>
							{#each numbers as n, i (i)}
								<tr class={n.within === false ? 'text-hard' : ''}>
									<td>{n.metric}</td><td class="num font-mono">{n.expected ?? '—'}</td><td class="num font-mono">{n.actual ?? '—'}</td><td>{n.unit}</td>
									<td class={n.within ? 'text-ok' : ''}>{n.within === null ? '' : n.within ? '✓' : '✗'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<dl class="kv content-start">
			<dt>Citations</dt>
			<dd>
				recall {percent(citations.recall)} · precision {percent(citations.precision)}
				{#if Array.isArray(citations.forbidden_cited) && citations.forbidden_cited.length}<span class="text-hard">· cited forbidden: {list(citations.forbidden_cited)}</span>{/if}
			</dd>
			<dt>Tools</dt>
			<dd class={tools.match === false ? 'text-hard' : ''}>expected {list(tools.expected)} · actual {list(tools.actual)}</dd>
			<dt>Faithfulness</dt>
			<dd class="num">{percent(metrics.faithfulness)}</dd>
			<dt>Retrieval</dt>
			<dd class="num">recall@8 {percent(metrics.recall_at_8)} · recall@30 {percent(metrics.recall_at_30)} · reranker margin {score(typeof metrics.reranker_margin === 'number' ? metrics.reranker_margin : null)}</dd>
			<dt>Latency, cost</dt>
			<dd class="num">{result.latency_ms ?? '—'} ms · {result.cost_estimate === null || result.cost_estimate === undefined ? '—' : `$${result.cost_estimate.toFixed(4)}`}</dd>
		</dl>
	</div>

	{#if typeof metrics.judge_rationale === 'string' && metrics.judge_rationale}
		<div class="grid gap-1">
			<h4 class="eyebrow">Judge</h4>
			<p class="m-0 max-w-[80ch]">{metrics.judge_rationale}</p>
		</div>
	{/if}
	{#each warnings as w (w)}<Notice tone="warning">{w}</Notice>{/each}

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
