<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, approveCase, listBenchmarkCases, startRun, type BenchmarkCase, type BenchmarkCaseFilters } from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import { CATEGORIES } from '$lib/components/benchmark/case_form';
	import { caseHref, runHref } from '$lib/components/benchmark/links';
	import { runRequest } from '$lib/components/benchmark/run_view';
	import { Button } from '$lib/components/ui/button';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';

	let suite = $derived(page.params.suite ?? '');
	let statusFilter = $derived((page.url.searchParams.get('status') ?? '') as NonNullable<BenchmarkCaseFilters['status']> | '');
	let categoryFilter = $derived((page.url.searchParams.get('category') ?? '') as NonNullable<BenchmarkCaseFilters['category']> | '');
	let cases = $state<BenchmarkCase[]>([]);
	let error = $state('');
	let reload = $state(0);
	let picked = $state<string[]>([]);
	let busy = $state(false);
	let canEdit = $derived(hasRole(session.user?.roles ?? [], 'reviewer'));

	const statusTone = (status: string) => (status === 'active' ? 'ok' : status === 'draft' ? 'warn' : 'neutral');
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
	<Page title={suite} description="Cases in this suite. Drafts from chat wait for a reviewer's approval.">
		{#snippet actions()}
			{#if canEdit}<Button variant="outline" size="sm" disabled={busy || activeIds.length === 0} onclick={run}
					>{picked.length ? `Run ${picked.length} selected` : 'Run all active'}</Button
				>{/if}
			{#if canEdit}<Button size="sm" href="/benchmark/cases/new?suite={encodeURIComponent(suite)}">New case</Button>{/if}
		{/snippet}
		{#snippet filters()}
			<label class="grid gap-1"
				><span class="field-label">Status</span>
				<select class="field w-36" value={statusFilter} onchange={(e) => filter('status', (e.currentTarget as HTMLSelectElement).value)}>
					<option value="">any</option><option value="active">active</option><option value="draft">draft</option><option value="retired">retired</option>
				</select>
			</label>
			<label class="grid gap-1"
				><span class="field-label">Category</span>
				<select class="field w-44" value={categoryFilter} onchange={(e) => filter('category', (e.currentTarget as HTMLSelectElement).value)}>
					<option value="">any</option>
					{#each CATEGORIES as c (c)}<option value={c}>{c}</option>{/each}
				</select>
			</label>
		{/snippet}

		{#if error}<Notice tone="error" class="mb-4">{error}</Notice>{/if}
		<div class="panel">
			<table class="data-table" aria-label="Cases">
				<thead><tr>{#if canEdit}<th class="w-8"><span class="sr-only">Pick</span></th>{/if}<th>Case</th><th class="num">v</th><th>Status</th><th>Category</th><th>Question</th><th><span class="sr-only">Actions</span></th></tr></thead>
				<tbody>
					{#each cases as c (c.case_id)}
						<tr>
							{#if canEdit}<td
									>{#if c.status === 'active'}<input
											type="checkbox"
											aria-label="Pick {c.case_id}"
											checked={picked.includes(c.case_id)}
											onchange={(e) => pick(c.case_id, (e.currentTarget as HTMLInputElement).checked)}
										/>{/if}</td
								>{/if}
							<td class="whitespace-nowrap"><a class="font-mono text-xs" href={caseHref(c.case_id)}>{c.case_id}</a></td>
							<td class="num font-mono">{c.version}</td>
							<td class="whitespace-nowrap"
								><ToneBadge tone={statusTone(c.status)}>{c.status}</ToneBadge>{#if c.source_trace_id}<span class="text-muted-foreground ml-1.5 text-xs">from chat</span>{/if}</td
							>
							<td class="text-muted-foreground">{c.category}</td>
							<td class="max-w-[48ch]">{c.question}</td>
							<td class="text-right">{#if canEdit && c.status === 'draft'}<Button size="xs" variant="outline" onclick={() => approve(c)}>Approve</Button>{/if}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			{#if cases.length === 0 && !error}<EmptyState class="m-4" title="No cases match." description="Change the filters or add a case." />{/if}
		</div>
	</Page>
</RoleGate>
