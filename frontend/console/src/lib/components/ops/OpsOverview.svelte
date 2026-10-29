<script lang="ts">
	// The OpsPage counters of file 08 §4.2 that exist today: files per pipeline step (a step opens its files),
	// queue depths, documents by status, open flags, the latest run per benchmark suite, model calls and cost
	// today. A part the API could not read shows its note.
	import type { OpsSummary, Step } from '$lib/api_endpoint';
	import { runHref } from '$lib/components/benchmark/links';
	import StepFiles from './StepFiles.svelte';
	import { STEP_GROUPS, STEP_HINT, STEP_LABEL } from './file_steps';

	interface Props {
		summary: OpsSummary;
	}

	let { summary }: Props = $props();
	const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`);
	const int = (n: number) => n.toLocaleString('en-US');
	const ORDER = ['PROCESSING', 'WAITING_FOR_ROUTE', 'HALTED', 'FAILED', 'ACTIVE_WITH_SOFT_FLAGS', 'ACTIVE', 'SUPERSEDED', 'QUARANTINED', 'DELETED'];
	let documents = $derived(
		Object.entries(summary.documents_by_status ?? {}).sort((a, b) => {
			const ia = ORDER.indexOf(a[0]);
			const ib = ORDER.indexOf(b[0]);
			return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
		})
	);
	let counts = $derived(new Map((summary.steps ?? []).map((s) => [s.step, s.count])));
	let busy = $derived((summary.queues ?? []).filter((q) => q.waiting > 0));
	let opened = $state<Step | null>(null);
</script>

<div class="grid gap-4 lg:grid-cols-2">
	<section class="panel" aria-label="Files by step">
		<div class="panel-header"><h2 class="panel-title">Files by step</h2></div>
		{#if summary.steps}
			<div class="grid gap-x-6 gap-y-3 p-4 sm:grid-cols-2">
				{#each STEP_GROUPS as group (group.title)}
					<div>
						<h3 class="text-muted-foreground m-0 mb-1 text-xs font-medium">{group.title}</h3>
						<ul class="m-0 grid list-none gap-0.5 p-0 text-sm">
							{#each group.steps as step (step)}
								{@const n = counts.get(step) ?? 0}
								<li>
									<button type="button" class="hover:bg-muted flex w-full cursor-pointer justify-between gap-2 rounded px-1.5 py-0.5 text-left" title={STEP_HINT[step]} onclick={() => (opened = step)}>
										<span class={step === 'failed' && n ? 'text-hard' : ''}>{STEP_LABEL[step]}</span><strong class="num font-mono {n ? '' : 'text-muted-foreground font-normal'}">{int(n)}</strong>
									</button>
								</li>
							{/each}
						</ul>
					</div>
				{/each}
			</div>
		{:else}<p class="text-muted-foreground m-0 p-4 text-sm">{summary.notes.steps ?? 'unavailable'}</p>{/if}
		<p class="text-muted-foreground m-0 border-t px-4 py-2 text-xs">
			Jobs in queues: {#if !summary.queues}{summary.notes.queues ?? 'unavailable'}{:else if busy.length}{busy.map((q) => `${q.queue} ${int(q.waiting)}`).join(' · ')}{:else}none waiting{/if}
		</p>
	</section>
	<StepFiles bind:step={opened} />

	<section class="panel" aria-label="Review">
		<div class="panel-header"><h2 class="panel-title">Open flags</h2></div>
		{#if summary.open_flags}
			<p class="m-0 flex gap-6 p-4">
				<span><strong class="num text-hard font-mono text-xl">{int(summary.open_flags.HARD ?? 0)}</strong> <span class="text-muted-foreground text-sm">HARD</span></span>
				<span><strong class="num text-warn font-mono text-xl">{int(summary.open_flags.SOFT ?? 0)}</strong> <span class="text-muted-foreground text-sm">SOFT</span></span>
				<a class="self-center text-sm" href="/review">Open the queue</a>
			</p>
		{:else}<p class="text-muted-foreground m-0 p-4 text-sm">{summary.notes.open_flags ?? 'unavailable'}</p>{/if}
	</section>

	<section class="panel" aria-label="Documents">
		<div class="panel-header"><h2 class="panel-title">Documents by status</h2></div>
		{#if summary.documents_by_status}
			<ul class="m-0 grid list-none gap-1 p-4 text-sm">
				{#each documents as [status, n] (status)}
					<li class="flex justify-between gap-2">
						<span class={status === 'HALTED' || status === 'FAILED' ? 'text-hard' : ''}>{status}</span><strong class="num font-mono">{int(n)}</strong>
					</li>
				{:else}<li class="text-muted-foreground">No documents yet.</li>{/each}
			</ul>
		{:else}<p class="text-muted-foreground m-0 p-4 text-sm">{summary.notes.documents_by_status ?? 'unavailable'}</p>{/if}
	</section>

	<section class="panel" aria-label="Model calls today">
		<div class="panel-header"><h2 class="panel-title">Model calls today (UTC)</h2></div>
		{#if summary.llm_today}
			<dl class="kv p-4">
				<dt>Calls</dt><dd class="num font-mono">{int(summary.llm_today.calls)}</dd>
				<dt>Tokens in / out / cached</dt><dd class="num font-mono">{int(summary.llm_today.input_tokens)} / {int(summary.llm_today.output_tokens)} / {int(summary.llm_today.cached_tokens)}</dd>
				<dt>Estimated cost</dt><dd class="num font-mono">{summary.llm_today.cost_estimate === null ? '—' : `$${summary.llm_today.cost_estimate.toFixed(2)}`}</dd>
			</dl>
		{:else}<p class="text-muted-foreground m-0 p-4 text-sm">{summary.notes.llm_today ?? 'unavailable'}</p>{/if}
	</section>

	<section class="panel lg:col-span-2" aria-label="Last benchmark runs">
		<div class="panel-header"><h2 class="panel-title">Last benchmark run per suite</h2></div>
		{#if summary.last_runs?.length}
			<table class="data-table">
				<thead><tr><th>Suite</th><th>Run</th><th>Status</th><th class="num">Pass rate</th><th>Started</th></tr></thead>
				<tbody>
					{#each summary.last_runs as r (r.run_id)}
						<tr>
							<td>{r.suite}</td>
							<td><a class="font-mono text-xs" href={runHref(r.run_id)}>{r.run_id.slice(0, 8)}</a></td>
							<td>{r.status}</td>
							<td class="num font-mono">{pct(r.pass_rate)}{r.cases_done !== null && r.cases_total !== null && r.cases_done < r.cases_total ? ` of ${r.cases_done}/${r.cases_total}` : ''}</td>
							<td class="num">{r.started_at?.slice(0, 16).replace('T', ' ') ?? '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{:else}<p class="text-muted-foreground m-0 p-4 text-sm">{summary.notes.last_runs ?? 'No benchmark runs yet.'}</p>{/if}
	</section>
</div>
