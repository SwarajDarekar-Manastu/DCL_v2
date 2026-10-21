<script lang="ts">
	import type { BenchmarkCase, BenchmarkResult } from '$lib/api_endpoint';
	import { caseHref, percent, score, viewerHref } from './links';
	import { numericChecks } from './run_view';

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

<section class="drill" aria-label="Case drilldown">
	<p class="head">
		<a href={caseHref(result.case_id)}>{result.case_id}</a> v{result.case_version}
		{#if testCase}· {testCase.question}{/if}
		{#if result.trace_id}· trace <code>{result.trace_id}</code>{/if}
	</p>

	{#if numbers.length}
		<h4>Numbers</h4>
		<table>
			<thead><tr><th>Metric</th><th>Expected</th><th>Actual</th><th>Unit</th><th></th></tr></thead>
			<tbody>
				{#each numbers as n, i (i)}
					<tr class:bad={n.within === false}>
						<td>{n.metric}</td><td>{n.expected ?? '—'}</td><td>{n.actual ?? '—'}</td><td>{n.unit}</td>
						<td>{n.within === null ? '' : n.within ? '✓' : '✗'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}

	<dl>
		<dt>Citations</dt>
		<dd>
			recall {percent(citations.recall)} · precision {percent(citations.precision)}
			{#if Array.isArray(citations.forbidden_cited) && citations.forbidden_cited.length}<span class="bad">· cited forbidden: {list(citations.forbidden_cited)}</span>{/if}
		</dd>
		<dt>Tools</dt>
		<dd class:bad={tools.match === false}>expected {list(tools.expected)} · actual {list(tools.actual)}</dd>
		<dt>Faithfulness</dt>
		<dd>{percent(metrics.faithfulness)}</dd>
		<dt>Retrieval</dt>
		<dd>recall@8 {percent(metrics.recall_at_8)} · recall@30 {percent(metrics.recall_at_30)} · reranker margin {score(typeof metrics.reranker_margin === 'number' ? metrics.reranker_margin : null)}</dd>
		<dt>Latency, cost</dt>
		<dd>{result.latency_ms ?? '—'} ms · {result.cost_estimate === null || result.cost_estimate === undefined ? '—' : `$${result.cost_estimate.toFixed(4)}`}</dd>
	</dl>

	{#if typeof metrics.judge_rationale === 'string' && metrics.judge_rationale}
		<h4>Judge</h4>
		<p>{metrics.judge_rationale}</p>
	{/if}
	{#each warnings as w (w)}<p class="warn">⚠ {w}</p>{/each}

	{#if testCase?.spec.retrieval_gold_anchors?.length}
		<h4>Gold passages</h4>
		<ul>
			{#each testCase.spec.retrieval_gold_anchors as g (g.doc_id + g.anchor)}
				<li><a href={viewerHref(g.doc_id, g.anchor)}>{g.anchor}</a> <span class="muted">{g.doc_id}</span></li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.drill {
		font-size: 0.82rem;
		padding: 0.5rem 0.75rem;
		background: var(--bg);
		border-left: 3px solid var(--border);
	}
	.head {
		margin: 0 0 0.4rem;
	}
	h4 {
		margin: 0.6rem 0 0.2rem;
		font-size: 0.8rem;
	}
	table {
		border-collapse: collapse;
	}
	th,
	td {
		border: 1px solid var(--border);
		padding: 0.15rem 0.45rem;
		text-align: left;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.2rem 0.8rem;
		margin: 0.5rem 0 0;
	}
	dt {
		opacity: 0.7;
	}
	dd {
		margin: 0;
	}
	.bad {
		color: var(--hard);
	}
	.warn {
		color: var(--warn);
		margin: 0.2rem 0;
	}
	.muted {
		opacity: 0.6;
		font-size: 0.75rem;
	}
	ul {
		margin: 0;
		padding-left: 1rem;
	}
</style>
