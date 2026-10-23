<script lang="ts">
	// Search canonical entities, merge duplicates and split wrongly merged aliases (file 08 §4.2 EntitiesPage).
	import { ApiError, mergeEntities, searchEntities, splitEntity, type Entity, type EntityType } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { ENTITY_TYPES, mergePlan, splitProblem } from './entities';

	const PAGE = 50;
	let query = $state('');
	let type = $state<EntityType | ''>('');
	let offset = $state(0);
	let items = $state<Entity[]>([]);
	let total = $state(0);
	let selected = $state<Entity[]>([]);
	let target = $state('');
	let splitting = $state<Entity | null>(null);
	let splitKeys = $state<string[]>([]);
	let splitName = $state('');
	let error = $state('');
	let notice = $state('');
	let busy = $state(false);
	let reload = $state(0);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		const q = { query, type, limit: PAGE, offset };
		void reload;
		const timer = setTimeout(() => {
			searchEntities(q)
				.then((page) => {
					items = page.items;
					total = page.total;
					error = '';
				})
				.catch((e) => (error = describe(e)));
		}, 250);
		return () => clearTimeout(timer);
	});

	const isSelected = (e: Entity) => selected.some((s) => s.entity_id === e.entity_id);
	function toggle(e: Entity, on: boolean) {
		selected = on ? [...selected, e] : selected.filter((s) => s.entity_id !== e.entity_id);
		if (!selected.some((s) => s.entity_id === target)) target = selected[0]?.entity_id ?? '';
	}
	let plan = $derived(mergePlan(selected, target));

	async function act(run: () => Promise<string>) {
		busy = true;
		error = '';
		notice = '';
		try {
			notice = await run();
			reload += 1;
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	const merge = () =>
		act(async () => {
			const p = plan!;
			const kept = await mergeEntities(p.target.entity_id, p.sources.map((s) => s.entity_id));
			selected = [];
			target = '';
			return `Merged ${p.sources.map((s) => s.canonical_name).join(', ')} into ${kept.canonical_name}: now ${kept.aliases.length} aliases, ${kept.mentions} mentions.`;
		});

	function startSplit(e: Entity) {
		splitting = e;
		splitKeys = [];
		splitName = '';
	}
	let splitIssue = $derived(splitting ? splitProblem(splitting, splitKeys, splitName) : null);
	const split = () =>
		act(async () => {
			const e = splitting!;
			const created = await splitEntity(e.entity_id, splitKeys, splitName.trim());
			splitting = null;
			return `Split ${created.aliases.length} alias${created.aliases.length === 1 ? '' : 'es'} off ${e.canonical_name} into ${created.canonical_name}.`;
		});
</script>

<div class="grid gap-4">
	<form class="flex flex-wrap items-end gap-3" role="search" aria-label="Find entities" onsubmit={(e) => e.preventDefault()}>
		<label class="field-label grid gap-1"
			>Name or alias
			<input class="field w-72" type="search" bind:value={query} oninput={() => (offset = 0)} placeholder="e.g. HTP, Inconel, ECSS-E-ST-35" />
		</label>
		<label class="field-label grid gap-1"
			>Type
			<select class="field w-48" bind:value={type} onchange={() => (offset = 0)}>
				<option value="">any</option>
				{#each ENTITY_TYPES as t (t)}<option value={t}>{t.replace(/_/g, ' ')}</option>{/each}
			</select>
		</label>
		<span class="text-muted-foreground text-sm">{total} {total === 1 ? 'entity' : 'entities'}</span>
	</form>

	{#if error}<Notice tone="error">{error}</Notice>{/if}
	{#if notice}<Notice tone="success">{notice}</Notice>{/if}

	{#if selected.length >= 2 && plan}
		<section class="panel grid gap-2 p-3 text-sm" aria-label="Merge">
			<label class="field-label grid w-fit gap-1"
				>Keep
				<select class="field w-72" bind:value={target}>
					{#each selected as s (s.entity_id)}<option value={s.entity_id}>{s.canonical_name} ({s.type})</option>{/each}
				</select>
			</label>
			{#if plan.problem}
				<Notice tone="warning">{plan.problem}</Notice>
			{:else}
				<p class="m-0">
					Fold {plan.sources.map((s) => s.canonical_name).join(', ')} into <strong>{plan.target.canonical_name}</strong>: {plan.aliases} aliases and
					{plan.mentions} mentions move. This is audited; a wrong merge is undone with Split.
				</p>
			{/if}
			<div class="flex gap-2">
				<Button size="sm" disabled={busy || !!plan.problem} onclick={merge}>Merge {selected.length} entities</Button>
				<Button size="sm" variant="ghost" disabled={busy} onclick={() => ((selected = []), (target = ''))}>Clear selection</Button>
			</div>
		</section>
	{/if}

	<div class="table-scroll">
		<table class="data-table" aria-label="Entities">
			<thead><tr><th><span class="sr-only">Select</span></th><th>Name</th><th>Type</th><th>Aliases</th><th class="num">Mentions</th><th class="num">Documents</th><th></th></tr></thead>
			<tbody>
				{#each items as e (e.entity_id)}
					<tr>
						<td><input type="checkbox" aria-label="Select {e.canonical_name}" checked={isSelected(e)} onchange={(ev) => toggle(e, (ev.currentTarget as HTMLInputElement).checked)} /></td>
						<td class="font-medium">{e.canonical_name}</td>
						<td class="text-muted-foreground text-xs">{e.type.replace(/_/g, ' ')}</td>
						<td class="text-xs">{e.aliases.map((a) => a.alias).join(', ') || '—'}</td>
						<td class="num font-mono">{e.mentions}</td>
						<td class="num font-mono">{e.documents}</td>
						<td class="text-right">{#if e.aliases.length > 1}<Button variant="ghost" size="xs" onclick={() => startSplit(e)}>Split</Button>{/if}</td>
					</tr>
					{#if splitting?.entity_id === e.entity_id}
						<tr class="hover:bg-transparent">
							<td colspan="7">
								<form class="grid gap-2 p-2 text-sm" aria-label="Split {e.canonical_name}" onsubmit={(ev) => (ev.preventDefault(), split())}>
									<fieldset class="m-0 flex flex-wrap gap-3 border-0 p-0">
										<legend class="field-label mb-1">Aliases that belong to the new entity</legend>
										{#each e.aliases as a (a.alias_key)}
											<label class="flex items-center gap-1.5"
												><input
													type="checkbox"
													checked={splitKeys.includes(a.alias_key)}
													onchange={(ev) =>
														(splitKeys = (ev.currentTarget as HTMLInputElement).checked ? [...splitKeys, a.alias_key] : splitKeys.filter((k) => k !== a.alias_key))}
												/>{a.alias}</label
											>
										{/each}
									</fieldset>
									<label class="field-label grid w-fit gap-1">New entity name <input class="field w-72" bind:value={splitName} /></label>
									{#if splitIssue}<p class="text-muted-foreground m-0 text-xs">{splitIssue}</p>{/if}
									<div class="flex gap-2">
										<Button type="submit" size="sm" disabled={busy || !!splitIssue}>Split</Button>
										<Button size="sm" variant="ghost" onclick={() => (splitting = null)}>Cancel</Button>
									</div>
								</form>
							</td>
						</tr>
					{/if}
				{:else}<tr><td colspan="7" class="text-muted-foreground">No entities match.</td></tr>{/each}
			</tbody>
		</table>
	</div>
	{#if total > PAGE}
		<div class="flex items-center gap-2 text-sm">
			<Button size="sm" variant="outline" disabled={offset === 0} onclick={() => (offset = Math.max(0, offset - PAGE))}>Previous</Button>
			<span class="text-muted-foreground">{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
			<Button size="sm" variant="outline" disabled={offset + PAGE >= total} onclick={() => (offset += PAGE)}>Next</Button>
		</div>
	{/if}
</div>
