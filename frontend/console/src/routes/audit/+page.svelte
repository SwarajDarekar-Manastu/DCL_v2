<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, listAudit, type AuditFilters, type AuditItem } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import AuditTimeline from '$lib/components/review/AuditTimeline.svelte';
	import { auditFiltersFromUrl, auditUrl } from '$lib/components/review/audit';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	const TYPES = ['case', 'flag', 'rule', 'entity', 'config', 'benchmark_case', 'document'] as const;

	let filters = $derived(auditFiltersFromUrl(page.url.searchParams));
	let items = $state<AuditItem[]>([]);
	let nextCursor = $state<string | null>(null);
	let error = $state('');

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		const f = filters;
		let cancelled = false;
		listAudit(f)
			.then((result) => {
				if (cancelled) return;
				items = result.items;
				nextCursor = result.next_cursor;
				error = '';
			})
			.catch((e) => !cancelled && (error = describe(e)));
		return () => {
			cancelled = true;
		};
	});

	async function loadMore() {
		if (!nextCursor) return;
		try {
			const more = await listAudit({ ...filters, cursor: nextCursor });
			items = [...items, ...more.items];
			nextCursor = more.next_cursor;
		} catch (e) {
			error = describe(e);
		}
	}

	function apply(event: SubmitEvent) {
		event.preventDefault();
		const data = new FormData(event.currentTarget as HTMLFormElement);
		const text = (k: string) => String(data.get(k) ?? '').trim() || undefined;
		const ids = (text('entity_id') ?? '').split(/\s*,\s*/).filter(Boolean);
		const next: AuditFilters = {
			entity_type: text('entity_type') as AuditFilters['entity_type'],
			entity_id: ids.length ? ids : undefined,
			actor: text('actor'),
			action: text('action'),
			since: text('since') ? new Date(`${text('since')}T00:00:00`).toISOString() : undefined,
			until: text('until') ? new Date(`${text('until')}T00:00:00`).toISOString() : undefined
		};
		goto(auditUrl(next), { keepFocus: true });
	}
	const day = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : '');
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<h1>Audit</h1>
	<form class="filters" onsubmit={apply} aria-label="Audit filters">
		<label
			>Entity type
			<select name="entity_type" value={filters.entity_type ?? ''}>
				<option value="">any</option>
				{#each TYPES as t (t)}<option value={t}>{t}</option>{/each}
			</select>
		</label>
		<label>Entity ids <input name="entity_id" value={(filters.entity_id ?? []).join(', ')} placeholder="case key, flag id, …" /></label>
		<label>Actor <input name="actor" value={filters.actor ?? ''} /></label>
		<label>Action <input name="action" value={filters.action ?? ''} /></label>
		<label>From <input name="since" type="date" value={day(filters.since)} /></label>
		<label>Before <input name="until" type="date" value={day(filters.until)} /></label>
		<button type="submit">Apply</button>
		<a href="/audit">Clear</a>
	</form>
	{#if error}
		<p role="alert">{error}</p>
	{:else}
		<AuditTimeline {items} />
		{#if nextCursor}<button type="button" onclick={loadMore}>Load more</button>{/if}
	{/if}
</RoleGate>

<style>
	h1 {
		font-size: 1.1rem;
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem 0.9rem;
		align-items: end;
		margin-bottom: 1rem;
		font-size: 0.82rem;
	}
	label {
		display: grid;
		gap: 0.15rem;
	}
	input,
	select {
		font: inherit;
		padding: 0.25rem;
		background: var(--surface);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
	}
	button {
		font: inherit;
		padding: 0.3rem 0.8rem;
		cursor: pointer;
	}
</style>
