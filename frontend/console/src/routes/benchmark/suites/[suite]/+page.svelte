<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, approveCase, listBenchmarkCases, startRun, type BenchmarkCase, type BenchmarkCaseFilters } from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import { CATEGORIES } from '$lib/components/benchmark/case_form';
	import { caseHref, runHref } from '$lib/components/benchmark/links';
	import { runRequest } from '$lib/components/benchmark/run_view';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	let suite = $derived(page.params.suite ?? '');
	let statusFilter = $derived((page.url.searchParams.get('status') ?? '') as NonNullable<BenchmarkCaseFilters['status']> | '');
	let categoryFilter = $derived((page.url.searchParams.get('category') ?? '') as NonNullable<BenchmarkCaseFilters['category']> | '');
	let cases = $state<BenchmarkCase[]>([]);
	let error = $state('');
	let reload = $state(0);
	let picked = $state<string[]>([]);
	let busy = $state(false);
	let canEdit = $derived(hasRole(session.user?.roles ?? [], 'reviewer'));

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		void reload;
		listBenchmarkCases({ suite, status: statusFilter || undefined, category: categoryFilter || undefined })
			.then((list) => {
				cases = list.items;
				error = '';
			})
			.catch((e) => (error = describe(e)));
	});

	function filter(key: 'status' | 'category', value: string) {
		const params = new URLSearchParams(page.url.searchParams);
		if (value) params.set(key, value);
		else params.delete(key);
		goto(`?${params}`, { keepFocus: true, noScroll: true });
	}

	let activeIds = $derived(cases.filter((c) => c.status === 'active').map((c) => c.case_id));

	function pick(caseId: string, on: boolean) {
		picked = on ? [...picked, caseId] : picked.filter((id) => id !== caseId);
	}

	async function run() {
		busy = true;
		try {
			const created = await startRun(runRequest(suite, picked, activeIds));
			await goto(runHref(created.run_id));
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	async function approve(c: BenchmarkCase) {
		try {
			await approveCase(c.case_id);
			reload += 1;
		} catch (e) {
			error = describe(e);
		}
	}
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<nav class="crumbs"><a href="/benchmark">Benchmark</a> › {suite}</nav>
	<div class="filters">
		<label
			>Status
			<select value={statusFilter} onchange={(e) => filter('status', (e.currentTarget as HTMLSelectElement).value)}>
				<option value="">any</option><option value="active">active</option><option value="draft">draft</option><option value="retired">retired</option>
			</select>
		</label>
		<label
			>Category
			<select value={categoryFilter} onchange={(e) => filter('category', (e.currentTarget as HTMLSelectElement).value)}>
				<option value="">any</option>
				{#each CATEGORIES as c (c)}<option value={c}>{c}</option>{/each}
			</select>
		</label>
		{#if canEdit}<button type="button" disabled={busy || activeIds.length === 0} onclick={run}>{picked.length ? `Run ${picked.length} selected` : 'Run all active'}</button>{/if}
		{#if canEdit}<a href="/benchmark/cases/new?suite={encodeURIComponent(suite)}">New case</a>{/if}
	</div>
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	<table class="grid" aria-label="Cases">
		<thead><tr>{#if canEdit}<th><span class="sr">Pick</span></th>{/if}<th>Case</th><th>v</th><th>Status</th><th>Category</th><th>Question</th><th></th></tr></thead>
		<tbody>
			{#each cases as c (c.case_id)}
				<tr class:draft={c.status === 'draft'}>
					{#if canEdit}<td>{#if c.status === 'active'}<input type="checkbox" aria-label="Pick {c.case_id}" checked={picked.includes(c.case_id)} onchange={(e) => pick(c.case_id, (e.currentTarget as HTMLInputElement).checked)} />{/if}</td>{/if}
					<td><a href={caseHref(c.case_id)}>{c.case_id}</a></td>
					<td>{c.version}</td>
					<td>{c.status}{c.source_trace_id ? ' · from chat' : ''}</td>
					<td>{c.category}</td>
					<td>{c.question}</td>
					<td>{#if canEdit && c.status === 'draft'}<button type="button" onclick={() => approve(c)}>Approve</button>{/if}</td>
				</tr>
			{/each}
		</tbody>
	</table>
	{#if cases.length === 0 && !error}<p class="muted">No cases match.</p>{/if}
</RoleGate>

<style>
	.crumbs {
		font-size: 0.85rem;
	}
	.filters {
		display: flex;
		gap: 1rem;
		align-items: end;
		font-size: 0.84rem;
		margin: 0.6rem 0;
	}
	label {
		display: grid;
		gap: 0.15rem;
	}
	select {
		font: inherit;
		padding: 0.25rem;
		background: var(--surface);
		color: inherit;
		border: 1px solid var(--border);
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
		vertical-align: top;
	}
	tr.draft td:first-child {
		border-left: 3px solid var(--warn);
	}
	button {
		font: inherit;
		font-size: 0.8rem;
		padding: 0.15rem 0.6rem;
		cursor: pointer;
	}
	.sr {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	.muted {
		opacity: 0.7;
	}
	.error {
		color: var(--hard);
	}
</style>
