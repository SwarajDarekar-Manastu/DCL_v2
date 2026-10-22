<script lang="ts">
	// The keys of one Settings section with typed editors. Edits form one batch: preview shows what it would
	// change (counts, bytes, cost), apply writes it with the versions the editor saw (file 08 §3.2).
	import {
		ApiError,
		applySettings,
		listSettings,
		previewSettings,
		type ConfigApplied,
		type ConfigChange,
		type ConfigEntry,
		type ConfigImpact
	} from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import KeyHistory from './KeyHistory.svelte';
	import { fromDraft, kindOf, sameValue, sectionKeys, toDraft, type SectionKey, type ValueKind } from './settings_form';

	interface Props {
		patterns: string[];
	}

	let { patterns }: Props = $props();
	let entries = $state<ConfigEntry[]>([]);
	let drafts = $state<Record<string, { kind: ValueKind; text: string }>>({});
	let fieldErrors = $state<Record<string, string>>({});
	let impacts = $state<ConfigImpact[] | null>(null);
	let applied = $state<ConfigApplied | null>(null);
	let description = $state('');
	let error = $state('');
	let notice = $state('');
	let busy = $state(false);
	let historyOpen = $state<string | null>(null);
	let loaded = $state(false);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	let rows = $derived(sectionKeys(patterns, entries));

	async function load() {
		try {
			entries = (await listSettings()).items;
			const next: typeof drafts = {};
			for (const row of sectionKeys(patterns, entries)) {
				const kind = row.entry ? kindOf(row.entry.value) : 'json';
				next[row.key] = { kind, text: row.entry ? toDraft(kind, row.entry.value) : '' };
			}
			drafts = next;
			fieldErrors = {};
			impacts = null;
			loaded = true;
		} catch (e) {
			error = describe(e);
		}
	}

	$effect(() => {
		void patterns;
		load();
	});

	function parse(row: SectionKey) {
		const draft = drafts[row.key];
		if (!draft || (!row.entry && draft.text.trim() === '')) return null;
		return fromDraft(draft.kind, draft.text);
	}

	let changes = $derived.by(() => {
		const out: ConfigChange[] = [];
		for (const row of rows) {
			const parsed = parse(row);
			if (parsed?.ok && !(row.entry && sameValue(parsed.value, row.entry.value))) {
				out.push({ key: row.key, value: parsed.value as ConfigChange['value'], expected_version: row.entry?.version ?? 0 });
			}
		}
		return out;
	});
	let parseErrors = $derived(
		Object.fromEntries(
			rows.flatMap((row) => {
				const parsed = parse(row);
				return parsed && !parsed.ok ? [[row.key, parsed.error]] : [];
			})
		) as Record<string, string>
	);
	let blocked = $derived(Object.keys(parseErrors).length > 0);

	function setDraft(key: string, text: string) {
		drafts[key] = { ...drafts[key], text };
		impacts = null;
		applied = null;
		delete fieldErrors[key];
	}

	async function act(run: () => Promise<void>) {
		busy = true;
		error = '';
		notice = '';
		try {
			await run();
		} catch (e) {
			if (e instanceof ApiError && e.status === 422) fieldErrors = e.errors;
			if (e instanceof ApiError && e.status === 409) {
				await load();
				error = `${e.detail}. Someone else changed this section; the current values are loaded. Make your edit again.`;
			} else error = describe(e);
		} finally {
			busy = false;
		}
	}

	const preview = () => act(async () => void (impacts = (await previewSettings({ changes })).impacts));

	const apply = () =>
		act(async () => {
			const result = await applySettings({ changes, description: description.trim() || null });
			await load();
			applied = result;
			description = '';
			notice = `Saved ${result.applied.map((a) => `${a.key} (v${a.version})`).join(', ')}.`;
		});

	function restored(message: string) {
		historyOpen = null;
		load().then(() => (notice = message));
	}

	const topExtensions = (counts: Record<string, number>) =>
		Object.entries(counts)
			.sort((a, b) => b[1] - a[1])
			.slice(0, 5)
			.map(([ext, n]) => `${ext} ${n}`)
			.join(', ');
	const fmtBytes = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${n} B`);
</script>

<div class="grid gap-4">
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	{#if notice}<Notice tone="success">{notice}</Notice>{/if}
	{#if loaded && rows.length === 0}<p class="text-muted-foreground m-0 text-sm">No keys of this section are set yet.</p>{/if}

	<ul class="m-0 grid gap-3 p-0" aria-label="Configuration keys">
		{#each rows as row (row.key)}
			{@const draft = drafts[row.key]}
			{@const problem = parseErrors[row.key] ?? fieldErrors[row.key]}
			<li class="list-none rounded-md border px-3 py-2.5">
				<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
					<code class="text-foreground text-sm">{row.key}</code>
					<span class="text-muted-foreground text-xs">
						{#if row.entry}v{row.entry.version} · {row.entry.updated_by} · {row.entry.updated_at.slice(0, 10)}{:else}not set{/if}
					</span>
					{#if row.entry}
						<button
							type="button"
							class="text-link ml-auto cursor-pointer border-0 bg-transparent p-0 text-xs"
							aria-expanded={historyOpen === row.key}
							onclick={() => (historyOpen = historyOpen === row.key ? null : row.key)}>{historyOpen === row.key ? 'Hide history' : 'History'}</button
						>
					{/if}
				</div>
				{#if draft}
					<label class="mt-2 grid gap-1">
						<span class="sr-only">Value of {row.key}</span>
						{#if draft.kind === 'boolean'}
							<span class="flex items-center gap-2 text-sm"
								><input
									type="checkbox"
									aria-label="Value of {row.key}"
									checked={draft.text === 'true'}
									disabled={busy}
									onchange={(e) => setDraft(row.key, (e.currentTarget as HTMLInputElement).checked ? 'true' : 'false')}
								/>{draft.text === 'true' ? 'on' : 'off'}</span
							>
						{:else if draft.kind === 'number'}
							<input class="field text-foreground w-48" inputmode="decimal" aria-label="Value of {row.key}" value={draft.text} disabled={busy} oninput={(e) => setDraft(row.key, (e.currentTarget as HTMLInputElement).value)} />
						{:else if draft.kind === 'text'}
							<input class="field text-foreground" aria-label="Value of {row.key}" value={draft.text} disabled={busy} oninput={(e) => setDraft(row.key, (e.currentTarget as HTMLInputElement).value)} />
						{:else}
							<textarea
								class="field text-foreground font-mono text-xs"
								aria-label="Value of {row.key}"
								rows={Math.min(12, Math.max(2, draft.text.split('\n').length + (draft.kind === 'lines' ? 1 : 0)))}
								placeholder={draft.kind === 'lines' ? 'one value per line' : row.entry ? '' : 'JSON value'}
								value={draft.text}
								disabled={busy}
								oninput={(e) => setDraft(row.key, (e.currentTarget as HTMLTextAreaElement).value)}
							></textarea>
							{#if draft.kind === 'lines'}<span class="text-muted-foreground text-xs">One value per line.</span>{/if}
						{/if}
					</label>
				{/if}
				{#if problem}<p class="text-hard m-0 mt-1 text-xs" role="alert">{problem}</p>{/if}
				{#if historyOpen === row.key}<KeyHistory key={row.key} onRestored={restored} />{/if}
			</li>
		{/each}
	</ul>

	{#if changes.length || impacts || blocked}
		<section class="bg-muted/40 sticky bottom-0 grid gap-3 rounded-md border px-3 py-3" aria-label="Pending changes">
			<p class="m-0 text-sm"><strong>{changes.length}</strong> changed {changes.length === 1 ? 'key' : 'keys'}: {changes.map((c) => c.key).join(', ')}</p>
			{#if impacts}
				<ul class="m-0 grid gap-1 p-0 text-sm" aria-label="Impact">
					{#each impacts as impact (impact.key)}
						<li class="list-none">
							<code>{impact.key}</code>: {impact.summary}
							{#if Object.keys(impact.counts).length}<span class="text-muted-foreground"> · {Object.entries(impact.counts).map(([k, n]) => `${k} ${n}`).join(' · ')}</span>{/if}
							{#if impact.bytes}<span class="text-muted-foreground"> · {fmtBytes(impact.bytes)}</span>{/if}
							{#if Object.keys(impact.by_extension).length}<span class="text-muted-foreground"> · {topExtensions(impact.by_extension)}</span>{/if}
							{#if impact.estimated_cost_usd !== null}<span> · about ${impact.estimated_cost_usd.toFixed(2)}</span>{/if}
							{#if impact.cost_note}<span class="text-muted-foreground"> ({impact.cost_note})</span>{/if}
						</li>
					{:else}
						<li class="text-muted-foreground list-none">No measurable effect on documents.</li>
					{/each}
				</ul>
			{/if}
			<label class="field-label grid gap-1"
				>Reason (kept with every new version)
				<input class="field text-foreground" bind:value={description} placeholder="why this change" />
			</label>
			<div class="flex gap-2">
				<Button variant="outline" disabled={busy || blocked || !changes.length} onclick={preview}>Preview</Button>
				<Button disabled={busy || blocked || !changes.length || !impacts} onclick={apply}>Apply</Button>
				<Button variant="ghost" disabled={busy} onclick={() => load()}>Discard</Button>
			</div>
			{#if blocked}<p class="text-hard m-0 text-xs">Fix the marked values to preview.</p>{:else if !impacts && changes.length}<p class="text-muted-foreground m-0 text-xs">Preview first to see what the change affects.</p>{/if}
		</section>
	{/if}

	{#if applied && (applied.released_downloads || applied.held_downloads || applied.dispatch_started)}
		<Notice tone="info"
			>Downloads released: {applied.released_downloads}, held: {applied.held_downloads}{applied.dispatch_started ? '; dispatch started' : ''}.</Notice
		>
	{/if}
</div>
