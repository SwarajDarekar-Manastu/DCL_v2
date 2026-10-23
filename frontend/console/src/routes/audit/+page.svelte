<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, listAudit, listCases, type AuditFilters, type AuditItem, type CaseSummary } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import AuditTimeline from '$lib/components/review/AuditTimeline.svelte';
	import { auditFiltersFromUrl, auditUrl, decisionsHref } from '$lib/components/review/audit';
	import Notice from '$lib/components/shell/Notice.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import { Button } from '$lib/components/ui/button';

	const TYPES = ['case', 'flag', 'rule', 'entity', 'config', 'benchmark_case', 'document'] as const;

	let filters = $derived(auditFiltersFromUrl(page.url.searchParams));
	let items = $state<AuditItem[]>([]);
	let nextCursor = $state<string | null>(null);
	let error = $state('');

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	// "Find a file": files that have at least one decision, by words in the name or path.
	let finder = $state('');
	let found = $state<CaseSummary[]>([]);
	let finding = $state(false);
	$effect(() => {
		const text = finder.trim();
		if (text.length < 2) {
			found = [];
			finding = false;
			return;
		}
		finding = true;
		const timer = setTimeout(
			() =>
				listCases({ decided: true, q: text, limit: 12 })
					.then((r) => (found = r.items))
					.catch((e) => (error = describe(e)))
					.finally(() => (finding = false)),
			250
		);
		return () => clearTimeout(timer);
	});

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
	<Page title="Audit" description="Who changed what, when, with the before and after of each change. Find a file to correct what was decided on it." filters={filterBar}>
		<section class="panel mb-5" aria-labelledby="find-title">
			<div class="panel-header"><h2 id="find-title" class="panel-title">Find a file to check or change its decisions</h2></div>
			<div class="panel-body grid gap-2">
				<input class="field w-full max-w-xl" type="search" placeholder="Part of the file name or folder, for example Test_01 or Injector 14" aria-label="Find a file" bind:value={finder} />
				{#if finder.trim().length < 2}
					<p class="text-muted-foreground m-0 text-xs">Each file shows who approved what and when, and lets you change a unit or reopen a decision, with a reason.</p>
				{:else if !finding && found.length === 0}
					<p class="text-muted-foreground m-0 text-sm">No file with a decision matches.</p>
				{:else}
					<ul class="m-0 grid list-none gap-1 p-0" aria-label="Files found" aria-busy={finding}>
						{#each found as file (file.case_key)}
							<li>
								<a href={decisionsHref(file.case_key)} class="hover:bg-muted flex flex-wrap items-baseline gap-x-3 rounded-md border px-3 py-2 no-underline">
									<strong class="text-foreground text-[13px] font-medium">{file.title}</strong>
									<span class="text-muted-foreground min-w-0 flex-1 truncate text-xs">{file.path ?? ''}</span>
									<ToneBadge tone="outline">{file.status}</ToneBadge>
								</a>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		</section>

		{#if error}
			<Notice tone="error">{error}</Notice>
		{:else}
			<AuditTimeline {items} />
			{#if nextCursor}<div class="mt-4 flex justify-center"><Button variant="outline" onclick={loadMore}>Load more</Button></div>{/if}
		{/if}
	</Page>
</RoleGate>
