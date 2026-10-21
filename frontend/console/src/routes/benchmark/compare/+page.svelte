<script lang="ts">
	import { page } from '$app/state';
	import { ApiError, compareRuns, type RunComparison } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import { caseHref, runHref } from '$lib/components/benchmark/links';
	import { ribbon } from '$lib/components/benchmark/run_view';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	let base = $derived(page.url.searchParams.get('base') ?? '');
	let head = $derived(page.url.searchParams.get('head') ?? '');
	let data = $state<RunComparison | null>(null);
	let error = $state('');

	$effect(() => {
		const [b, h] = [base, head];
		if (!b || !h) {
			error = 'Choose two runs on the Benchmark page.';
			return;
		}
		compareRuns(b, h)
			.then((c) => {
				data = c;
				error = '';
			})
			.catch((e) => (error = e instanceof ApiError ? e.detail : String(e)));
	});

	let items = $derived(data ? ribbon(data.head.aggregate, data.base.aggregate) : []);
	const display = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<nav class="crumbs"><a href="/benchmark">Benchmark</a> › compare</nav>
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#if data}
		<h1>
			<a href={runHref(data.base.run_id)}>{data.base.run_id.slice(0, 8)}</a> → <a href={runHref(data.head.run_id)}>{data.head.run_id.slice(0, 8)}</a>
			<small>{data.head.suite}</small>
		</h1>
		{#if items.length}
			<ul class="ribbon" aria-label="Summary">
				{#each items as item (item.key)}
					<li>
						<span class="label">{item.label}</span><span class="value">{item.value}</span>
						{#if item.delta}<span class:good={item.better === true} class:worse={item.better === false}>{item.delta}</span>{/if}
					</li>
				{/each}
			</ul>
		{/if}
		{#each [{ title: 'Newly failing', rows: data.newly_failing, cls: 'worse' }, { title: 'Newly passing', rows: data.newly_passing, cls: 'good' }, { title: 'Still failing', rows: data.still_failing, cls: '' }] as group (group.title)}
			<h2 class={group.cls}>{group.title} ({group.rows.length})</h2>
			{#if group.rows.length}
				<table class="grid">
					<thead><tr><th>Case</th><th>Before</th><th>After</th></tr></thead>
					<tbody>
						{#each group.rows as d (d.case_id)}
							<tr>
								<td><a href={caseHref(d.case_id)}>{d.case_id}</a></td>
								<td>{d.base_passed === null ? 'not run' : d.base_passed ? 'pass' : `fail · ${d.base_failure_class ?? ''}`}</td>
								<td>{d.head_passed === null ? '—' : d.head_passed ? 'pass' : `fail · ${d.head_failure_class ?? ''}`}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{/each}
		<h2>Configuration changes</h2>
		{#if Object.keys(data.config_diff).length === 0}
			<p class="muted">Same configuration.</p>
		{:else}
			<table class="grid">
				<thead><tr><th>Setting</th><th>Before</th><th>After</th></tr></thead>
				<tbody>
					{#each Object.entries(data.config_diff) as [key, change] (key)}
						<tr><td><code>{key}</code></td><td>{display(change.base)}</td><td>{display(change.head)}</td></tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
</RoleGate>

<style>
	.crumbs {
		font-size: 0.85rem;
	}
	h1 {
		font-size: 1.1rem;
	}
	h1 small {
		font-size: 0.8rem;
		opacity: 0.7;
		margin-left: 0.5rem;
	}
	h2 {
		font-size: 0.95rem;
		margin: 1.1rem 0 0.4rem;
	}
	.ribbon {
		list-style: none;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
	}
	.ribbon li {
		display: grid;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 0.4rem;
		padding: 0.45rem 0.7rem;
		min-width: 8rem;
		font-size: 0.78rem;
	}
	.label {
		opacity: 0.75;
	}
	.value {
		font-size: 1.05rem;
		font-weight: 600;
	}
	.grid {
		border-collapse: collapse;
		font-size: 0.84rem;
	}
	.grid td,
	.grid th {
		border-bottom: 1px solid var(--border);
		padding: 0.3rem 0.5rem;
		text-align: left;
	}
	.good {
		color: var(--ok);
	}
	.worse {
		color: var(--hard);
	}
	.muted {
		opacity: 0.7;
	}
	.error {
		color: var(--hard);
	}
</style>
