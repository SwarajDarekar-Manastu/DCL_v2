<script lang="ts">
	import { crumb } from '$lib/components/shell/crumb.svelte';
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, getCase, listCases, type CaseDetail, type CaseFilters, type CaseSummary } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import { live } from '$lib/live.svelte';
	import CaseView from '$lib/components/review/CaseView.svelte';
	import QueueFilters from '$lib/components/review/QueueFilters.svelte';
	import SavedFilters from '$lib/components/review/SavedFilters.svelte';
	import QueueList from '$lib/components/review/QueueList.svelte';
	import { filtersFromUrl, urlFor } from '$lib/components/review/filters';
	import InboxIcon from '@lucide/svelte/icons/inbox';
	import ListChecksIcon from '@lucide/svelte/icons/list-checks';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	let filters = $derived(filtersFromUrl(page.url.searchParams));
	let caseKey = $derived(page.url.searchParams.get('case'));

	let items = $state<CaseSummary[]>([]);
	let nextCursor = $state<string | null>(null);
	let counts = $state<{ hard: number; soft: number } | null>(null);
	let listError = $state('');
	let detail = $state<CaseDetail | null>(null);
	let caseError = $state('');
	let reload = $state(0);

	const describe = (e: unknown) =>
		e instanceof ApiError ? (e.status === 501 ? 'The review backend is not connected yet.' : e.detail) : String(e);

	// Queue: refetch on filter change, after an action, and when a case event arrives.
	$effect(() => {
		const f = filters;
		void reload;
		void live.lastCaseEvent;
		let cancelled = false;
		listCases(f)
			.then((list) => {
				if (cancelled) return;
				items = list.items;
				nextCursor = list.next_cursor;
				counts = { hard: list.open_hard, soft: list.open_soft };
				listError = '';
			})
			.catch((e) => !cancelled && (listError = describe(e)));
		return () => {
			cancelled = true;
		};
	});

	// Case: refetch when the selection changes, after an action, or when an event names this case.
	$effect(() => {
		const key = caseKey;
		void reload;
		const event = live.lastCaseEvent;
		if (!key) {
			detail = null;
			return;
		}
		const loadedKey = untrack(() => detail?.summary.case_key);
		if (event && event.key !== key && loadedKey === key) return;
		let cancelled = false;
		getCase(key)
			.then((d) => {
				if (cancelled) return;
				detail = d;
				caseError = '';
			})
			.catch((e) => {
				if (cancelled) return;
				detail = null;
				caseError = describe(e);
			});
		return () => {
			cancelled = true;
		};
	});

	// The open case names the last crumb, so the trail reads Review > <case> and Review goes back to the queue.
	$effect(() => {
		crumb.leaf = detail?.summary.title ?? '';
		return () => (crumb.leaf = '');
	});

	async function loadMore() {
		if (!nextCursor) return;
		try {
			const more = await listCases({ ...filters, cursor: nextCursor });
			items = [...items, ...more.items];
			nextCursor = more.next_cursor;
		} catch (e) {
			listError = describe(e);
		}
	}

	const open = (key: string) => goto(urlFor(filters, key), { keepFocus: true, noScroll: true });
	const setFilters = (next: CaseFilters) => goto(urlFor(next, caseKey), { keepFocus: true, noScroll: true });
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<div class="grid min-h-[calc(100vh-3rem)] grid-cols-[20rem_minmax(0,1fr)] xl:grid-cols-[23rem_minmax(0,1fr)]">
		<aside
			class="bg-sidebar sticky top-12 flex h-[calc(100vh-3rem)] min-h-0 flex-col border-r"
			aria-labelledby="queue-title"
		>
			<div class="grid gap-3 border-b px-4 pt-4 pb-3">
				<div class="flex items-center gap-2">
					<h1 id="queue-title" class="m-0 text-base">Queue</h1>
					{#if counts}
						<span class="num flex items-center gap-1.5 text-xs" aria-label="{counts.hard} HARD, {counts.soft} SOFT open">
							<span class="bg-hard-bg text-hard border-hard-border rounded-md border px-1.5 leading-4 font-medium">{counts.hard} HARD</span>
							<span class="text-muted-foreground">{counts.soft} SOFT</span>
						</span>
					{/if}
					<Button variant="ghost" size="sm" href="/review/rules" class="ml-auto"><ListChecksIcon />Rules</Button>
				</div>
				{#if filters.proposed_by_rule_id}
					<p class="bg-info-bg border-info-border m-0 flex flex-wrap items-center gap-x-2 rounded-md border px-3 py-2 text-xs">
						Only the files one rule has proposed units for.
						<button type="button" class="text-link cursor-pointer border-0 bg-transparent p-0 text-xs" onclick={() => setFilters({ ...filters, proposed_by_rule_id: undefined })}>Show all</button>
					</p>
				{/if}
				<QueueFilters {filters} onChange={setFilters} />
				<div class="mt-2.5"><SavedFilters owner={session.user?.email ?? ''} {filters} onApply={setFilters} /></div>
			</div>
			<div class="min-h-0 flex-1 overflow-y-auto">
				{#if listError}
					<div class="p-4"><Notice tone="error">{listError}</Notice></div>
				{:else}
					<QueueList {items} selectedKey={caseKey} onOpen={open} />
					{#if nextCursor}<div class="p-3"><Button variant="outline" size="sm" class="w-full" onclick={loadMore}>Load more</Button></div>{/if}
				{/if}
			</div>
			<p class="text-muted-foreground m-0 flex items-center gap-1.5 border-t px-4 py-2 text-xs">
				Keys: <kbd class="bg-muted rounded border px-1 text-[11px]">j</kbd> / <kbd class="bg-muted rounded border px-1 text-[11px]">k</kbd> to move,
				<kbd class="bg-muted rounded border px-1 text-[11px]">Enter</kbd> to open.
			</p>
		</aside>
		<section class="min-w-0 px-5 pt-5" aria-label="Case detail">
			{#if caseError}
				<Notice tone="error">{caseError}</Notice>
			{:else if detail}
				<CaseView {detail} me={session.user?.email ?? ''} onChanged={() => (reload += 1)} />
			{:else if caseKey}
				<p class="text-muted-foreground m-0 flex items-center gap-2" role="status">
					<LoaderCircleIcon class="size-4 animate-spin" aria-hidden="true" /> Loading case…
				</p>
			{:else}
				<div class="text-muted-foreground flex h-[60vh] flex-col items-center justify-center gap-2 text-center">
					<InboxIcon class="size-6" aria-hidden="true" />
					<p class="text-foreground m-0 font-medium">Select a case from the queue.</p>
					<p class="m-0 text-xs">Cases are sorted by how many files they unblock. HARD cases halt their documents.</p>
				</div>
			{/if}
		</section>
	</div>
</RoleGate>
