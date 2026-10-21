<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, getCase, listCases, type CaseDetail, type CaseFilters, type CaseSummary } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import { live } from '$lib/live.svelte';
	import CaseView from '$lib/components/review/CaseView.svelte';
	import QueueFilters from '$lib/components/review/QueueFilters.svelte';
	import QueueList from '$lib/components/review/QueueList.svelte';
	import { filtersFromUrl, urlFor } from '$lib/components/review/filters';
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
	<div class="review">
		<aside class="queue">
			<div class="queue-head">
				<h1>Queue</h1>
				{#if counts}<span><span class="hard">{counts.hard} HARD</span> / {counts.soft} SOFT</span>{/if}
				<a href="/review/rules">Rules</a>
			</div>
			<QueueFilters {filters} onChange={setFilters} />
			{#if listError}
				<p role="alert">{listError}</p>
			{:else}
				<QueueList {items} selectedKey={caseKey} onOpen={open} />
				{#if nextCursor}<button type="button" onclick={loadMore}>Load more</button>{/if}
			{/if}
			<p class="keys">Keys: j / k to move, Enter to open.</p>
		</aside>
		<section class="detail">
			{#if caseError}
				<p role="alert">{caseError}</p>
			{:else if detail}
				<CaseView {detail} me={session.user?.email ?? ''} onChanged={() => (reload += 1)} />
			{:else if caseKey}
				<p>Loading case…</p>
			{:else}
				<p class="empty">Select a case from the queue.</p>
			{/if}
		</section>
	</div>
</RoleGate>

<style>
	.review {
		display: grid;
		grid-template-columns: 19rem minmax(0, 1fr);
		gap: 1rem;
		align-items: start;
	}
	@media (max-width: 800px) {
		.review {
			grid-template-columns: 1fr;
		}
	}
	.queue {
		display: grid;
		gap: 0.6rem;
		position: sticky;
		top: 0.5rem;
		max-height: calc(100vh - 4.5rem);
		overflow-y: auto;
		padding-right: 0.25rem;
	}
	@media (max-width: 800px) {
		.queue {
			position: static;
			max-height: none;
		}
	}
	.queue-head {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		font-size: 0.82rem;
	}
	.queue-head a {
		margin-left: auto;
	}
	h1 {
		font-size: 1.1rem;
		margin: 0;
	}
	.hard {
		color: var(--hard);
		font-weight: 600;
	}
	.keys,
	.empty {
		font-size: 0.78rem;
		opacity: 0.7;
	}
</style>
