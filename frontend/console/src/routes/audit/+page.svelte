<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, listAudit, type AuditFilters, type AuditItem } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import AuditTimeline from '$lib/components/review/AuditTimeline.svelte';
	import { auditFiltersFromUrl, auditUrl } from '$lib/components/review/audit';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import { Button } from '$lib/components/ui/button';

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

{#snippet filterBar()}
	<form class="flex w-full flex-wrap items-end gap-3" onsubmit={apply} aria-label="Audit filters">
		<label class="field-label grid gap-1"
			>Entity type
			<select class="field text-foreground w-36" name="entity_type" value={filters.entity_type ?? ''}>
				<option value="">any</option>
				{#each TYPES as t (t)}<option value={t}>{t}</option>{/each}
			</select>
		</label>
		<label class="field-label grid gap-1"
			>Entity ids <input class="field text-foreground w-56" name="entity_id" value={(filters.entity_id ?? []).join(', ')} placeholder="case key, flag id, …" /></label
		>
		<label class="field-label grid gap-1">Actor <input class="field text-foreground w-44" name="actor" value={filters.actor ?? ''} /></label>
		<label class="field-label grid gap-1">Action <input class="field text-foreground w-32" name="action" value={filters.action ?? ''} /></label>
		<label class="field-label grid gap-1">From <input class="field text-foreground w-36" name="since" type="date" value={day(filters.since)} /></label>
		<label class="field-label grid gap-1">Before <input class="field text-foreground w-36" name="until" type="date" value={day(filters.until)} /></label>
		<div class="flex items-center gap-2">
			<Button type="submit">Apply</Button>
			<Button href="/audit" variant="ghost">Clear</Button>
		</div>
	</form>
{/snippet}

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<Page title="Audit" description="Who changed what, when, with the before and after of each change." filters={filterBar}>
		{#if error}
			<Notice tone="error">{error}</Notice>
		{:else}
			<AuditTimeline {items} />
			{#if nextCursor}<div class="mt-4 flex justify-center"><Button variant="outline" onclick={loadMore}>Load more</Button></div>{/if}
		{/if}
	</Page>
</RoleGate>
